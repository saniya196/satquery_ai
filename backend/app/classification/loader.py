"""Finds and caches the trained model. Set SATQUERY_MODEL_DIR to override the default <project>/models."""
import os
from functools import lru_cache
from pathlib import Path

from app.classification.classifier import LandCoverClassifier
from app.core.errors import SatQueryError


class ModelUnavailableError(SatQueryError):
    code = "model_unavailable"


def default_model_dir() -> Path:
    env = os.getenv("SATQUERY_MODEL_DIR", "").strip()
    return Path(env) if env else Path(__file__).resolve().parents[3] / "models"


@lru_cache(maxsize=1)
def get_classifier() -> LandCoverClassifier:
    d = default_model_dir()
    if not (d / "landcover_resnet18.npz").exists() or not (d / "landcover_meta.json").exists():
        raise ModelUnavailableError(
            f"Land-cover model files not found in '{d}'. Expected landcover_resnet18.npz and landcover_meta.json "
            f"(from the training notebook export).")
    return LandCoverClassifier.from_dir(d)
