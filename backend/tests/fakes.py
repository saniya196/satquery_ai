"""Synthetic scenes for TESTS ONLY. Never used by the application."""
from datetime import date, datetime, timezone
import numpy as np
from affine import Affine

from app.satellite.provider import SatelliteProvider, SceneData
from app.core.errors import NoImageryError

TF = Affine(10, 0, 500000, 0, -10, 4000000)
SHAPE = (60, 60)
AOI = {"type": "Polygon", "coordinates": [[[78.0, 17.0], [78.01, 17.0], [78.01, 17.01], [78.0, 17.01], [78.0, 17.0]]]}


def make_scene(item_id, dt, ndvi_left=0.8, ndvi_right=0.8, cloud=5.0, cloudy_fraction=0.0, tf=TF,
               coverage=None):
    """Synthetic-only scene: pick NIR=0.5 and solve RED for the requested NDVI."""
    nir = np.full(SHAPE, 0.5)
    red = np.empty(SHAPE)
    for cols, target in ((slice(0, 30), ndvi_left), (slice(30, 60), ndvi_right)):
        red[:, cols] = 0.5 * (1 - target) / (1 + target)
    scl = np.full(SHAPE, 4, dtype=np.uint8)
    if cloudy_fraction:
        n = int(SHAPE[0] * cloudy_fraction)
        scl[:n, :] = 9
    bands = {"blue": np.full(SHAPE, 0.1), "green": np.full(SHAPE, 0.2), "red": red,
             "nir": nir, "swir1": np.full(SHAPE, 0.15)}
    scene = dict(item_id=item_id, datetime=dt, cloud=cloud, bands=bands, scl=scl, tf=tf)
    if coverage is not None:
        scene["coverage"] = coverage
    return scene


class FakeProvider(SatelliteProvider):
    def __init__(self, scenes):
        self.scenes = {s["item_id"]: s for s in scenes}

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        out = []
        for s in self.scenes.values():
            d = datetime.fromisoformat(s["datetime"]).date()
            if start <= d <= end and s["cloud"] <= max_cloud:
                item = {"item_id": s["item_id"], "datetime": s["datetime"], "cloud_cover": s["cloud"],
                        "provider": "synthetic test provider", "collection": "sentinel-2-l2a",
                        "platform": "Sentinel-2A", "processing_level": "L2A"}
                if "coverage" in s:
                    item["coverage"] = s["coverage"]
                out.append(item)
        return sorted(out, key=lambda x: x["datetime"])

    def resolve_scene(self, aoi_geojson, item_id, max_cloud, start=None, end=None,
                      required_bands=None, min_coverage=0.99):
        scene = self.scenes.get(item_id)
        if scene is None:
            raise NoImageryError(f"Selected scene {item_id} was not found in the synthetic test catalog.")
        acquired = datetime.fromisoformat(scene["datetime"].replace("Z", "+00:00")).date()
        if start is not None and (end is None or not start <= acquired <= end):
            raise NoImageryError(f"Selected scene {item_id} is outside the requested date range.")
        if scene["cloud"] > max_cloud:
            raise NoImageryError(f"Selected scene {item_id} exceeds the cloud-cover limit.")
        missing = set(required_bands or ()) - set(scene["bands"])
        if missing:
            raise NoImageryError(f"Selected scene {item_id} is missing required bands: {', '.join(sorted(missing))}.")
        utc_acquired = datetime.fromisoformat(scene["datetime"].replace("Z", "+00:00")).astimezone(timezone.utc).date()
        metadata = {"item_id": item_id, "datetime": scene["datetime"], "acquisition_date": acquired,
                    "utc_acquisition_date": utc_acquired,
                    "cloud_cover": scene["cloud"], "collection": "sentinel-2-l2a",
                    "provider": "synthetic test provider", "platform": "Sentinel-2A",
                    "processing_level": "L2A"}
        if "coverage" in scene:
            metadata["coverage"] = scene["coverage"]
        return metadata

    def get_scene(self, aoi_geojson, item_id, bands):
        s = self.scenes[item_id]
        return SceneData(item_id, s["datetime"], s["cloud"], {b: s["bands"][b] for b in bands}, s["scl"],
                         s["tf"], "EPSG:32644", np.ones(SHAPE, dtype=bool), 10.0, ["synthetic test scene"])


class FakeLandCoverClassifier:
    """Synthetic classifier for API tests; emits all four product-class codes."""
    bands_logical = ("blue", "green", "red", "nir", "swir1")
    tile = 64

    def classify_cube(self, cube, valid, pixel_area_m2):
        height, width = valid.shape
        class_map = np.tile(np.arange(width, dtype=np.int16) % 4, (height, 1))
        class_map[~valid] = -1
        counts = [(class_map == code).sum() for code in range(4)]
        names = ("vegetation", "agricultural_land", "built_up", "water")
        classes = {
            name: {"pixels": int(count), "fraction": float(count / max(valid.sum(), 1)),
                   "area_km2": float(count * pixel_area_m2 / 1e6)}
            for name, count in zip(names, counts)
        }
        dominant_class = max(classes, key=lambda name: classes[name]["pixels"])
        return {
            "class_map": class_map,
            "class_map_10": np.zeros(valid.shape, dtype=np.int16),
            "confidence_map": np.where(valid, 0.9, np.nan),
            "distribution": {"classified_pixels": int(valid.sum()), "classes": classes},
            "distribution_10class": {},
            "dominant_class": dominant_class,
            "n_tiles_classified": 1,
            "n_tiles_skipped": 0,
            "edge_pixels_unused": 0,
            "mean_confidence": 0.9,
            "low_confidence_tile_fraction": 0.0,
        }

    def model_info(self):
        return {"test_accuracy_10class": 0.9, "test_accuracy_product": 0.9, "limitations": []}
