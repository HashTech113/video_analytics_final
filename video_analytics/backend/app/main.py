from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.analytics import router as analytics_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.cameras import stop_all_camera_streams
from app.api.routes.jobs import router as jobs_router
from app.api.routes.uploads import router as uploads_router
from app.api.routes.videos import router as videos_router
from app.core.config import CORS_ALLOW_ORIGINS, OUTPUT_DIR, UPLOAD_DIR
from app.services.store import ensure_storage_dirs


def create_app() -> FastAPI:
    ensure_storage_dirs()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
    app.include_router(uploads_router)
    app.include_router(jobs_router)
    app.include_router(analytics_router)
    app.include_router(videos_router)
    app.include_router(cameras_router)

    @app.on_event("shutdown")
    async def on_shutdown():
        stop_all_camera_streams()

    return app


app = create_app()
