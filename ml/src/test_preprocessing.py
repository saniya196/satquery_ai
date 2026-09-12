from preprocessing import load_bands, compute_ndvi, compute_ndwi, summarize_index

bands = load_bands("../data/AnnualCrop_1.tif")
ndvi = compute_ndvi(bands)
ndwi = compute_ndwi(bands)
print("AnnualCrop NDVI:", summarize_index(ndvi))
print("AnnualCrop NDWI:", summarize_index(ndwi))

bands2 = load_bands("../data/SeaLake_1.tif")
ndvi2 = compute_ndvi(bands2)
print("SeaLake NDVI:", summarize_index(ndvi2))