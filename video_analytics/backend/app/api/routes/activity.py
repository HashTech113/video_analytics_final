"""
REST API for person-activity sessions stored in PostgreSQL.

GET /api/activity
    Query params (all optional):
        activity_date       ISO date string, e.g. "2026-03-16"
        camera_id           filter to a specific camera
        person_identifier   case-insensitive substring match on the person name / ID

    Returns sessions grouped by (person, date) with time ranges:
    {
      "data": [
        {
          "person_label":     "John Doe",
          "is_known":         true,
          "camera_name":      "Lobby Camera",
          "activity_date":    "2026-03-16",
          "in_office_ranges": ["09:00:00-12:30:15", "13:00:00-17:45:02"]
        },
        ...
      ]
    }

GET /api/activity/persons
    Returns one record per unique person with aggregate stats.

GET /api/activity/dates
    Returns all dates that have at least one session.
"""

import logging
from collections import defaultdict

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _fmt_time(dt) -> str:
    """Format a datetime-aware value as HH:MM:SS."""
    if dt is None:
        return ""
    try:
        return dt.strftime("%H:%M:%S")
    except Exception:
        return str(dt)


@router.get("/activity")
async def get_activity(
    activity_date: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    person_identifier: str | None = Query(default=None),
):
    """
    Return person-activity sessions grouped by (person, date) so that each row
    represents one person's presence on one day, with all time ranges included.
    """
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return JSONResponse({"data": [], "db_available": False})

        conditions: list[str] = []
        params: list = []

        if activity_date:
            conditions.append("session_date = %s")
            params.append(activity_date)
        if camera_id:
            conditions.append("camera_id = %s")
            params.append(camera_id)
        if person_identifier:
            conditions.append("person_identifier ILIKE %s")
            params.append(f"%{person_identifier}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"""
            SELECT
                person_identifier,
                is_known,
                camera_name,
                session_date,
                enter_time,
                exit_time
            FROM person_sessions
            {where}
            ORDER BY session_date DESC, person_identifier, enter_time
        """

        with get_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        # Group by (date, person_identifier)
        grouped: dict[tuple, dict] = defaultdict(lambda: {
            "person_label": "",
            "is_known": False,
            "camera_name": "",
            "activity_date": "",
            "in_office_ranges": [],
        })

        for person_id, is_known, cam_name, sess_date, enter_time, exit_time in rows:
            key = (str(sess_date), person_id)
            group = grouped[key]
            group["person_label"] = person_id
            group["is_known"] = bool(is_known)
            group["camera_name"] = cam_name
            group["activity_date"] = str(sess_date)

            enter_str = _fmt_time(enter_time)
            exit_str = _fmt_time(exit_time)
            if enter_str and exit_str:
                group["in_office_ranges"].append(f"{enter_str}-{exit_str}")
            elif enter_str:
                group["in_office_ranges"].append(f"{enter_str}-ongoing")

        records = list(grouped.values())
        return JSONResponse({"data": records, "db_available": True})

    except Exception as exc:
        logger.exception("Error fetching activity records")
        return JSONResponse(
            {"data": [], "db_available": False, "error": str(exc)},
            status_code=500,
        )


@router.get("/activity/persons")
async def get_activity_persons():
    """
    Returns one record per unique person with aggregate session statistics.
    Known persons are listed before unknown ones.
    """
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return JSONResponse({"data": [], "db_available": False})

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    person_identifier,
                    is_known,
                    COUNT(*)                            AS session_count,
                    MIN(session_date)                   AS first_seen,
                    MAX(session_date)                   AS last_seen,
                    array_agg(DISTINCT camera_name)     AS cameras
                FROM person_sessions
                GROUP BY person_identifier, is_known
                ORDER BY is_known DESC, person_identifier
                """
            )
            rows = cur.fetchall()

        persons = [
            {
                "person_identifier": row[0],
                "is_known": bool(row[1]),
                "session_count": row[2],
                "first_seen": str(row[3]) if row[3] else None,
                "last_seen": str(row[4]) if row[4] else None,
                "cameras": list(row[5]) if row[5] else [],
            }
            for row in rows
        ]
        return JSONResponse({"data": persons, "db_available": True})

    except Exception as exc:
        logger.exception("Error fetching persons list")
        return JSONResponse(
            {"data": [], "db_available": False, "error": str(exc)},
            status_code=500,
        )


@router.get("/activity/dates")
async def get_activity_dates():
    """Returns all distinct dates that have at least one session, newest first."""
    try:
        from app.services.db import get_cursor, is_db_available  # noqa: PLC0415

        if not is_db_available():
            return JSONResponse({"data": [], "db_available": False})

        with get_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT session_date FROM person_sessions ORDER BY session_date DESC"
            )
            rows = cur.fetchall()

        return JSONResponse(
            {"data": [str(row[0]) for row in rows], "db_available": True}
        )

    except Exception as exc:
        logger.exception("Error fetching activity dates")
        return JSONResponse(
            {"data": [], "db_available": False, "error": str(exc)},
            status_code=500,
        )
