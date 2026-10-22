"""Land-cover analysis: scene -> deterministic masks -> ML tiles -> evidence + confidence + grounded answer."""
from typing import Callable, Optional

import numpy as np

from app.classification.classifier import LandCoverClassifier
from app.classification.labels import BANDS, LOGICAL_BANDS
from app.core.config import settings
from app.core.errors import InsufficientValidPixelsError
from app.evidence.confidence import compute_confidence
from app.preprocessing.masking import build_valid_mask, pixel_area_m2
from app.satellite.provider import SatelliteProvider, UploadedRasterError
from app.schemas.evidence import Evidence, SceneRef
from app.schemas.query import DateRange
from app.validation.grounding import grounded_answer

BAND_IDS = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir1": "B11"}


def run_uploaded_land_cover(cube, raster, filename: str, classifier: LandCoverClassifier,
                            radiometry: str) -> dict:
    """Classify an explicitly mapped uploaded reflectance cube without scene assumptions."""
    if radiometry != "reflectance":
        raise UploadedRasterError("unsupported_radiometry", "Uploaded land-cover classification requires radiometry='reflectance'.")
    cube = np.asarray(cube, dtype=np.float32)
    if cube.ndim != 3 or cube.shape[0] != len(BANDS) or cube.shape[1] <= 0 or cube.shape[2] <= 0:
        raise UploadedRasterError("invalid_cube", "Uploaded land-cover classification requires a non-empty cube in (5, height, width) order.")
    if tuple(getattr(classifier, "bands_logical", ())) != LOGICAL_BANDS:
        raise UploadedRasterError("invalid_classifier_bands", "The classifier does not use the required B02, B03, B04, B08, B11 logical order.")
    mapping = getattr(raster, "band_mapping", None)
    if not isinstance(mapping, dict) or set(mapping) != set(BANDS):
        raise UploadedRasterError("invalid_band_mapping", "Uploaded raster band_mapping must contain exactly B02, B03, B04, B08, and B11.")
    if any(isinstance(index, bool) or not isinstance(index, (int, np.integer)) or int(index) < 1
           for index in mapping.values()) \
            or len({int(index) for index in mapping.values()}) != len(BANDS):
        raise UploadedRasterError("invalid_band_mapping", "Uploaded raster band_mapping must contain positive unique indexes.")
    band_count = getattr(raster, "band_count", None)
    if not isinstance(band_count, (int, np.integer)) or band_count < len(BANDS):
        raise UploadedRasterError("invalid_band_mapping", "Uploaded raster does not contain enough bands for the required mapping.")
    if any(int(index) > int(band_count) for index in mapping.values()):
        raise UploadedRasterError("invalid_band_mapping", "A mapped band is not present in the uploaded raster.")
    valid = np.isfinite(cube).all(axis=0)
    valid_fraction = float(valid.mean()) if valid.size else 0.0
    if valid_fraction < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {valid_fraction:.1%} of uploaded pixels are valid; "
            f"minimum is {settings.min_valid_fraction:.0%}.")
    pixel_area = pixel_area_m2(raster.transform) if raster.linear_units in {"metre", "metres", "meter", "meters"} else 0.0
    res = classifier.classify_cube(cube, valid, pixel_area)
    dist = res["distribution"]
    classified_fraction = float(dist["classified_fraction"])
    if classified_fraction < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {classified_fraction:.1%} of uploaded pixels could be classified; "
            f"minimum is {settings.min_valid_fraction:.0%}.")
    if pixel_area == 0.0:
        for values in dist["classes"].values():
            values["area_km2"] = None

    info = classifier.model_info()
    metrics = {
        "input_valid_pixel_fraction": valid_fraction,
        "classified_pixel_count": dist["classified_pixels"],
        "classified_fraction": classified_fraction,
        "unclassified_pixel_count": dist["unclassified_pixels"],
        "distribution": dist,
        "distribution_10class": res["distribution_10class"],
        "dominant_class": res["dominant_class"],
        "n_tiles_classified": res["n_tiles_classified"],
        "n_tiles_skipped": res["n_tiles_skipped"],
        "edge_pixels_unused": res["edge_pixels_unused"],
        "mean_model_confidence": res["mean_confidence"],
        "low_confidence_tile_fraction": res["low_confidence_tile_fraction"],
    }
    evidence = {
        "operation": "uploaded_land_cover",
        "source": {
            "filename": filename,
            "format": "GeoTIFF",
            "width": raster.width,
            "height": raster.height,
            "band_count": raster.band_count,
            "crs": raster.crs,
            "transform": list(tuple(raster.transform)[:6]),
            "resolution": {"x": raster.resolution_x, "y": raster.resolution_y, "units": raster.linear_units},
            "nodata": raster.nodata,
            "bounds": list(raster.bounds),
        },
        "band_mapping": dict(raster.band_mapping),
        "radiometry": "user-declared reflectance; not independently verified",
        "preprocessing": [
            "Read the explicitly mapped bands in B02, B03, B04, B08, B11 order",
            "Used the uploaded raster's native grid without reprojection, resampling, or cropping",
            "Excluded nodata and non-finite pixels",
            f"Non-overlapping {classifier.tile}x{classifier.tile}-pixel tiles",
            "Tiles with <80% valid pixels skipped",
            "Per-band normalisation from training statistics",
        ],
        "thresholds": {
            "min_tile_valid_fraction": 0.8,
            "low_confidence_below": 0.7,
        },
        "valid_pixel_fraction": valid_fraction,
        "metrics": metrics,
        "model": info,
        "limitations": [
            "The model was trained on European EuroSAT Sentinel-2 L1C imagery.",
            "Accuracy on Indian landscapes and uploaded imagery is unmeasured.",
            "This is tile-level land-cover classification, not VQA, captioning, grounding, or semantic certainty.",
            "Model confidence is separate from valid-pixel coverage; no combined data-quality score is computed.",
        ],
    }
    return {
        "operation": "uploaded_land_cover",
        "source": evidence["source"],
        "band_mapping": evidence["band_mapping"],
        "radiometry": evidence["radiometry"],
        "metrics": metrics,
        "model": info,
        "confidence": {
            "mean_model_confidence": res["mean_confidence"],
            "valid_pixel_fraction": valid_fraction,
            "combined_score": None,
            "note": "No combined score is reported for uploaded imagery because cloud and temporal inputs are unavailable.",
        },
        "evidence": evidence,
    }


