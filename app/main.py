import logging
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, get_settings
from app.data.repository import get_knowledge_source

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _configure_logging(settings: Settings) -> None:
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
    )


def create_app() -> FastAPI:
    settings = get_settings()  # missing/empty API_KEY raises here, before anything serves
    _configure_logging(settings)
    logger = structlog.get_logger()
    get_knowledge_source()  # missing KB file or empty section raises here too

    app = FastAPI(title="Cadre Support Bot")
    app.include_router(router)

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    else:
        logger.warning("frontend_dist_missing", path=str(FRONTEND_DIST))

    logger.info(
        "app_created",
        environment=settings.environment,
        mock_llm=settings.mock_llm,
    )
    return app


app = create_app()
