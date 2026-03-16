"""
PostgreSQL database initialisation.

The connection is attempted once at startup.  If psycopg2 is not installed,
or if the PostgreSQL server is unreachable, the module silently marks the
database as unavailable so that the rest of the application keeps running.

Environment variables (all optional, defaults shown):
    POSTGRES_HOST      localhost
    POSTGRES_PORT      5432
    POSTGRES_DB        video_analytics
    POSTGRES_USER      postgres
    POSTGRES_PASSWORD  postgres
"""

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DB_AVAILABLE = False

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "video_analytics")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")


def _make_conn():
    """Open a fresh connection.  Raises on any error."""
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=5,
    )


def _create_tables() -> None:
    conn = _make_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS person_sessions (
                    id            SERIAL PRIMARY KEY,
                    person_identifier TEXT        NOT NULL,
                    is_known      BOOLEAN         NOT NULL DEFAULT FALSE,
                    camera_id     TEXT            NOT NULL,
                    camera_name   TEXT            NOT NULL,
                    session_date  DATE            NOT NULL,
                    enter_time    TIMESTAMPTZ     NOT NULL,
                    exit_time     TIMESTAMPTZ,
                    created_at    TIMESTAMPTZ     DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ps_date       ON person_sessions(session_date)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ps_camera     ON person_sessions(camera_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ps_identifier ON person_sessions(person_identifier)"
            )
        conn.commit()
    finally:
        conn.close()


def init_db() -> bool:
    """
    Attempt to connect and create tables.

    Returns True on success.  Logs a warning and returns False if the DB
    cannot be reached (so the rest of the app keeps starting up).
    """
    global _DB_AVAILABLE  # noqa: PLW0603
    try:
        import psycopg2  # noqa: F401, PLC0415
    except ImportError:
        logger.warning(
            "psycopg2 not installed — person-activity tracking disabled. "
            "Run:  pip install psycopg2-binary"
        )
        _DB_AVAILABLE = False
        return False

    try:
        _create_tables()
        _DB_AVAILABLE = True
        logger.info(
            "PostgreSQL connected: %s:%s/%s",
            POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
        )
        return True
    except Exception as exc:
        logger.warning(
            "PostgreSQL unavailable (%s) — person-activity tracking disabled. "
            "Set POSTGRES_HOST / POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD env vars.",
            exc,
        )
        _DB_AVAILABLE = False
        return False


def is_db_available() -> bool:
    return _DB_AVAILABLE


@contextmanager
def get_cursor():
    """
    Yield a psycopg2 cursor backed by a short-lived connection.

    Each call opens and closes its own connection so there are no
    thread-safety concerns.  Raises RuntimeError if the DB is unavailable.
    """
    if not _DB_AVAILABLE:
        raise RuntimeError("Database not available")

    conn = _make_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
