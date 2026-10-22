import json
from datetime import date, datetime

import numpy as np
import pytest
from affine import Affine

from app.classification.classifier import LandCoverClassifier
from app.classification.loader import ModelUnavailableError, get_classifier
from app.classification.numpy_resnet import fold_state_dict, save_params
from app.core.errors import InsufficientValidPixelsError
from app.satellite.provider import SatelliteProvider, SceneData
from app.schemas.query import DateRange
from app.services.land_cover import run_land_cover
from app.validation.grounding import check_grounding
from tests.test_numpy_resnet import random_state

TF = Affine(10, 0, 500000, 0, -10, 4000000)
AOI = {"type": "Polygon", "coordinates": [[[78.0, 17.0], [78.01, 17.0], [78.01, 17.01], [78.0, 17.01], [78.0, 17.0]]]}
RNG = DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30))
META = {"bands_logical": ["blue", "green", "red", "nir", "swir1"], "bands_sentinel2": ["B02", "B03", "B04", "B08", "B11"],
        "mean": [0.1] * 5, "std": [0.1] * 5, "tile_size": 64, "architecture": "resnet18 (test)",
        "data": {"source": "EuroSAT (test fixture)", "processing_level": "L1C"}}
METRICS = {"test_10class": {"accuracy": 0.9874, "macro_f1": 0.9871}, "test_product_4class": {"accuracy": 0.9928}, "ece": 0.0032}


class FakeNet:
    """Forest (idx 1) where the normalised blue channel is > 0, else SeaLake (idx 9)."""
    def __init__(self, conf=0.95):
        self.conf, self.last_x = conf, None

    def predict(self, x, batch=16):
        self.last_x = x
        return np.where(x[:, 0].mean(axis=(1, 2)) > 0, 1, 9), np.full(len(x), self.conf)


