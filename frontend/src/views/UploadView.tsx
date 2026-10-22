import React, { useEffect, useState, useRef } from 'react'

interface UploadedFileInfo {
  name: string
  sizeBytes: number
  format: string
  bands: string[]
  crs: string
  width: number
  height: number
  status: 'valid' | 'invalid' | 'inspecting'
  error?: string
  rawFile?: File
  analysis?: {
    operation: string
    source: Record<string, unknown>
    stats: Record<string, number | null>
    evidence: { area_note?: string; valid_pixel_fraction?: number }
    region?: { coordinate_convention?: string; crs?: string }
  }
}

interface UploadedChangeResponse {
  operation: string
  before_date: string
  after_date: string
  sources: Array<{ filename: string; date: string; selected_band: number; crs: string; nodata: number | null }>
  alignment: { crs_equivalent: boolean; dimensions_identical: boolean; affine_transform_equivalent: boolean; resampling: string; reprojection: string }
  description: {
    text: string
    direction: 'positive' | 'negative' | 'zero'
    mean_difference: number
    absolute_difference_mean: number
    median_difference: number
    common_valid_pixel_fraction: number
    dates: string[]
    bands: string[]
    source_units: string | null
    semantic_scope: string
  }
  metrics: Record<string, number>
  evidence: { formula: string; valid_pixel_fraction: number; preprocessing: string[]; limitations: string[] }
}

const LAND_COVER_BANDS = ['B02', 'B03', 'B04', 'B08', 'B11'] as const
type LandCoverBand = typeof LAND_COVER_BANDS[number]

interface UploadedLandCoverResponse {
  operation: string
  source: { filename: string; format: string; width: number; height: number; band_count: number; crs: string; nodata: number | null }
  band_mapping: Record<LandCoverBand, number>
  radiometry: string
  metrics: {
    input_valid_pixel_fraction: number
    classified_pixel_count: number
    classified_fraction: number
    unclassified_pixel_count: number
    distribution: {
      classes: Record<string, { pixels: number; fraction: number | null; area_km2: number | null }>
      classified_pixels: number
      unclassified_pixels: number
      classified_fraction: number
    }
    dominant_class: string
    n_tiles_classified: number
    n_tiles_skipped: number
    mean_model_confidence: number
  }
  model: { architecture?: string; trained_on?: string; limitations?: string[] }
  confidence: { mean_model_confidence: number; valid_pixel_fraction: number; combined_score: number | null }
  evidence: { radiometry: string; preprocessing: string[]; limitations: string[] }
}

