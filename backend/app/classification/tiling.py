"""Cut an AOI raster into model-sized tiles and stitch predictions back. numpy only."""
import numpy as np

from app.classification.labels import TILE


def tile_array(cube, valid, tile=TILE, min_valid_fraction=0.8):
    """cube: (C,H,W) reflectance (NaN allowed). valid: (H,W) bool.

    Non-overlapping tiles; partial edge tiles and tiles with too few valid pixels are skipped
    (and counted, never silently invented). Invalid pixels inside a kept tile are filled with
    that tile's per-band mean of valid pixels.
    """
    cube = np.asarray(cube, dtype=np.float32)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(cube).all(axis=0)
    _, H, W = cube.shape
    tiles, origins, skipped = [], [], 0
    for r in range(0, H - tile + 1, tile):
        for c in range(0, W - tile + 1, tile):
            v = valid[r:r + tile, c:c + tile]
            if v.mean() < min_valid_fraction:
                skipped += 1
                continue
            t = cube[:, r:r + tile, c:c + tile].copy()
            if not v.all():
                for b in range(t.shape[0]):
                    t[b][~v] = t[b][v].mean()
            tiles.append(t)
            origins.append((r, c))
    n_total = len(tiles) + skipped
    return {"tiles": np.stack(tiles) if tiles else np.empty((0, cube.shape[0], tile, tile), np.float32),
            "origins": origins, "n_tiles_total": n_total, "n_skipped": skipped,
            "edge_pixels_unused": int(H * W - n_total * tile * tile)}


def stitch(pred, conf, origins, shape_hw, valid=None, tile=TILE):
    """Return (class_map int16 with -1 = not classified, confidence_map float32 with NaN)."""
    H, W = shape_hw
    class_map = np.full((H, W), -1, dtype=np.int16)
    conf_map = np.full((H, W), np.nan, dtype=np.float32)
    for (r, c), p, q in zip(origins, pred, conf):
        class_map[r:r + tile, c:c + tile] = p
        conf_map[r:r + tile, c:c + tile] = q
    if valid is not None:
        class_map[~np.asarray(valid, dtype=bool)] = -1
        conf_map[~np.asarray(valid, dtype=bool)] = np.nan
    return class_map, conf_map


def class_distribution(class_map, names, pixel_area_m2):
    """Share of CLASSIFIED pixels per class (unclassified pixels are reported separately)."""
    cm = np.asarray(class_map)
    done = cm >= 0
    n = int(done.sum())
    dist = {}
    for i, name in enumerate(names):
        k = int((cm == i).sum())
        dist[name] = {"pixels": k, "fraction": (k / n) if n else None, "area_km2": k * pixel_area_m2 / 1e6}
    return {"classes": dist, "classified_pixels": n, "unclassified_pixels": int(cm.size - n),
            "classified_fraction": n / cm.size if cm.size else 0.0}
