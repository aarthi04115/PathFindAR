"""
App-level singleton state.

Holds shared, long-lived service instances (navigator, localization pipeline,
ingestion engine) so endpoints can access them without re-instantiating
on every request.

Usage in endpoints:
    from app.core import state
    route = state.navigator.find_route(...)
    state.ingestion_engine.ingest_base64(...)
"""

from typing import Optional

from app.navigation.pathfinder import IndoorNavigator
from app.localization.pipeline import LocalizationPipeline
from app.localization.ingestion import IngestionEngine

# These are initialized in main.py lifespan startup
navigator: IndoorNavigator = IndoorNavigator()
localization: LocalizationPipeline = LocalizationPipeline()
ingestion_engine: Optional[IngestionEngine] = None
