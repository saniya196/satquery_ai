import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app


def test_land_cover_evaluation_serves_the_checked_in_report_with_scope():
    project_root = Path(__file__).resolve().parents[2]
    source = json.loads((project_root / "models" / "metrics.json").read_text(encoding="utf-8"))

    response = TestClient(app).get("/evaluation/land-cover")

    assert response.status_code == 200
    report = response.json()
    assert report["dataset"] == "EuroSAT"
    assert report["test_samples"] == sum(item["support"] for item in source["test_10class"]["per_class"].values())
    assert report["reported_artifact_only"] is True
    assert report["reproduced_by_this_endpoint"] is False
    assert report["results"]["accuracy_10_class"] == source["test_10class"]["accuracy"]
    assert report["results"]["macro_f1_10_class"] == source["test_10class"]["macro_f1"]
    assert report["results"]["accuracy_4_class"] == source["test_product_4class"]["accuracy"]
    assert report["results"]["macro_f1_4_class"] == source["test_product_4class"]["macro_f1"]
    assert report["results"]["expected_calibration_error"] == source["ece"]
    assert report["results"]["accuracy_gaussian_noise_sd_0_01"] == source["robustness"]["gaussian noise sd=0.01"]["accuracy"]
    assert any("Indian landscapes is unmeasured" in note for note in report["limitations"])
