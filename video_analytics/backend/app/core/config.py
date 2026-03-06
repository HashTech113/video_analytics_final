from pathlib import Path
import os


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve_dir(env_name: str, default_relative: str) -> Path:
    raw_value = os.getenv(env_name, default_relative).strip()
    raw_path = Path(raw_value)
    if raw_path.is_absolute():
        return raw_path
    return BACKEND_DIR / raw_path


def _parse_origins(raw_origins: str) -> list[str]:
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["*"]


UPLOAD_DIR = _resolve_dir("VIDEO_UPLOAD_DIR", "uploads")
OUTPUT_DIR = _resolve_dir("VIDEO_OUTPUT_DIR", "outputs")
ANALYTICS_STORE = OUTPUT_DIR / "analytics_data.json"
FRAME_STRIDE = max(1, int(os.getenv("VIDEO_FRAME_STRIDE", "3")))
CORS_ALLOW_ORIGINS = _parse_origins(os.getenv("CORS_ALLOW_ORIGINS", "*"))
SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ts",
    ".m2ts",
}

SUPPORTED_USE_CASES = {
    "person_count",
    "person_recognition",
}

EXECUTABLE_VIDEO_USE_CASES = {
    "person_count",
}
