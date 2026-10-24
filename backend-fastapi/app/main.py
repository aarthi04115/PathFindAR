"""
PathFindAR Backend — Main Application Entry Point

Indoor AR navigation backend providing:
  - Visual localization (SuperPoint + SuperGlue + PnP)
  - A* pathfinding on indoor map graphs
  - Waypoint generation for Unity AR client
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.logging import setup_logging
from app.core import state
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("PathFindAR Backend Starting")
    logger.info(f"Environment : {settings.ENV}")
    logger.info(f"Model Path  : {settings.MODEL_PATH}")
    logger.info(f"Data Path   : {settings.DATA_PATH}")
    logger.info(f"Log Level   : {settings.LOG_LEVEL}")
    logger.info("=" * 60)

    # ── Load navigation map ──────────────────────────────────────
    map_path = Path(settings.DATA_PATH) / settings.MAP_FILE
    try:
        state.navigator.load_map(str(map_path))
        logger.info(f"Navigation map loaded: {map_path}")
    except FileNotFoundError:
        logger.warning(
            f"Map file not found at {map_path} — navigation endpoints will return 503"
        )
    except Exception as exc:
        logger.error(f"Failed to load navigation map: {exc}")

    # ── Load localization models (stubs for now) ─────────────────
    try:
        state.localization.load_models()
    except Exception as exc:
        logger.warning(f"Localization models not loaded: {exc}")

    # ── Initialize reference frame ingestion ──────────────────────
    try:
        from app.localization.storage import ReferenceFrameStore
        from app.localization.ingestion import IngestionEngine

        db_path = Path(settings.DATA_PATH) / "reference_frames.db"
        store = ReferenceFrameStore(db_path)
        state.ingestion_engine = IngestionEngine(
            store=store,
            image_dir=Path(settings.DATA_PATH) / "reference_images",
            feature_dir=Path(settings.DATA_PATH) / "reference_features",
        )
        logger.info(f"Ingestion engine ready — {store.count()} existing frames")
    except Exception as exc:
        logger.warning(f"Ingestion engine not initialized: {exc}")

    yield

    # ── Cleanup ──────────────────────────────────────────────────
    if state.ingestion_engine:
        state.ingestion_engine.store.close()
    logger.info("PathFindAR Backend Shutting Down")


app = FastAPI(
    title="PathFindAR Backend",
    description="Indoor AR Navigation — Localization & Pathfinding Server",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow Unity client + dev tools to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router, prefix="/v1")


@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint — also reports map + model status."""
    from app.api.v1.endpoints.ws_localize import session_manager
    return {
        "status": "ok",
        "service": "pathfindar-backend",
        "version": "0.1.0",
        "nav_map_loaded": state.navigator.is_loaded,
        "localization_loaded": state.localization.is_loaded,
        "active_sessions": session_manager.active_count,
    }


@app.get("/sessions", tags=["system"])
async def list_sessions():
    """List all active WebSocket sessions and their stats."""
    from app.api.v1.endpoints.ws_localize import session_manager
    return {
        "active_sessions": session_manager.active_count,
        "sessions": session_manager.all_summaries,
    }
