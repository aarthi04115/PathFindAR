"""
API v1 Router — mounts all versioned endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.localize import router as localize_router
from app.api.v1.endpoints.route import router as route_router
from app.api.v1.endpoints.map import router as map_router
from app.api.v1.endpoints.ws_localize import router as ws_localize_router
from app.api.v1.endpoints.ingestion import router as ingestion_router

api_router = APIRouter()

api_router.include_router(localize_router, prefix="/localize", tags=["localization"])
api_router.include_router(route_router, prefix="/route", tags=["navigation"])
api_router.include_router(map_router, prefix="/map", tags=["map"])
api_router.include_router(ws_localize_router, prefix="/ws/localize", tags=["websocket"])
api_router.include_router(ingestion_router, prefix="/ingest", tags=["ingestion"])