class LCProvider(SatelliteProvider):
    def __init__(self, shape=(128, 128), cloudy_rows=0, cloud=5.0):
        self.shape, self.cloudy_rows, self.cloud = shape, cloudy_rows, cloud

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        return [{"item_id": "S1", "datetime": "2026-06-15T05:00:00+00:00", "cloud_cover": self.cloud}]

    def get_scene(self, aoi_geojson, item_id, bands):
        h, w = self.shape
        blue = np.full(self.shape, 0.02); blue[:, : w // 2] = 0.20     # left half bright, right half dark
        arr = {b: (blue if b == "blue" else np.full(self.shape, 0.15)) for b in bands}
        scl = np.full(self.shape, 4, dtype=np.uint8); scl[: self.cloudy_rows] = 9
        return SceneData("S1", "2026-06-15T05:00:00+00:00", self.cloud, arr, scl, TF, "EPSG:32644",
                         np.ones(self.shape, bool), 10.0, ["synthetic test scene"])


def clf(net=None):
    return LandCoverClassifier(net or FakeNet(), META, METRICS)


def test_known_distribution_and_areas():
    r = run_land_cover(LCProvider(), AOI, RNG, clf())
    d = r["distribution"]["classes"]
    assert d["vegetation"]["fraction"] == pytest.approx(0.5) and d["water"]["fraction"] == pytest.approx(0.5)
    assert d["water"]["area_km2"] == pytest.approx(128 * 128 * 100 / 1e6 / 2)
    assert r["evidence"]["metrics"]["n_tiles_classified"] == 4 and r["evidence"]["valid_pixel_fraction"] == pytest.approx(1.0)
    assert r["facts"]["dominant_class"] in ("vegetation", "water")
    assert r["arrays"]["class_map"].shape == (128, 128) and (r["arrays"]["class_map"] >= 0).all()


def test_inputs_are_normalised_with_training_statistics():
    net = FakeNet()
    run_land_cover(LCProvider(), AOI, RNG, clf(net))
    assert net.last_x.shape[1:] == (5, 64, 64)
    left = net.last_x[:, 0][net.last_x[:, 0].mean(axis=(1, 2)) > 0]
    assert left.mean() == pytest.approx((0.20 - 0.1) / 0.1, abs=1e-5)       # (value - mean) / std


def test_evidence_names_the_model_its_accuracy_and_limits():
    ev = run_land_cover(LCProvider(), AOI, RNG, clf())["evidence"]
    assert ev["bands"] == "B02 / B03 / B04 / B08 / B11" and ev["model"]["test_accuracy_10class"] == 0.9874
    assert ev["model"]["training_processing_level"] == "L1C" and len(ev["model"]["limitations"]) >= 4
    assert any("tile" in p.lower() for p in ev["preprocessing"])


def test_answer_is_grounded_and_says_confidence_is_not_certainty():
    r = run_land_cover(LCProvider(), AOI, RNG, clf())
    assert r["answer"]["source"] == "template" and "not certainty" in r["answer"]["text"]
    assert check_grounding(r["answer"]["text"], r["facts"])["valid"]


def test_hallucinated_llm_answer_is_rejected():
    r = run_land_cover(LCProvider(), AOI, RNG, clf(), llm_fn=lambda facts, errs: "Forest covers 91% of the area.")
    assert r["answer"]["source"] == "template"


def test_cloudy_half_is_skipped_not_invented():
    r = run_land_cover(LCProvider(cloudy_rows=64, cloud=30.0), AOI, RNG, clf())
    assert r["evidence"]["metrics"]["n_tiles_skipped"] == 2
    assert r["evidence"]["valid_pixel_fraction"] == pytest.approx(0.5)
    assert (r["arrays"]["class_map"][:64] == -1).all()


def test_fully_cloudy_scene_is_refused():
    with pytest.raises(InsufficientValidPixelsError):
        run_land_cover(LCProvider(cloudy_rows=128, cloud=35.0), AOI, RNG, clf())


def test_small_area_edge_pixels_are_reported():
    r = run_land_cover(LCProvider(shape=(100, 100)), AOI, RNG, clf())
    assert r["evidence"]["metrics"]["n_tiles_classified"] == 1
    assert r["evidence"]["metrics"]["edge_pixels_unused"] == 100 * 100 - 64 * 64
    assert r["evidence"]["valid_pixel_fraction"] == pytest.approx(64 * 64 / 10000)


def test_area_smaller_than_one_tile_is_refused():
    with pytest.raises(InsufficientValidPixelsError):
        run_land_cover(LCProvider(shape=(40, 40)), AOI, RNG, clf())


def test_low_confidence_fraction_is_reported():
    r = run_land_cover(LCProvider(), AOI, RNG, clf(FakeNet(conf=0.5)))
    assert r["evidence"]["metrics"]["low_confidence_tile_fraction"] == 1.0
    assert r["facts"]["mean_model_confidence"] == pytest.approx(0.5)


def write_model(d, seed=0):
    save_params(d / "landcover_resnet18.npz", fold_state_dict(random_state(np.random.default_rng(seed))))
    (d / "landcover_meta.json").write_text(json.dumps(META))
    (d / "metrics.json").write_text(json.dumps(METRICS))


def test_real_numpy_network_from_disk_is_deterministic(tmp_path):
    write_model(tmp_path)
    c = LandCoverClassifier.from_dir(tmp_path)
    r1 = run_land_cover(LCProvider(), AOI, RNG, c)
    r2 = run_land_cover(LCProvider(), AOI, RNG, c)
    fr = [v["fraction"] for v in r1["distribution"]["classes"].values()]
    assert sum(fr) == pytest.approx(1.0) and np.array_equal(r1["arrays"]["class_map"], r2["arrays"]["class_map"])
    assert r1["model"]["test_accuracy_product"] == 0.9928


def test_loader_reports_missing_model_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_MODEL_DIR", str(tmp_path))
    get_classifier.cache_clear()
    with pytest.raises(ModelUnavailableError) as e:
        get_classifier()
    assert "landcover_resnet18.npz" in e.value.message
    write_model(tmp_path)
    assert get_classifier().tile == 64
    get_classifier.cache_clear()
