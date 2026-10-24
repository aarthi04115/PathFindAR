"""
Application configuration loaded from environment / .env file.
Uses pydantic-settings for type-safe config management.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root = pathfindar_backend/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """PathFindAR backend configuration."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # General
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Paths
    MODEL_PATH: str = str(PROJECT_ROOT / "models")
    DATA_PATH: str = str(PROJECT_ROOT / "data")
    LOG_PATH: str = str(PROJECT_ROOT / "logs")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Localization
    SUPERPOINT_MODEL: str = "superpoint_v1.pth"
    SUPERGLUE_MODEL: str = "superglue_indoor.pth"
    FAISS_INDEX: str = "faiss_index.bin"
    MAX_KEYPOINTS: int = 1024
    MATCH_THRESHOLD: float = 0.7
    POSE_CONFIDENCE_THRESHOLD: float = 0.5

    # Frame processing
    FRAME_MAX_SIZE: int = 640
    FRAME_QUALITY: int = 85
    BLUR_THRESHOLD: float = 100.0

    # Navigation
    MAP_FILE: str = "building_map.json"
    DEFAULT_FLOOR: int = 0


settings = Settings()