def run_land_cover(provider: SatelliteProvider, aoi: dict, rng: DateRange, classifier: LandCoverClassifier,
                   max_cloud: float = settings.max_scene_cloud_cover, llm_fn: Optional[Callable] = None) -> dict:
    scene_meta = provider.best_scene(aoi, rng.start, rng.end, max_cloud)
    sc = provider.get_scene(aoi, scene_meta["item_id"], list(classifier.bands_logical))
    bands = [sc.bands[b] for b in classifier.bands_logical]
    cube = np.stack(bands).astype(np.float32)
    valid = build_valid_mask(sc.scl, sc.inside_aoi, bands)
    n_aoi = int(sc.inside_aoi.sum())
    px = pixel_area_m2(sc.transform)

    res = classifier.classify_cube(cube, valid, px)
    dist = res["distribution"]
    coverage = dist["classified_pixels"] / n_aoi if n_aoi else 0.0
    if coverage < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {coverage:.1%} of the area could be classified (cloud-free, complete tiles); "
            f"minimum is {settings.min_valid_fraction:.0%}.")

    conf = compute_confidence(valid_fraction=coverage, cloud_cover_pct=sc.cloud_cover,
                              model_confidence=res["mean_confidence"])
    info = classifier.model_info()
    dom = res["dominant_class"]
    classes = {k: {"fraction": v["fraction"], "area_km2": v["area_km2"]} for k, v in dist["classes"].items()}
    metrics = {"distribution": dist, "distribution_10class": res["distribution_10class"],
               "dominant_class": dom, "classified_fraction_of_aoi": coverage,
               "n_tiles_classified": res["n_tiles_classified"], "n_tiles_skipped": res["n_tiles_skipped"],
               "edge_pixels_unused": res["edge_pixels_unused"], "mean_model_confidence": res["mean_confidence"],
               "low_confidence_tile_fraction": res["low_confidence_tile_fraction"]}
    ev = Evidence(
        operation="land_cover",
        scenes=[SceneRef(item_id=sc.item_id, datetime=sc.datetime, cloud_cover=sc.cloud_cover,
                         resolution_m=sc.resolution_m, crs=sc.crs)],
        aoi_area_km2=n_aoi * px / 1e6,
        bands=" / ".join(BAND_IDS.get(b, b) for b in classifier.bands_logical),
        preprocessing=sc.preprocessing + [
            f"AOI cut into non-overlapping {classifier.tile}x{classifier.tile}-pixel tiles",
            "Tiles with <80% valid pixels skipped (never invented)", "Per-band normalisation from training statistics"],
        thresholds={"min_tile_valid_fraction": 0.8, "low_confidence_below": 0.7},
        valid_pixel_fraction=coverage, metrics=metrics, model=info)
    facts = {"operation": "land_cover", "date": sc.datetime[:10], "dominant_class": dom,
             "dominant_fraction": dist["classes"][dom]["fraction"], "classes": classes,
             "classified_fraction": coverage, "mean_model_confidence": res["mean_confidence"],
             "model_test_accuracy": info["test_accuracy_10class"], "data_quality_score": conf["score"]}
    return {"evidence": ev.model_dump(), "confidence": conf, "facts": facts,
            "answer": grounded_answer(facts, llm_fn),
            "distribution": dist, "model": info,
            "arrays": {"class_map": res["class_map"], "confidence_map": res["confidence_map"],
                   "class_map_10": res["class_map_10"]},
            "raster": {"transform": sc.transform, "crs": sc.crs}}
