"""Filesystem-based artifact store for analysis outputs (rasters/arrays)."""
import json
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np
from affine import Affine


def artifacts_dir() -> Path:
    configured = os.getenv("SATQUERY_ARTIFACTS_DIR")
    if configured:
        p = Path(configured).expanduser()
    else:
        p = Path(__file__).resolve().parents[2] / ".data" / "artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _job_dir(job_id: str) -> Path:
    d = artifacts_dir() / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _serialize_scalar(value: Any) -> dict:
    if isinstance(value, Affine):
        return {"type": "transform", "value": list(value)[:6]}
    return {"type": "value", "value": value}


def _deserialize_scalar(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    t = entry.get("type")
    if t == "transform":
        values = entry.get("value")
        if isinstance(values, list) and len(values) == 6:
            return Affine(*[float(v) for v in values])
        return None
    if t == "value":
        return entry.get("value")
    return entry


def save_artifacts(job_id: str, arrays: Optional[dict], raster: Optional[dict],
                   operation: Any = None) -> Optional[dict]:
    if not arrays and not raster:
        return None
    job_dir = _job_dir(job_id)
    meta: dict[str, Any] = {
        "arrays": {},
        "raster": None,
        "operation": str(operation) if operation is not None else None,
    }
    if arrays:
        for k, v in arrays.items():
            if isinstance(v, np.ndarray):
                path = job_dir / f"array_{k}.npy"
                np.save(path, np.asarray(v))
                meta["arrays"][k] = str(path)
    if raster:
        rmeta: dict[str, Any] = {}
        for k, v in raster.items():
            if isinstance(v, np.ndarray):
                path = job_dir / f"raster_{k}.npy"
                np.save(path, np.asarray(v))
                rmeta[k] = {"type": "array", "path": str(path)}
            else:
                rmeta[k] = _serialize_scalar(v)
        meta["raster"] = rmeta
        # Human-readable copy of the non-array raster metadata.
        (job_dir / "raster_meta.json").write_text(json.dumps(rmeta, default=str))
    meta_path = job_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, default=str))
    return meta


def load_artifacts(job_id: str) -> Optional[dict]:
    """Load persisted arrays/raster metadata for a job.

    Returns None when the artifact directory or meta.json is missing, or when
    any artifact file is missing/corrupt, so callers can degrade gracefully
    instead of failing the request.
    """
    job_dir = artifacts_dir() / job_id
    meta_path = job_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    result: dict[str, Any] = {}
    try:
        arrays_meta = meta.get("arrays") or {}
        if not isinstance(arrays_meta, dict):
            return None
        for k, p in arrays_meta.items():
            try:
                result[k] = np.load(p)
            except Exception:
                return None
        raster_meta = meta.get("raster")
        if raster_meta:
            if not isinstance(raster_meta, dict):
                return None
            r: dict[str, Any] = {}
            for k, v in raster_meta.items():
                if isinstance(v, dict) and v.get("type") == "array":
                    try:
                        r[k] = np.load(v["path"])
                    except Exception:
                        return None
                elif isinstance(v, dict) and v.get("type") == "transform":
                    tf = _deserialize_scalar(v)
                    if tf is None:
                        return None
                    r[k] = tf
                elif isinstance(v, dict) and v.get("type") == "value":
                    r[k] = v.get("value")
                else:
                    # Unknown raster entry: skip rather than corrupt the load.
                    pass
            result.update(r)
    except Exception:
        return None
    return result
