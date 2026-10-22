import numpy as np
import pytest

from app.classification.labels import (EUROSAT_CLASSES, PRODUCT_CLASSES, PRODUCT_MAP, confusion_matrix,
                                       expected_calibration_error, metrics_from_cm, normalise, product_index)
from app.classification.tiling import class_distribution, stitch, tile_array


def test_every_eurosat_class_maps_to_a_product_class_and_no_bare_soil():
    assert len(EUROSAT_CLASSES) == 10 and set(PRODUCT_MAP) == set(EUROSAT_CLASSES)
    assert set(PRODUCT_MAP.values()) <= set(PRODUCT_CLASSES)
    assert "bare_soil" not in PRODUCT_CLASSES   # EuroSAT cannot supply it


def test_product_index_mapping():
    idx = product_index(np.arange(10))
    names = [PRODUCT_CLASSES[i] for i in idx]
    assert names[EUROSAT_CLASSES.index("Forest")] == "vegetation"
    assert names[EUROSAT_CLASSES.index("SeaLake")] == "water"
    assert names[EUROSAT_CLASSES.index("Residential")] == "built_up"
    assert names[EUROSAT_CLASSES.index("Pasture")] == "agricultural_land"


def test_metrics_hand_checked():
    y_true = [0, 0, 0, 1, 1, 2]
    y_pred = [0, 0, 1, 1, 1, 0]
    cm = confusion_matrix(y_true, y_pred, 3)
    assert cm.tolist() == [[2, 1, 0], [0, 2, 0], [1, 0, 0]]
    m = metrics_from_cm(cm, ["a", "b", "c"])
    assert m["accuracy"] == pytest.approx(4 / 6)
    assert m["per_class"]["a"]["precision"] == pytest.approx(2 / 3) and m["per_class"]["a"]["recall"] == pytest.approx(2 / 3)
    assert m["per_class"]["b"]["precision"] == pytest.approx(2 / 3) and m["per_class"]["b"]["recall"] == 1.0
    assert m["per_class"]["c"]["f1"] == 0.0 and m["per_class"]["c"]["support"] == 1


def test_ece_perfectly_calibrated_vs_overconfident():
    rng = np.random.default_rng(0)
    conf = rng.uniform(0.5, 1.0, 20000)
    calibrated = rng.uniform(size=conf.size) < conf
    over = rng.uniform(size=conf.size) < (conf - 0.3)
    assert expected_calibration_error(conf, calibrated)[0] < 0.02
    assert expected_calibration_error(conf, over)[0] > 0.25
    assert expected_calibration_error([1.0, 1.0], [True, False])[0] == pytest.approx(0.5)


def test_normalise_per_band():
    cube = np.ones((2, 2, 2), dtype=np.float32) * np.array([1.0, 3.0]).reshape(2, 1, 1)
    out = normalise(cube, [1.0, 1.0], [2.0, 2.0])
    assert out[0].max() == 0.0 and out[1].min() == 1.0


def test_tiling_counts_and_edge_handling():
    cube = np.random.rand(5, 150, 140).astype(np.float32)
    t = tile_array(cube, np.ones((150, 140), bool), tile=64)
    assert t["tiles"].shape == (4, 5, 64, 64) and t["n_skipped"] == 0       # 2x2 full tiles
    assert t["edge_pixels_unused"] == 150 * 140 - 4 * 64 * 64


def test_tiles_with_too_few_valid_pixels_are_skipped_not_invented():
    cube = np.random.rand(3, 128, 64).astype(np.float32)
    valid = np.ones((128, 64), bool)
    valid[:64, :] = False
    valid[:64, :10] = True        # only ~16% valid in first tile
    t = tile_array(cube, valid, tile=64, min_valid_fraction=0.8)
    assert len(t["origins"]) == 1 and t["n_skipped"] == 1 and t["origins"][0] == (64, 0)


def test_invalid_pixels_in_kept_tile_are_filled_with_tile_mean():
    cube = np.full((1, 64, 64), 0.5, dtype=np.float32)
    cube[0, 0, 0] = np.nan
    t = tile_array(cube, np.ones((64, 64), bool), tile=64)
    assert np.isfinite(t["tiles"]).all() and t["tiles"][0, 0, 0, 0] == pytest.approx(0.5)


def test_stitch_and_distribution():
    origins = [(0, 0), (0, 64)]
    cm, conf = stitch([1, 3], [0.9, 0.6], origins, (64, 128), tile=64)
    assert (cm[:, :64] == 1).all() and (cm[:, 64:] == 3).all() and conf[0, 0] == pytest.approx(0.9)
    valid = np.ones((64, 128), bool)
    valid[:, :32] = False
    cm2, _ = stitch([1, 3], [0.9, 0.6], origins, (64, 128), valid=valid, tile=64)
    assert (cm2[:, :32] == -1).all()
    d = class_distribution(cm, PRODUCT_CLASSES, 100.0)
    assert d["classes"]["agricultural_land"]["fraction"] == pytest.approx(0.5)
    assert d["classes"]["water"]["fraction"] == pytest.approx(0.5)
    assert d["classes"]["water"]["area_km2"] == pytest.approx(64 * 64 * 100 / 1e6)
    assert d["classified_fraction"] == 1.0
    d2 = class_distribution(cm2, PRODUCT_CLASSES, 100.0)
    assert d2["unclassified_pixels"] == 64 * 32 and d2["classified_fraction"] == pytest.approx(0.75)
