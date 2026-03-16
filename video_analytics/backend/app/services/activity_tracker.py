"""
Person-activity session tracker.

Maintains an in-memory map of currently-visible faces per camera and writes
sessions to PostgreSQL when people enter/leave the camera view.

Key calls (already wired in cameras.py):
  - update_presence(camera_id, camera_name, face_results)
      Called every face_recognition_stride frames with the latest list of
      recognised faces.  Opens new sessions, updates ongoing ones, and closes
      sessions for faces that have been absent > SESSION_GRACE_PERIOD_SECONDS.

  - flush_camera(camera_id, camera_name)
      Called when a camera is disconnected.  Closes all open sessions for
      that camera immediately.
"""

import logging
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

logger = logging.getLogger(__name__)

_lock = Lock()

# key: (camera_id, face_id)
# value: {session_id, identifier, is_known, last_seen_at, camera_name}
_active_sessions: dict[tuple, dict] = {}

# How long a face must be absent before its session is closed.
SESSION_GRACE_PERIOD_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Private DB helpers
# ---------------------------------------------------------------------------

def _db_open_session(
    identifier: str,
    is_known: bool,
    camera_id: str,
    camera_name: str,
    enter_time: datetime,
) -> int | None:
    """Insert a new session row and return its DB id (None if DB unavailable)."""
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return None

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO person_sessions
                    (person_identifier, is_known, camera_id, camera_name, session_date, enter_time)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (identifier, is_known, camera_id, camera_name, enter_time.date(), enter_time),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:
        logger.debug("Failed to open session in DB: %s", exc)
        return None


def _db_close_session(session_id: int, exit_time: datetime) -> None:
    """Set exit_time on a session row."""
    if session_id is None:
        return
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return

        with get_cursor() as cur:
            cur.execute(
                "UPDATE person_sessions SET exit_time = %s WHERE id = %s",
                (exit_time, session_id),
            )
    except Exception as exc:
        logger.debug("Failed to close session in DB: %s", exc)


def _db_update_identifier(session_id: int, identifier: str) -> None:
    """Upgrade an Unknown session to a named one when face recognition fires."""
    if session_id is None:
        return
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return

        with get_cursor() as cur:
            cur.execute(
                "UPDATE person_sessions SET person_identifier = %s, is_known = TRUE WHERE id = %s",
                (identifier, session_id),
            )
    except Exception as exc:
        logger.debug("Failed to update session identifier in DB: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_presence(camera_id: str, camera_name: str, face_results: list) -> None:
    """
    Process the latest face-recognition results for a camera frame.

    face_results — list of dicts with keys:
        "id"   : int   face/track ID assigned by the recognition module
        "name" : str   recognised name, or "Unknown"
        "bbox" : list  [x1, y1, x2, y2]  (not used here)

    Called from CameraFrameProcessor.process() every face_recognition_stride
    frames, so typically ~2 times per second at 25 fps / stride 12.
    """
    now = datetime.now(timezone.utc)
    seen_face_ids: set = set()

    with _lock:
        # ---- Process detections in current frame --------------------------
        for result in face_results:
            face_id = result.get("id")
            if face_id is None:
                continue

            seen_face_ids.add(face_id)
            name = str(result.get("name", "")).strip()
            is_known = bool(name and name.lower() != "unknown")

            key = (camera_id, face_id)

            if key not in _active_sessions:
                # New person — open a session
                identifier = name if is_known else f"Unknown_{uuid4().hex[:8]}"
                session_id = _db_open_session(
                    identifier, is_known, camera_id, camera_name, now
                )
                _active_sessions[key] = {
                    "session_id": session_id,
                    "identifier": identifier,
                    "is_known": is_known,
                    "last_seen_at": now,
                    "camera_name": camera_name,
                }
                logger.debug(
                    "Opened session: %s | camera=%s face_id=%s",
                    identifier, camera_name, face_id,
                )
            else:
                session = _active_sessions[key]
                session["last_seen_at"] = now

                # Upgrade: was Unknown, now identified
                if not session["is_known"] and is_known:
                    session["identifier"] = name
                    session["is_known"] = True
                    _db_update_identifier(session["session_id"], name)
                    logger.debug(
                        "Upgraded Unknown → %s (face_id=%s, camera=%s)",
                        name, face_id, camera_name,
                    )

        # ---- Close sessions that have exceeded the grace period -----------
        to_close = [
            key
            for key, session in _active_sessions.items()
            if key[0] == camera_id
            and key[1] not in seen_face_ids
            and (now - session["last_seen_at"]).total_seconds() > SESSION_GRACE_PERIOD_SECONDS
        ]

        for key in to_close:
            session = _active_sessions.pop(key)
            _db_close_session(session["session_id"], now)
            logger.debug(
                "Closed session: %s | camera=%s face_id=%s",
                session["identifier"], camera_name, key[1],
            )


def flush_camera(camera_id: str, camera_name: str) -> None:
    """
    Immediately close all open sessions for a camera.
    Called when the camera stream is stopped or the camera is deleted.
    """
    now = datetime.now(timezone.utc)

    with _lock:
        keys = [k for k in _active_sessions if k[0] == camera_id]
        for key in keys:
            session = _active_sessions.pop(key)
            _db_close_session(session["session_id"], now)

    if keys:
        logger.info(
            "Flushed %d open session(s) for camera %s (%s)",
            len(keys), camera_name, camera_id,
        )
