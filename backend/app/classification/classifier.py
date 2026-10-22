"""Land-cover classifier: AOI cube -> tiles -> numpy ResNet18 -> class map + distribution + model info."""
import json
from pathlib import Path
from typing import Optional

import numpy as np

from app.classification.labels import EUROSAT_CLASSES, PRODUCT_CLASSES, product_index
from app.classification.numpy_resnet import NumpyResNet18, load_params
from app.classification.tiling import class_distribution, stitch, tile_array
from app.core.errors import InsufficientValidPixelsError

LOW_CONFIDENCE = 0.7

LIMITATIONS = [
    "Trained on European EuroSAT imagery (top-of-atmosphere L1C); not validated on Indian surface-reflectance (L2A) imagery.",
    "Each 640 m tile gets one label, so class boundaries are blocky and mixed tiles are forced into one class.",
    "No bare-soil class exists in the training data.",
    "Confidence is the model's softmax score, not scientific certainty.",
]


class LandCoverClassifier:
    def __init__(self, net, meta: dict, metrics: Optional[dict] = None):
        self.net, self.meta, self.metrics = net, meta, metrics or {}
        self.bands_logical = tuple(meta["bands_logical"])
        self.tile = int(meta.get("tile_size", 64))
        self.mean = np.asarray(meta["mean"], dtype=np.float32).reshape(1, -1, 1, 1)
        self.std = np.asarray(meta["std"], dtype=np.float32).reshape(1, -1, 1, 1)

    @classmethod
    def from_dir(cls, model_dir):
        d = Path(model_dir)
        net = NumpyResNet18(load_params(d / "landcover_resnet18.npz"))
        meta = json.loads((d / "landcover_meta.json").read_text())
        mp = d / "metrics.json"
        return cls(net, meta, json.loads(mp.read_text()) if mp.exists() else None)

    def model_info(self) -> dict:
        m = self.metrics
        return {
            "architecture": self.meta.get("architecture", "resnet18"),
            "inference": "numpy (BatchNorm folded), verified against torch",
            "bands": self.meta.get("bands_sentinel2"),
            "trained_on": self.meta.get("data", {}).get("source", "EuroSAT"),
            "training_processing_level": self.meta.get("data", {}).get("processing_level", "L1C"),
            "test_accuracy_10class": m.get("test_10class", {}).get("accuracy"),
            "test_accuracy_product": m.get("test_product_4class", {}).get("accuracy"),
            "test_macro_f1_10class": m.get("test_10class", {}).get("macro_f1"),
            "expected_calibration_error": m.get("ece"),
            "limitations": LIMITATIONS,
        }

    def classify_cube(self, cube, valid, pixel_area_m2: float, min_tile_valid: float = 0.8) -> dict:
        """cube: (C,H,W) reflectance in self.bands_logical order. valid: (H,W) bool."""
        cube = np.asarray(cube, dtype=np.float32)
        valid = np.asarray(valid, dtype=bool) & np.isfinite(cube).all(axis=0)
        t = tile_array(cube, valid, tile=self.tile, min_valid_fraction=min_tile_valid)
        if not t["origins"]:
            raise InsufficientValidPixelsError(
                f"No complete {self.tile}x{self.tile}-pixel tile has at least {min_tile_valid:.0%} valid pixels "
                f"(area too small, too cloudy, or too narrow).")
        x = (t["tiles"] - self.mean) / self.std
        pred10, conf = self.net.predict(x)
        pred4 = product_index(pred10)
        shape = cube.shape[1:]
        map4, conf_map = stitch(pred4, conf, t["origins"], shape, valid=valid, tile=self.tile)
        map10, _ = stitch(pred10, conf, t["origins"], shape, valid=valid, tile=self.tile)
        dist4 = class_distribution(map4, PRODUCT_CLASSES, pixel_area_m2)
        dist10 = class_distribution(map10, EUROSAT_CLASSES, pixel_area_m2)
        dominant = max(dist4["classes"], key=lambda k: dist4["classes"][k]["pixels"])
        return {
            "class_map": map4, "class_map_10": map10, "confidence_map": conf_map,
            "distribution": dist4, "distribution_10class": dist10, "dominant_class": dominant,
            "n_tiles_classified": len(t["origins"]), "n_tiles_skipped": t["n_skipped"],
            "n_tiles_total": t["n_tiles_total"], "edge_pixels_unused": t["edge_pixels_unused"],
            "mean_confidence": float(conf.mean()),
            "low_confidence_tile_fraction": float((conf < LOW_CONFIDENCE).mean()),
        }