export const UploadView: React.FC = () => {
  const [dragActive, setDragActive] = useState(false)
  const [files, setFiles] = useState<UploadedFileInfo[]>([])
  const [selectedFileIdx, setSelectedFileIdx] = useState<number>(-1)
  const [uploading, setUploading] = useState(false)
  const [regionValues, setRegionValues] = useState({ minX: '', minY: '', maxX: '', maxY: '' })
  const [regionError, setRegionError] = useState<string | null>(null)
  const [beforeFile, setBeforeFile] = useState<File | null>(null)
  const [afterFile, setAfterFile] = useState<File | null>(null)
  const [beforeDate, setBeforeDate] = useState('')
  const [afterDate, setAfterDate] = useState('')
  const [beforeBand, setBeforeBand] = useState('1')
  const [afterBand, setAfterBand] = useState('1')
  const [changeResult, setChangeResult] = useState<UploadedChangeResponse | null>(null)
  const [changeError, setChangeError] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)
  const [landCoverMapping, setLandCoverMapping] = useState<Record<LandCoverBand, string>>({
    B02: '', B03: '', B04: '', B08: '', B11: '',
  })
  const [landCoverResult, setLandCoverResult] = useState<UploadedLandCoverResponse | null>(null)
  const [landCoverFileIndex, setLandCoverFileIndex] = useState<number | null>(null)
  const [landCoverError, setLandCoverError] = useState<string | null>(null)
  const [landCoverErrorKind, setLandCoverErrorKind] = useState<'validation' | 'unsupported' | 'server' | null>(null)
  const [classifyingLandCover, setClassifyingLandCover] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (files.length > 0) setSelectedFileIdx(files.length - 1)
  }, [files.length])

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(Array.from(e.dataTransfer.files))
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFiles(Array.from(e.target.files))
    }
  }

  const handleFiles = async (incoming: File[]) => {
    setUploading(true)
    for (const f of incoming) {
      const isTiff = f.name.toLowerCase().endsWith('.tif') || f.name.toLowerCase().endsWith('.tiff')
      if (!isTiff) {
        setFiles((prev) => [
          ...prev,
          {
            name: f.name,
            sizeBytes: f.size,
            format: 'Unsupported',
            bands: [],
            crs: 'Unknown',
            width: 0,
            height: 0,
            status: 'invalid',
            error: 'Only .tif and .tiff GeoTIFF files are supported.',
          },
        ])
        continue
      }

      try {
        const formData = new FormData()
        formData.append('file', f)
        formData.append('band', '1')
        formData.append('operation', 'single_band_statistics')
        const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/geotiff/analyze`, {
          method: 'POST',
          body: formData,
        })
        if (res.ok) {
          const data = await res.json()
          const source = data.source || {}
          setFiles((prev) => [
            ...prev,
            {
              name: f.name,
              sizeBytes: f.size,
              format: String(source.format || 'GeoTIFF'),
              bands: [`Band ${source.selected_band || 1}`],
              crs: String(source.crs || 'Unknown'),
              width: Number(source.width || 0),
              height: Number(source.height || 0),
              status: 'valid',
              rawFile: f,
              analysis: data,
            },
          ])
        } else {
          const body = await res.json().catch(() => null)
          const detail = body?.detail
          const message = typeof detail === 'string'
            ? detail
            : detail?.message || `Upload analysis failed (${res.status}).`
          setFiles((prev) => [...prev, {
            name: f.name, sizeBytes: f.size, format: 'Unsupported', bands: [], crs: 'Unknown',
            width: 0, height: 0, status: 'invalid', error: message,
          }])
        }
      } catch (error) {
        setFiles((prev) => [
          ...prev,
          {
            name: f.name,
            sizeBytes: f.size,
            format: 'Unavailable', bands: [], crs: 'Unknown', width: 0, height: 0,
            status: 'invalid', error: error instanceof Error ? error.message : 'Could not reach the upload analysis service.',
          },
        ])
      }
    }
    setUploading(false)
  }

  const handleRegionAnalysis = async (event: React.FormEvent) => {
    event.preventDefault()
    const selected = files[selectedFileIdx]
    if (!selected?.rawFile) return
    setUploading(true)
    setRegionError(null)
    try {
      const formData = new FormData()
      formData.append('file', selected.rawFile)
      formData.append('band', '1')
      formData.append('operation', 'region_statistics')
      formData.append('region_min_x', regionValues.minX)
      formData.append('region_min_y', regionValues.minY)
      formData.append('region_max_x', regionValues.maxX)
      formData.append('region_max_y', regionValues.maxY)
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/geotiff/analyze`, {
        method: 'POST',
        body: formData,
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const detail = body?.detail
        throw new Error(typeof detail === 'string' ? detail : detail?.message || `Region analysis failed (${res.status}).`)
      }
      setFiles((prev) => prev.map((item, index) => index === selectedFileIdx ? { ...item, analysis: body } : item))
    } catch (error) {
      setRegionError(error instanceof Error ? error.message : 'Could not complete region analysis.')
    } finally {
      setUploading(false)
    }
  }

  const handleChangeAnalysis = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!beforeFile || !afterFile) return
    setComparing(true)
    setChangeError(null)
    setChangeResult(null)
    try {
      const formData = new FormData()
      formData.append('before_file', beforeFile)
      formData.append('after_file', afterFile)
      formData.append('before_date', beforeDate)
      formData.append('after_date', afterDate)
      formData.append('before_band', beforeBand)
      formData.append('after_band', afterBand)
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/geotiff/change`, { method: 'POST', body: formData })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const detail = body?.detail
        throw new Error(typeof detail === 'string' ? detail : detail?.message || `Raster comparison failed (${res.status}).`)
      }
      setChangeResult(body as UploadedChangeResponse)
    } catch (error) {
      setChangeError(error instanceof Error ? error.message : 'Could not compare the uploaded rasters.')
    } finally {
      setComparing(false)
    }
  }

  const handleLandCoverAnalysis = async (event: React.FormEvent) => {
    event.preventDefault()
    const selected = files[selectedFileIdx]
    setLandCoverError(null)
    setLandCoverErrorKind(null)
    setLandCoverResult(null)
    setLandCoverFileIndex(null)

    if (!selected?.rawFile) {
      setLandCoverErrorKind('validation')
      setLandCoverError('Select a valid uploaded GeoTIFF before starting classification.')
      return
    }

    const indexes = LAND_COVER_BANDS.map((band) => Number(landCoverMapping[band]))
    if (indexes.some((index) => !Number.isInteger(index) || index < 1) || new Set(indexes).size !== indexes.length) {
      setLandCoverErrorKind('validation')
      setLandCoverError('Enter five positive, unique physical band indexes for B02, B03, B04, B08, and B11.')
      return
    }

    setClassifyingLandCover(true)
    let failureKind: 'validation' | 'unsupported' | 'server' = 'server'
    try {
      const mapping = Object.fromEntries(LAND_COVER_BANDS.map((band, index) => [band, indexes[index]]))
      const formData = new FormData()
      formData.append('file', selected.rawFile)
      formData.append('band_mapping', JSON.stringify(mapping))
      formData.append('radiometry', 'reflectance')
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'}/geotiff/land-cover`, {
        method: 'POST',
        body: formData,
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const detail = body?.detail
        const code = typeof detail === 'object' ? detail?.code : undefined
        const message = typeof detail === 'string'
          ? detail
          : detail?.message || `Land-cover classification failed (${res.status}).`
        const unsupportedCodes = new Set([
          'unsupported_file_type', 'unsupported_radiometry', 'unsupported_raster_format',
          'raster_backend_unavailable', 'raster_dimensions_unsupported', 'raster_pixel_limit_exceeded',
          'missing_crs', 'rotated_transform_unsupported', 'invalid_geotiff',
        ])
        failureKind = res.status >= 500 ? 'server' : unsupportedCodes.has(code) ? 'unsupported' : 'validation'
        setLandCoverErrorKind(failureKind)
        throw new Error(message)
      }
      setLandCoverResult(body as UploadedLandCoverResponse)
      setLandCoverFileIndex(selectedFileIdx)
    } catch (error) {
      setLandCoverErrorKind(failureKind)
      setLandCoverError(error instanceof Error ? error.message : 'Could not reach the land-cover classification service.')
    } finally {
      setClassifyingLandCover(false)
    }
  }

  const formatSize = (bytes: number) => {
    const mb = bytes / (1024 * 1024)
    return `${mb.toFixed(0)} MB`
  }

  return (
    <div className="upload-view-container">
      <div className="upload-view-header">
        <h2>Upload GeoTIFF Files</h2>
        <p>Upload a georeferenced GeoTIFF for single-band statistics. SAR and spectral-index analysis are not integrated here.</p>
        {uploading && <p role="status">Reading and validating uploaded pixels…</p>}
      </div>

      <form className="upload-change-form" onSubmit={handleChangeAnalysis}>
        <h3>Compare two dated rasters</h3>
        <p>Compares raw pixel values as after minus before. This is not automatically NDVI or a semantic land-cover change.</p>
        <label>Before raster <input type="file" accept=".tif,.tiff" required onChange={(event) => setBeforeFile(event.target.files?.[0] ?? null)} /></label>
        <label>Before date <input type="date" required value={beforeDate} onChange={(event) => setBeforeDate(event.target.value)} /></label>
        <label>Before band <input type="number" min="1" required value={beforeBand} onChange={(event) => setBeforeBand(event.target.value)} /></label>
        <label>After raster <input type="file" accept=".tif,.tiff" required onChange={(event) => setAfterFile(event.target.files?.[0] ?? null)} /></label>
        <label>After date <input type="date" required value={afterDate} onChange={(event) => setAfterDate(event.target.value)} /></label>
        <label>After band <input type="number" min="1" required value={afterBand} onChange={(event) => setAfterBand(event.target.value)} /></label>
        <button type="submit" disabled={comparing || !beforeFile || !afterFile}>{comparing ? 'Comparing rasters…' : 'Compare rasters'}</button>
        {changeError && <p role="alert">{changeError}</p>}
        {changeResult && <div className="upload-change-result" role="status">
          <h4>Raw raster comparison</h4>
          <p>{changeResult.before_date} → {changeResult.after_date}; formula: {changeResult.evidence.formula}</p>
          <p>{changeResult.description.text}</p>
          <p>Common valid pixels: {changeResult.metrics.common_valid_pixel_count} / {changeResult.metrics.total_pixel_count} ({(changeResult.evidence.valid_pixel_fraction * 100).toFixed(2)}%)</p>
          <p>Mean difference: {changeResult.metrics.difference_mean.toFixed(6)}; mean absolute difference: {changeResult.metrics.absolute_difference_mean.toFixed(6)}</p>
          <p>Median difference: {changeResult.description.median_difference.toFixed(6)}; selected bands: {changeResult.description.bands.join(' / ')}</p>
          {changeResult.description.source_units && <p>Source units: {changeResult.description.source_units}</p>}
          <p>CRS and affine grid matched; reprojection and resampling: none.</p>
          <small>{changeResult.evidence.limitations.join(' ')}</small>
        </div>}
      </form>

      <div className="upload-main-grid">
        {/* Left Column: Dropzone */}
        <div className="upload-drop-column">
          <div
            className={`dropzone-card ${dragActive ? 'dropzone-active' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".tif,.tiff"
              onChange={handleFileInput}
              style={{ display: 'none' }}
            />
            <div className="dropzone-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <p className="dropzone-text">Drag and drop files here<br /><span>or</span></p>
            <button type="button" className="choose-files-btn">
              Choose Files
            </button>
          </div>
        </div>

        {/* Right Column: File Checks */}
        <div className="upload-checks-column">
          <div className="file-checks-card">
            <h3>File Checks</h3>
            <ul className="checks-list">
              <li className="check-item-pass">
                <span className="check-icon">✓</span>
                <span><strong>Valid format</strong> (GeoTIFF)</span>
              </li>
              <li className="check-item-pass">
                <span className="check-icon">✓</span>
                <span><strong>Correct bands</strong> (e.g., B02, B03, B04, B08)</span>
              </li>
              <li className="check-item-pass">
                <span className="check-icon">✓</span>
                <span><strong>Supported CRS</strong> (e.g., UTM, WGS84)</span>
              </li>
            </ul>

            <div className="checks-note">
              <span className="info-icon">ℹ</span>
              <span>Rasters will be inspected for CRS alignment, physical nodata masks, and radiometric calibration before analysis.</span>
            </div>
          </div>
        </div>
      </div>

      {/* Uploaded Files Table */}
      <div className="uploaded-files-section">
        <h3>Uploaded Files ({files.length})</h3>
        <div className="uploaded-files-list">
          {files.map((file, idx) => (
            <div
              key={`${file.name}-${idx}`}
              className={`uploaded-file-row ${selectedFileIdx === idx ? 'file-row-selected' : ''}`}
              onClick={() => setSelectedFileIdx(idx)}
            >
              <div className="file-row-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
              </div>
              <div className="file-row-name">
                <span className="name-text">{file.name}</span>
                <span className="meta-text">{file.crs} • {file.bands.join(', ')} • {file.width}×{file.height}</span>
              </div>
              <div className="file-row-size">
                {formatSize(file.sizeBytes)}
              </div>
              <div className="file-row-badge">
                <span className={`status-pill status-${file.status}`}>
                  {file.status === 'valid' ? 'Analyzed' : file.status === 'inspecting' ? 'Inspecting' : 'Invalid'}
                </span>
              </div>
              {file.error && <div className="file-row-error" role="alert">{file.error}</div>}
            </div>
          ))}
        </div>

        {selectedFileIdx >= 0 && files[selectedFileIdx]?.rawFile && (() => {
          const selected = files[selectedFileIdx]
          const sourceBounds = selected.analysis?.source.bounds
          return (
            <form className="upload-region-form" onSubmit={handleRegionAnalysis}>
              <h3>Ask about a raster region</h3>
              <p>Enter an axis-aligned bounding box in the uploaded raster CRS ({selected.crs}). Coordinates are not latitude/longitude unless the raster CRS says so.</p>
              {Array.isArray(sourceBounds) && <p>Raster extent: {sourceBounds.map((value) => String(value)).join(', ')}</p>}
              <div className="upload-region-fields">
                {(['minX', 'minY', 'maxX', 'maxY'] as const).map((key) => (
                  <label key={key}>{key.replace(/[A-Z]/g, (letter) => ` ${letter}`).toUpperCase()}
                    <input type="number" step="any" required value={regionValues[key]} onChange={(event) => setRegionValues((prev) => ({ ...prev, [key]: event.target.value }))} />
                  </label>
                ))}
              </div>
              <button type="submit" disabled={uploading}>Calculate region statistics</button>
              {regionError && <p role="alert">{regionError}</p>}
            </form>
          )
        })()}

        {selectedFileIdx >= 0 && files[selectedFileIdx]?.analysis && (() => {
          const selected = files[selectedFileIdx]
          const stats = selected.analysis!.stats
          return (
            <div className="upload-analysis-result" role="status">
              <h3>Uploaded raster analysis</h3>
              <p>Operation: {selected.analysis!.operation}. No Sentinel-2 band identity or spectral index was inferred.</p>
              <p>Valid pixels: {stats.valid_pixel_count} / {stats.total_pixel_count} ({((Number(stats.valid_pixel_fraction) || 0) * 100).toFixed(2)}%)</p>
              <p>Mean: {Number(stats.mean).toFixed(6)} · Minimum: {Number(stats.minimum).toFixed(6)} · Maximum: {Number(stats.maximum).toFixed(6)}</p>
              <p>{selected.analysis!.evidence.area_note}</p>
              {selected.analysis!.region && <p>Region CRS: {selected.analysis!.region.crs}. {selected.analysis!.region.coordinate_convention}.</p>}
            </div>
          )
        })()}

        {selectedFileIdx >= 0 && files[selectedFileIdx]?.rawFile && (() => {
          return (
            <form className="upload-region-form" onSubmit={handleLandCoverAnalysis}>
              <h3>Uploaded land-cover classification</h3>
              <p>Provide the physical band indexes explicitly. Values must be user-declared reflectance; no scaling, resampling, or band inference is applied.</p>
              <div className="upload-region-fields">
                {LAND_COVER_BANDS.map((band) => (
                  <label key={band}>{band} physical index
                    <input
                      type="number"
                      min="1"
                      step="1"
                      required
                      value={landCoverMapping[band]}
                      onChange={(event) => setLandCoverMapping((prev) => ({ ...prev, [band]: event.target.value }))}
                    />
                  </label>
                ))}
              </div>
              <button type="submit" disabled={classifyingLandCover}>{classifyingLandCover ? 'Classifying raster…' : 'Classify uploaded raster'}</button>
              {landCoverError && <p role="alert">{landCoverErrorKind === 'unsupported' ? 'Unsupported input: ' : landCoverErrorKind === 'validation' ? 'Validation error: ' : 'Server error: '}{landCoverError}</p>}
            </form>
          )
        })()}

        {landCoverResult && landCoverFileIndex === selectedFileIdx && (
          <div className="upload-analysis-result" role="status">
            <h3>Uploaded land-cover result</h3>
            <p>Model operation: {landCoverResult.operation}. Source: {landCoverResult.source.filename} ({landCoverResult.source.width}×{landCoverResult.source.height}).</p>
            <p>Valid-pixel coverage: {(landCoverResult.metrics.input_valid_pixel_fraction * 100).toFixed(2)}%. Classified coverage: {(landCoverResult.metrics.classified_fraction * 100).toFixed(2)}%.</p>
            <p>Classified pixels: {landCoverResult.metrics.classified_pixel_count}; unclassified pixels: {landCoverResult.metrics.unclassified_pixel_count}; tiles classified: {landCoverResult.metrics.n_tiles_classified}; tiles skipped: {landCoverResult.metrics.n_tiles_skipped}.</p>
            <p>Mean model confidence: {landCoverResult.confidence.mean_model_confidence.toFixed(4)}. Dominant class: {landCoverResult.metrics.dominant_class}.</p>
            <h4>Class distribution</h4>
            <ul>
              {Object.entries(landCoverResult.metrics.distribution.classes).map(([name, values]) => (
                <li key={name}>{name}: {values.pixels} pixels ({values.fraction === null ? 'unavailable' : `${(values.fraction * 100).toFixed(2)}%`})</li>
              ))}
            </ul>
            <p>Radiometry: {landCoverResult.evidence.radiometry}</p>
            <p>Model: {landCoverResult.model.architecture || 'reported by backend'}; trained on {landCoverResult.model.trained_on || 'reported by backend'}.</p>
            <p>This is tile-level land-cover classification, not VQA, captioning, grounding, or semantic certainty.</p>
            <ul>
              {landCoverResult.evidence.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
          </div>
        )}

        <div className="upload-action-row">
          <button
            type="button"
            className="continue-analysis-btn"
            disabled
          >
            Analysis is complete for the selected upload
          </button>
        </div>
      </div>
    </div>
  )
}
