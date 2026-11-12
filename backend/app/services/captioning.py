"""Genuine Sentinel-2 image captioning with a local RSICD BLIP checkpoint.

The caption is model output, not a deterministic measurement and not a
verified ground-truth description.  This module renders a reproducible RGB
image from the actual Sentinel-2 surface-reflectance bands, masks invalid
pixels with SCL/AOI validity, and runs the local checkpoint on CPU.

No network call is made to load or run the model.  The checkpoint must already
exist under ``settings.caption_model_dir`` (or ``SATQUERY_CAPTION_MODEL_DIR``).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.core.config import settings
from app.core.errors import (
    CaptionGenerationError,
    CaptionModelUnavailableError,
    InsufficientValidPixelsError,
    NoImageryError,
)
from app.preprocessing.masking import build_valid_mask, pixel_area_m2
from app.satellite.provider import SceneData

MODEL_REPO = "Gurveer05/blip-image-captioning-base-rscid-finetuned"
MODEL_BASE = "Salesforce/blip-image-captioning-base"
MODEL_REVISION = "57c4f0ff06264d374131637ce7c1e8dea079d589"
MODEL_ARCHITECTURE = "BlipForConditionalGeneration"
MODEL_DATASET = "arampacha/rsicd"
MODEL_LICENSE = "apache-2.0"
MODEL_DISPLAY_NAME = "BLIP image captioning (RSICD fine-tuned)"
MODEL_INPUT_SIZE = 384
STRETCH_PERCENTILES = (2.0, 98.0)


@dataclass
class CaptionModelBundle:
    """Loaded processor/model plus provenance used in evidence."""

    processor: Any
    model: Any
    model_dir: str
    device: str = "cpu"
    parameter_count: Optional[int] = None
    model_size_bytes: Optional[int] = None
    model_dtype: Optional[str] = None


@dataclass
class RenderedScene:
    """Deterministic RGB rendering of one Sentinel-2 AOI."""

    image: Any
    rgb: np.ndarray
    valid_fraction: float
    valid_pixel_count: int
    aoi_pixel_count: int
    width: int
    height: int
    stretch: dict
    crop: dict
    aoi_area_km2: float


_model_bundle: Optional[CaptionModelBundle] = None
_model_lock = threading.Lock()


def model_dir() -> Path:
    """Resolve the local checkpoint directory without any network access."""
    configured = os.getenv("SATQUERY_CAPTION_MODEL_DIR") or settings.caption_model_dir
    path = Path(configured).expanduser()
    if not path.is_absolute():
        # backend/app/services/captioning.py -> repository root
        path = Path(__file__).resolve().parents[3] / path
    return path


def load_caption_model() -> CaptionModelBundle:
    """Load and cache the local BLIP checkpoint.

    Any failure is reported as ``CaptionModelUnavailableError`` with the exact
    local path and exception type.  There is deliberately no generic-model or
    template-caption fallback.
    """
    global _model_bundle
    if _model_bundle is not None:
        return _model_bundle

    with _model_lock:
        if _model_bundle is not None:
            return _model_bundle

        path = model_dir()
        required = (
            "config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.txt",
        )
        missing = [name for name in required if not (path / name).is_file()]
        if missing:
            raise CaptionModelUnavailableError(
                f"The local RSICD caption checkpoint is incomplete at {path}. "
                f"Missing: {', '.join(missing)}. Download the checkpoint before captioning; "
                "no fallback caption was produced."
            )

        try:
            import torch
            from transformers import BlipForConditionalGeneration, BlipProcessor
        except Exception as exc:  # pragma: no cover - environment dependent
            raise CaptionModelUnavailableError(
                "The local caption runtime could not be imported. "
                f"{type(exc).__name__}: {exc}. No fallback caption was produced."
            ) from exc

        try:
            processor = BlipProcessor.from_pretrained(str(path), local_files_only=True)
            model = BlipForConditionalGeneration.from_pretrained(str(path), local_files_only=True)
            model.eval()
        except Exception as exc:
            raise CaptionModelUnavailableError(
                f"The local RSICD BLIP checkpoint at {path} could not be loaded. "
                f"{type(exc).__name__}: {exc}. No fallback caption was produced."
            ) from exc

        try:
            parameter_count = int(sum(parameter.numel() for parameter in model.parameters()))
        except Exception:
            parameter_count = None
        try:
            model_size_bytes = int((path / "model.safetensors").stat().st_size)
        except OSError:
            model_size_bytes = None
        try:
            model_dtype = str(next(model.parameters()).dtype).replace("torch.", "")
        except Exception:
            model_dtype = None

        _model_bundle = CaptionModelBundle(
            processor=processor,
            model=model,
            model_dir=str(path),
            device="cpu",
            parameter_count=parameter_count,
            model_size_bytes=model_size_bytes,
            model_dtype=model_dtype,
        )
        return _model_bundle


def render_scene_rgb(scene: SceneData) -> RenderedScene:
    """Render a deterministic 8-bit RGB image from actual Sentinel-2 bands.

    Invalid/cloud/SLC pixels are excluded from the percentile stretch and
    rendered black.  The image is cropped to the valid-pixel bounding box with
    a small margin so the caption model sees the AOI rather than the whole
    provider window.
    """
    required = ("red", "green", "blue")
    missing = [name for name in required if name not in scene.bands]
    if missing:
        raise NoImageryError(
            "Selected Sentinel-2 scene lacks the RGB bands required for captioning: "
            f"{', '.join(missing)}."
        )

    red = np.asarray(scene.bands["red"], dtype=np.float64)
    green = np.asarray(scene.bands["green"], dtype=np.float64)
    blue = np.asarray(scene.bands["blue"], dtype=np.float64)
    shape = red.shape
    if red.ndim != 2 or green.shape != shape or blue.shape != shape:
        raise NoImageryError("Sentinel-2 RGB bands are not aligned on one 2-D grid.")

    scl = np.asarray(scene.scl)
    inside = np.asarray(scene.inside_aoi, dtype=bool)
    if scl.shape != shape or inside.shape != shape:
        raise NoImageryError("Sentinel-2 SCL/AOI mask is not aligned with the RGB bands.")

    aoi_pixel_count = int(np.count_nonzero(inside))
    if aoi_pixel_count == 0:
        raise NoImageryError("Selected Sentinel-2 scene has no pixels inside the AOI.")

    valid = build_valid_mask(scl, inside, [red, green, blue])
    valid_pixel_count = int(np.count_nonzero(valid))
    if valid_pixel_count == 0:
        raise InsufficientValidPixelsError(
            "No valid cloud-free Sentinel-2 RGB pixels remain inside the selected AOI."
        )

    valid_fraction = valid_pixel_count / aoi_pixel_count
    if valid_fraction < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {valid_fraction:.1%} of AOI pixels have valid cloud-free RGB values; "
            f"the minimum for captioning is {settings.min_valid_fraction:.0%}."
        )

    rows, cols = np.where(valid)
    row_start, row_end = int(rows.min()), int(rows.max()) + 1
    col_start, col_end = int(cols.min()), int(cols.max()) + 1
    margin = max(2, int(round(0.02 * max(row_end - row_start, col_end - col_start))))
    row_start = max(0, row_start - margin)
    row_end = min(shape[0], row_end + margin)
    col_start = max(0, col_start - margin)
    col_end = min(shape[1], col_end + margin)
    crop_valid = valid[row_start:row_end, col_start:col_end]

    channels: list[np.ndarray] = []
    stretch: dict[str, dict[str, Any]] = {}
    for name, array in (("red", red), ("green", green), ("blue", blue)):
        crop = array[row_start:row_end, col_start:col_end]
        values = crop[crop_valid]
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            raise InsufficientValidPixelsError(
                f"No finite {name} reflectance values remain inside the valid AOI crop."
            )

        low, high = (float(value) for value in np.percentile(finite, STRETCH_PERCENTILES))
        mode = "percentile"
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            low, high = float(np.min(finite)), float(np.max(finite))
            mode = "min_max"
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            normalized = np.full(crop.shape, 0.5, dtype=np.float64)
            mode = "constant"
            low, high = float(finite[0]), float(finite[0])
        else:
            normalized = (crop - low) / (high - low)

        normalized = np.clip(normalized, 0.0, 1.0)
        normalized = np.where(crop_valid, normalized, 0.0)
        channels.append(np.rint(normalized * 255.0).astype(np.uint8))
        stretch[name] = {
            "low_reflectance": low,
            "high_reflectance": high,
            "mode": mode,
        }

    rgb = np.dstack(channels)
    from PIL import Image

    image = Image.fromarray(rgb, mode="RGB")
    height, width = rgb.shape[:2]
    aoi_area_km2 = aoi_pixel_count * pixel_area_m2(scene.transform) / 1_000_000.0
    return RenderedScene(
        image=image,
        rgb=rgb,
        valid_fraction=valid_fraction,
        valid_pixel_count=valid_pixel_count,
        aoi_pixel_count=aoi_pixel_count,
        width=width,
        height=height,
        stretch=stretch,
        crop={
            "row_start": row_start,
            "row_end": row_end,
            "col_start": col_start,
            "col_end": col_end,
            "margin_pixels": margin,
        },
        aoi_area_km2=aoi_area_km2,
    )


def generate_caption(image: Any, bundle: Optional[CaptionModelBundle] = None) -> str:
    """Run local BLIP inference and return a non-empty caption.

    An empty/whitespace caption is treated as a generation failure.  No
    template or generic caption is substituted.
    """
    bundle = bundle or load_caption_model()
    try:
        import torch
    except Exception as exc:  # pragma: no cover - environment dependent
        raise CaptionModelUnavailableError(
            f"The caption runtime could not be imported. {type(exc).__name__}: {exc}"
        ) from exc

    try:
        inputs = bundle.processor(images=image, return_tensors="pt")
        with torch.no_grad():
            output = bundle.model.generate(
                **inputs,
                max_new_tokens=settings.caption_max_new_tokens,
                num_beams=settings.caption_num_beams,
            )
        caption = bundle.processor.decode(output[0], skip_special_tokens=True)
    except CaptionModelUnavailableError:
        raise
    except Exception as exc:
        raise CaptionGenerationError(
            f"Local BLIP caption generation failed. {type(exc).__name__}: {exc}. "
            "No fallback caption was produced."
        ) from exc

    caption = " ".join(str(caption).split())
    if not caption:
        raise CaptionGenerationError(
            "The local RSICD caption model returned an empty caption; no result was produced."
        )
    return caption


def caption_scene(
    scene: SceneData,
    *,
    output_image_path: Optional[Path | str] = None,
    bundle: Optional[CaptionModelBundle] = None,
    aoi_area_km2: Optional[float] = None,
) -> dict:
    """Render a Sentinel-2 AOI, run local BLIP, and return auditable output."""
    rendered = render_scene_rgb(scene)
    if output_image_path is not None:
        path = Path(output_image_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered.image.save(path, format="PNG")

    bundle = bundle or load_caption_model()
    caption = generate_caption(rendered.image, bundle)

    model_meta = {
        "name": MODEL_DISPLAY_NAME,
        "architecture": MODEL_ARCHITECTURE,
        "repository": MODEL_REPO,
        "base_model": MODEL_BASE,
        "revision": MODEL_REVISION,
        "dataset": MODEL_DATASET,
        "license": MODEL_LICENSE,
        "parameter_count": bundle.parameter_count,
        "model_size_bytes": bundle.model_size_bytes,
        "dtype": bundle.model_dtype,
        "device": bundle.device,
        "local_path": bundle.model_dir,
        "task": "image-to-text",
    }

    preprocessing = list(scene.preprocessing or [])
    preprocessing.extend([
        "Sentinel-2 L2A surface reflectance with provider scale/offset applied",
        "SCL and AOI validity mask; invalid/cloud pixels excluded from the stretch and rendered black",
        "Valid-pixel bounding box cropped with a 2% margin",
        "Per-channel 2nd-98th percentile linear stretch to 8-bit RGB",
        "BLIP image processor resize/normalization (384 px, ImageNet mean/std)",
    ])

    limitations = [
        "The caption is generated by a pretrained BLIP model fine-tuned on the RSICD "
        "remote-sensing captioning dataset. It is model output, not a verified "
        "ground-truth description or a quantitative measurement.",
        "The model was trained on RGB remote-sensing images and can miss small, rare, "
        "or ambiguous features; it may describe generic land-cover patterns.",
        "Caption quality depends on the acquisition (cloud cover, haze, season, "
        "resolution) and on the deterministic 2nd-98th percentile RGB stretch applied "
        "to the selected AOI.",
        "Invalid/cloud-masked pixels are rendered black. Read the caption together with "
        "the valid-pixel fraction and the deterministic index/statistics evidence.",
        "Captions are English-language model output. No calibrated per-caption "
        "confidence score is reported because the model does not expose one.",
    ]

    area = float(aoi_area_km2) if aoi_area_km2 is not None else rendered.aoi_area_km2
    evidence = {
        "operation": "image_captioning",
        "scenes": [{
            "item_id": scene.item_id,
            "datetime": scene.datetime,
            "cloud_cover": scene.cloud_cover,
            "resolution_m": scene.resolution_m,
            "crs": scene.crs,
            "processing_level": scene.processing_level,
            "source": scene.source,
            "provider": scene.provider,
            "collection": scene.collection,
            "platform": scene.platform,
            "coverage_fraction": scene.coverage_fraction,
            "sensor": scene.sensor,
            "sensor_identity": scene.sensor_identity,
        }],
        "aoi_area_km2": area,
        "formula": (
            "RGB display = per-channel 2nd-98th percentile linear stretch of "
            "Sentinel-2 L2A surface reflectance (B04 red, B03 green, B02 blue)"
        ),
        "bands": ["B04 (red)", "B03 (green)", "B02 (blue)"],
        "preprocessing": preprocessing,
        "thresholds": {
            "min_valid_pixel_fraction": settings.min_valid_fraction,
            "stretch_low_percentile": STRETCH_PERCENTILES[0],
            "stretch_high_percentile": STRETCH_PERCENTILES[1],
        },
        "valid_pixel_fraction": rendered.valid_fraction,
        "metrics": {
            "valid_pixel_count": rendered.valid_pixel_count,
            "aoi_pixel_count": rendered.aoi_pixel_count,
            "rendered_width": rendered.width,
            "rendered_height": rendered.height,
            "crop": rendered.crop,
            "stretch": rendered.stretch,
            "model_input_size": MODEL_INPUT_SIZE,
            "input_image_filename": "caption_input.png",
        },
        "model": model_meta,
    }

    facts = {
        "operation": "image_captioning",
        "caption": caption,
        "source_scene_id": scene.item_id,
        "acquisition_datetime": scene.datetime,
        "model_name": MODEL_DISPLAY_NAME,
        "model_repository": MODEL_REPO,
        "model_revision": MODEL_REVISION,
        "valid_pixel_fraction": rendered.valid_fraction,
        "rendered_width": rendered.width,
        "rendered_height": rendered.height,
    }

    return {
        "facts": facts,
        "evidence": evidence,
        "limitations": limitations,
        "model": model_meta,
    }
