"""Central, documented configuration. Every threshold shown in the UI comes from here."""
from dataclasses import dataclass

# Sentinel-2 L2A Scene Classification (SCL) values treated as INVALID.
# 0 no data, 1 saturated/defective, 3 cloud shadow, 8 cloud medium, 9 cloud high,
# 10 thin cirrus, 11 snow/ice.
SCL_INVALID = (0, 1, 3, 8, 9, 10, 11)

# NDVI-difference thresholds (absolute NDVI units) for the five change classes.
DEFAULT_CHANGE_THRESHOLDS = {
    "significant_decrease": -0.20,
    "moderate_decrease": -0.05,
    "moderate_increase": 0.05,
    "significant_increase": 0.20,
}

# Confidence-score weights. Renormalised over the factors that apply to an analysis.
CONFIDENCE_WEIGHTS = {
    "valid_pixels": 0.35,
    "cloud_cover": 0.20,
    "temporal_separation": 0.10,
    "data_availability": 0.10,
    "model_confidence": 0.15,
    "statistical_support": 0.10,
}


@dataclass(frozen=True)
class Settings:
    min_valid_fraction: float = 0.30      # refuse analysis below this
    max_scene_cloud_cover: float = 40.0   # % at scene level, for scene search
    min_dates_for_trend: int = 8
    hotspot_min_pixels: int = 25
    savi_l: float = 0.5
    cache_dir: str = ".cache/satquery"
    fusion_max_temporal_separation_days: float = 3.0
    # Local BLIP checkpoint fine-tuned on RSICD for Sentinel-2 RGB captioning.
    caption_model_dir: str = "models/rsicd_blip_caption"
    caption_max_new_tokens: int = 40
    caption_num_beams: int = 3


settings = Settings()
