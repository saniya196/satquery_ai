import json
import os
import tempfile

import numpy as np

from app.storage import artifacts, jobs


def test_artifacts_save_load_roundtrip():
    job_id = "art1"
    arrays = {"index": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)}
    raster = {"transform": (10.0, 0.0, 0.0, 0.0, -10.0, 0.0), "crs": "EPSG:32644"}
    ref = artifacts.save_artifacts(job_id, arrays, raster)
    assert ref is not None
    loaded = artifacts.load_artifacts(job_id)
    assert loaded is not None
    assert "index" in loaded
    assert loaded["index"].shape == (2, 2)
    assert loaded["crs"] == "EPSG:32644"



def test_artifacts_missing():
    loaded = artifacts.load_artifacts("doesnotexist123")
    assert loaded is None


def test_artifacts_corrupted():
    job_id = "artbad"
    d = artifacts.artifacts_dir() / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text("not json")
    loaded = artifacts.load_artifacts(job_id)
    assert loaded is None
