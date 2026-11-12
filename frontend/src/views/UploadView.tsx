import React, { useState, useRef } from 'react'
import { useLanguage } from '../i18n'

interface UploadedFileInfo {
  name: string
  sizeBytes: number
  format: string
  bands: string[]
  bandCount?: number
  crs: string
  width: number
  height: number
  status: 'valid' | 'invalid' | 'inspecting'
  error?: string
  rawFile?: File
  analysis?: {
    operation: string
    source: {
      format?: string
      selected_band?: number
      band_count?: number
      crs?: string
      width?: number
      height?: number
      bounds?: number[]
      transform?: number[]
      nodata?: number | null
      resolution?: { x?: number; y?: number; units?: string | null }
      [key: string]: unknown
    }
    stats: {
      valid_pixel_count?: number
      total_pixel_count?: number
      valid_pixel_fraction?: number
      minimum?: number
      maximum?: number
      mean?: number
      median?: number
      standard_deviation?: number
      analysed_area_km2?: number | null
      [key: string]: unknown
    }
    evidence: {
      formula?: string | null
      area_note?: string
      valid_pixel_fraction?: number
      preprocessing?: string[]
      [key: string]: unknown
    }
    region?: { coordinate_convention?: string; crs?: string; [key: string]: unknown }
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

type SelectedActionTab = 'overview' | 'region' | 'landcover'

const GLOSSARY = {
  geotiff: {
    title: 'GeoTIFF (.tif, .tiff)',
    content: 'A standard digital image format embedded with geographical data so every pixel corresponds to an exact location on Earth.',
  },
  crs: {
    title: 'Map Projection (CRS & EPSG Codes)',
    content: 'A Coordinate Reference System (CRS) defines how flat image coordinates match locations on the curved Earth. Codes like EPSG:32632 (UTM zone) measure in meters; EPSG:4326 (WGS 84) measures in degrees latitude/longitude.',
  },
  bands: {
    title: 'Sensor Channels (Raster Bands)',
    content: 'Layered channels within the image file. Each band records light from a specific part of the spectrum (e.g. visible Blue, Green, Red, or invisible Near-Infrared and Shortwave Infrared).',
  },
  statistics: {
    title: 'Measurement Summary (Pixel Statistics)',
    content: 'Calculated mathematical summaries (average, minimum, maximum, spread) computed directly from genuine pixel values. No numbers are guessed or invented.',
  },
  bbox: {
    title: 'Rectangular Area (Bounding Box)',
    content: 'A rectangular area defined by four boundaries: Left/West (Min X), Bottom/South (Min Y), Right/East (Max X), and Top/North (Max Y), in the image coordinate system.',
  },
  validPixels: {
    title: 'Usable Pixel Coverage (Valid Pixels)',
    content: 'The percentage of pixels that contain real sensor measurements, excluding empty border gaps (nodata), cloud masks, or unreadable values.',
  },
  diff: {
    title: 'Raw Pixel Difference',
    content: 'The mathematical subtraction of earlier pixel values from later pixel values (After − Before). Positive numbers mean values increased; negative numbers mean values decreased. This does not automatically establish environmental significance.',
  },
} as const

const InfoTooltip: React.FC<{
  term?: keyof typeof GLOSSARY
  title?: string
  content?: string
}> = ({ term, title, content }) => {
  const [open, setOpen] = useState(false)
  const item = term ? GLOSSARY[term] : null
  const displayTitle = title || item?.title
  const displayContent = content || item?.content || ''

  return (
    <span className="info-tooltip-container">
      <button
        type="button"
        className="info-tooltip-btn"
        aria-label={displayTitle || 'Information'}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setOpen((prev) => !prev)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        ℹ
      </button>
      {open && (
        <span className="info-tooltip-bubble" role="tooltip">
          {displayTitle && <strong className="info-tooltip-title">{displayTitle}</strong>}
          <span className="info-tooltip-text">{displayContent}</span>
        </span>
      )}
    </span>
  )
}

export const UploadView: React.FC = () => {
  const { t } = useLanguage()
  const [dragActive, setDragActive] = useState(false)
  const [files, setFiles] = useState<UploadedFileInfo[]>([])
  const [selectedFileIdx, setSelectedFileIdx] = useState<number>(-1)
  const [activeAction, setActiveAction] = useState<SelectedActionTab>('overview')
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

  const selectedIdxEffective = selectedFileIdx >= 0 && selectedFileIdx < files.length
    ? selectedFileIdx
    : files.length > 0
    ? files.length - 1
    : -1

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
            bandCount: 0,
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
        const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001'}/geotiff/analyze`, {
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
              bandCount: Number(source.band_count || 1),
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
            name: f.name, sizeBytes: f.size, format: 'Unsupported', bands: [], bandCount: 0, crs: 'Unknown',
            width: 0, height: 0, status: 'invalid', error: message,
          }])
        }
      } catch (error) {
        setFiles((prev) => [
          ...prev,
          {
            name: f.name,
            sizeBytes: f.size,
            format: 'Unavailable', bands: [], bandCount: 0, crs: 'Unknown', width: 0, height: 0,
            status: 'invalid', error: error instanceof Error ? error.message : 'Could not reach the upload analysis service.',
          },
        ])
      }
    }
    setUploading(false)
  }

  const handleRegionAnalysis = async (event: React.FormEvent) => {
    event.preventDefault()
    const selected = files[selectedIdxEffective]
    if (!selected?.rawFile) return

    const minX = parseFloat(regionValues.minX)
    const minY = parseFloat(regionValues.minY)
    const maxX = parseFloat(regionValues.maxX)
    const maxY = parseFloat(regionValues.maxY)

    if (isNaN(minX) || isNaN(minY) || isNaN(maxX) || isNaN(maxY)) {
      setRegionError('Please enter valid numeric coordinates for all four boundary edges.')
      return
    }

    if (minX >= maxX) {
      setRegionError(`The Left boundary (Min X: ${minX}) must be smaller than the Right boundary (Max X: ${maxX}).`)
      return
    }

    if (minY >= maxY) {
      setRegionError(`The Bottom boundary (Min Y: ${minY}) must be smaller than the Top boundary (Max Y: ${maxY}).`)
      return
    }

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
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001'}/geotiff/analyze`, {
        method: 'POST',
        body: formData,
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const detail = body?.detail
        throw new Error(typeof detail === 'string' ? detail : detail?.message || `Region analysis failed (${res.status}).`)
      }
      setFiles((prev) => prev.map((item, index) => index === selectedIdxEffective ? { ...item, analysis: body } : item))
    } catch (error) {
      setRegionError(error instanceof Error ? error.message : 'Could not complete region analysis.')
    } finally {
      setUploading(false)
    }
  }

  const handleFillExtent = () => {
    const selected = selectedIdxEffective >= 0 ? files[selectedIdxEffective] : null
    const bounds = selected?.analysis?.source?.bounds
    if (Array.isArray(bounds) && bounds.length >= 4) {
      setRegionValues({
        minX: String(bounds[0]),
        minY: String(bounds[1]),
        maxX: String(bounds[2]),
        maxY: String(bounds[3]),
      })
      setRegionError(null)
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
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001'}/geotiff/change`, { method: 'POST', body: formData })
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
    const selected = files[selectedIdxEffective]
    setLandCoverError(null)
    setLandCoverErrorKind(null)
    setLandCoverResult(null)
    setLandCoverFileIndex(null)

    if (!selected?.rawFile) {
      setLandCoverErrorKind('validation')
      setLandCoverError('Please select a valid uploaded GeoTIFF file before starting land-cover classification.')
      return
    }

    const bandCount = selected.bandCount ?? (selected.analysis?.source?.band_count ? Number(selected.analysis.source.band_count) : 1)
    if (bandCount < 5) {
      setLandCoverErrorKind('unsupported')
      setLandCoverError(`This image contains only ${bandCount} band(s). Land-cover classification requires five compatible spectral bands: Blue, Green, Red, Near Infrared and Shortwave Infrared.`)
      return
    }

    const indexes = LAND_COVER_BANDS.map((band) => Number(landCoverMapping[band]))
    if (indexes.some((index) => !Number.isInteger(index) || index < 1) || new Set(indexes).size !== indexes.length) {
      setLandCoverErrorKind('validation')
      setLandCoverError('Please enter five positive, unique physical band numbers for Blue, Green, Red, NIR, and SWIR-1.')
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
      const res = await fetch(`${import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001'}/geotiff/land-cover`, {
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
      setLandCoverFileIndex(selectedIdxEffective)
    } catch (error) {
      setLandCoverErrorKind(failureKind)
      setLandCoverError(error instanceof Error ? error.message : 'Could not reach the land-cover classification service.')
    } finally {
      setClassifyingLandCover(false)
    }
  }

  const handleOpenCompare = () => {
    const details = document.querySelector('.upload-advanced-section') as HTMLDetailsElement | null
    if (details) {
      details.open = true
      details.scrollIntoView({ behavior: 'smooth' })
    }
  }

  const formatSize = (bytes: number) => {
    const mb = bytes / (1024 * 1024)
    if (mb >= 1) return `${mb.toFixed(1)} MB`
    const kb = bytes / 1024
    return `${kb.toFixed(0)} KB`
  }

  const selected = selectedIdxEffective >= 0 ? files[selectedIdxEffective] : null
  const isSelectedValid = selected?.status === 'valid'
  const isSelectedInvalid = selected?.status === 'invalid'
  const hasValidCrs = isSelectedValid && Boolean(selected.crs && selected.crs !== 'Unknown')
  const hasValidDims = isSelectedValid && selected.width > 0 && selected.height > 0
  const bandCount = selected?.bandCount ?? (selected?.analysis?.source?.band_count ? Number(selected.analysis.source.band_count) : 1)
  const canClassify = isSelectedValid && bandCount >= 5
  const stats = selected?.analysis?.stats
  const sourceBounds = selected?.analysis?.source?.bounds

  return (
    <div className="upload-view-container">
      {/* 1. Header */}
      <div className="upload-view-header">
        <h2>{t('upload.title')}</h2>
        <p>
          Upload your own satellite or aerial image (.tif) to inspect pixel values, analyze a specific rectangular area, identify land cover with AI, or compare two dated images.
        </p>
        {uploading && <p role="status">Reading and validating your image pixels…</p>}
      </div>

      {/* 2. Primary Upload Area (Top of Page) */}
      <div className="upload-main-grid">
        {/* Left Column: Dropzone */}
        <div className="upload-drop-column">
          <div
            className={`dropzone-card ${dragActive ? 'dropzone-active' : ''} ${uploading ? 'dropzone-uploading' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => !uploading && inputRef.current?.click()}
            role="button"
            tabIndex={0}
            aria-label="Upload GeoTIFF image file"
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".tif,.tiff"
              onChange={handleFileInput}
              style={{ display: 'none' }}
              disabled={uploading}
            />
            <div className="dropzone-icon">
              {uploading ? (
                <div className="upload-spinner" aria-hidden="true" />
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              )}
            </div>
            {uploading ? (
              <div className="dropzone-uploading-msg">
                <p className="dropzone-text"><strong>Reading and validating uploaded image pixels…</strong></p>
                <p className="dropzone-subtext">Verifying image structure and calculating baseline statistics.</p>
              </div>
            ) : (
              <>
                <p className="dropzone-text">
                  <strong>Drag & drop your GeoTIFF image here</strong><br />
                  <span>or click to browse files from your computer</span>
                </p>
                <button
                  type="button"
                  className="choose-files-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    inputRef.current?.click()
                  }}
                >
                  Choose Image File (.tif, .tiff)
                </button>
                <p className="dropzone-subtext">
                  Supports GeoTIFF (.tif, .tiff) files up to 100 MB. Measurements are calculated automatically upon upload.
                </p>
              </>
            )}
          </div>
        </div>

        {/* Right Column: File requirements and actual inspection status */}
        <div className="upload-checks-column">
          <div className="file-checks-card">
            <h3>Image requirements & verification</h3>
            <ul className="checks-list checks-list-requirements">
              {/* 1. Format Check */}
              <li className={isSelectedValid ? 'check-item-pass' : isSelectedInvalid ? 'check-item-fail' : 'check-item-requirement'}>
                <span
                  className={`check-icon ${isSelectedValid ? 'check-icon-pass' : isSelectedInvalid ? 'check-icon-fail' : 'check-icon-neutral'}`}
                  aria-hidden="true"
                >
                  {isSelectedValid ? '✓' : isSelectedInvalid ? '✕' : '•'}
                </span>
                <span>
                  <strong>GeoTIFF format</strong> (.tif or .tiff)
                  <InfoTooltip term="geotiff" />
                  {isSelectedValid && ` — Verified structure: ${selected.format || 'GeoTIFF'}`}
                  {isSelectedInvalid && ' — File format is invalid or unreadable'}
                </span>
              </li>

              {/* 2. CRS Check */}
              <li className={hasValidCrs ? 'check-item-pass' : (isSelectedValid && !hasValidCrs) ? 'check-item-warn' : 'check-item-requirement'}>
                <span
                  className={`check-icon ${hasValidCrs ? 'check-icon-pass' : (isSelectedValid && !hasValidCrs) ? 'check-icon-warn' : 'check-icon-neutral'}`}
                  aria-hidden="true"
                >
                  {hasValidCrs ? '✓' : (isSelectedValid && !hasValidCrs) ? '⚠' : '•'}
                </span>
                <span>
                  <strong>Map reference (CRS)</strong>
                  <InfoTooltip term="crs" />
                  {hasValidCrs
                    ? ` — Verified: ${selected.crs}`
                    : (isSelectedValid && !hasValidCrs)
                    ? ' — Missing map reference (area queries unavailable)'
                    : ' — Required to locate coordinates on Earth'}
                </span>
              </li>

              {/* 3. Pixel Grid Dimensions */}
              <li className={hasValidDims ? 'check-item-pass' : 'check-item-requirement'}>
                <span
                  className={`check-icon ${hasValidDims ? 'check-icon-pass' : 'check-icon-neutral'}`}
                  aria-hidden="true"
                >
                  {hasValidDims ? '✓' : '•'}
                </span>
                <span>
                  <strong>Image dimensions</strong>
                  {hasValidDims
                    ? ` — Verified size: ${selected.width} × ${selected.height} pixels`
                    : ' — Positive width and height'}
                </span>
              </li>

              {/* 4. Band Semantics & Radiometry: explicitly user-declared, never green */}
              <li className="check-item-requirement">
                <span className="check-icon check-icon-info" aria-hidden="true">ℹ</span>
                <span>
                  <strong>Sensor channels (Bands)</strong>
                  <InfoTooltip term="bands" />
                  {' — User-declared (not auto-verified). AI land cover requires 5 compatible bands.'}
                </span>
              </li>
            </ul>

            {/* Selected File Inspection Banner */}
            {(() => {
              let status: 'not_checked' | 'checking' | 'passed' | 'needs_attention' = 'not_checked'
              let title = 'Not checked'
              let detail = 'Upload and select a GeoTIFF image above to see verification results.'

              if (uploading && !selected) {
                status = 'checking'
                title = 'Checking'
                detail = 'Reading and validating the uploaded image file…'
              } else if (selected) {
                if (selected.status === 'inspecting' || (uploading && selected.status !== 'valid' && selected.status !== 'invalid')) {
                  status = 'checking'
                  title = 'Checking'
                  detail = `Inspecting ${selected.name}…`
                } else if (selected.status === 'valid') {
                  status = 'passed'
                  title = 'Verified by engine'
                  const crs = selected.crs && selected.crs !== 'Unknown' ? selected.crs : 'Not reported'
                  const dims = selected.width && selected.height ? `${selected.width}×${selected.height}` : 'Not reported'
                  detail = `This image was read successfully. Format: ${selected.format || 'GeoTIFF'}; map reference: ${crs}; dimensions: ${dims} pixels; channels: ${bandCount} band(s). Wavelength labels and calibration values are not verified automatically.`
                } else if (selected.status === 'invalid') {
                  status = 'needs_attention'
                  title = 'Needs attention'
                  detail = selected.error || 'This file could not be inspected. Please check the file format and try again.'
                }
              }

              return (
                <div className={`upload-check-status upload-check-status-${status}`} role="status" aria-live="polite">
                  <div className="upload-check-status-header">
                    <strong>Selected file status: {title}</strong>
                  </div>
                  <p className="upload-check-status-detail">{detail}</p>
                </div>
              )
            })()}

            <details className="technical-details-toggle" style={{ marginTop: 'auto' }}>
              <summary><span>⚙ Technical inspection details (Advanced)</span></summary>
              <div className="technical-details-content">
                <span>The backend inspects affine geotransforms, nodata masks, and finite numerical pixel values. Results shown reflect actual responses received from the backend service without simulated data.</span>
              </div>
            </details>
          </div>
        </div>
      </div>

      {/* 3. Uploaded Files Section */}
      <div className="uploaded-files-section">
        <h3>Uploaded Files ({files.length})</h3>

        {files.length === 0 ? (
          <p className="upload-empty-notice">
            No files uploaded yet. Drag and drop a GeoTIFF image above or click <strong>Choose Image File</strong> to begin.
          </p>
        ) : (
          <div className="uploaded-files-list">
            {files.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className={`uploaded-file-row ${selectedIdxEffective === idx ? 'file-row-selected' : ''}`}
                onClick={() => setSelectedFileIdx(idx)}
                role="button"
                tabIndex={0}
                aria-pressed={selectedIdxEffective === idx}
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
                  <span className="meta-text">
                    {file.format || 'GeoTIFF'} • CRS: {file.crs} • {file.width && file.height ? `${file.width}×${file.height} px` : 'No dims'} • {file.bandCount || 1} band(s)
                  </span>
                </div>
                <div className="file-row-size">
                  {formatSize(file.sizeBytes)}
                </div>
                <div className="file-row-badge">
                  <span className={`status-pill status-${file.status}`}>
                    {file.status === 'valid' ? '✓ Analyzed' : file.status === 'inspecting' ? 'Inspecting' : 'Invalid'}
                  </span>
                </div>
                {file.error && <div className="file-row-error" role="alert">{file.error}</div>}
              </div>
            ))}
          </div>
        )}

        {/* 4. Guided Analysis Selection Cards */}
        {selected && selected.status === 'valid' && (
          <div className="upload-selected-workspace">
            <div className="upload-section-intro">
              <h3>Choose what you want to do with this image</h3>
              <p>Select an analysis below. Each option explains what it measures and only supported actions can be selected.</p>
            </div>

            <div className="guided-analysis-grid">
              {/* Option 1: Understand image values */}
              <button
                type="button"
                className={`guided-card ${activeAction === 'overview' ? 'guided-card-active' : ''}`}
                onClick={() => setActiveAction('overview')}
              >
                <div className="guided-card-header">
                  <span className="guided-card-icon">📊</span>
                  <span className="guided-card-status status-ready">✓ Ready</span>
                </div>
                <div className="guided-card-title">Understand image values</div>
                <p className="guided-card-desc">
                  Inspect average brightness/reflectance, value range, and usable coverage across the whole image.
                </p>
              </button>

              {/* Option 2: Analyze a specific area */}
              <button
                type="button"
                className={`guided-card ${activeAction === 'region' ? 'guided-card-active' : ''} ${!hasValidCrs ? 'guided-card-disabled' : ''}`}
                onClick={() => hasValidCrs && setActiveAction('region')}
                disabled={!hasValidCrs}
              >
                <div className="guided-card-header">
                  <span className="guided-card-icon">📐</span>
                  {hasValidCrs ? (
                    <span className="guided-card-status status-ready">✓ Available</span>
                  ) : (
                    <span className="guided-card-status status-unavailable">Missing CRS</span>
                  )}
                </div>
                <div className="guided-card-title">Analyze a specific area</div>
                <p className="guided-card-desc">
                  Select a rectangular section of this image to calculate measurements inside that boundary.
                </p>
              </button>

              {/* Option 3: Identify land cover */}
              <button
                type="button"
                className={`guided-card ${activeAction === 'landcover' ? 'guided-card-active' : ''} ${!canClassify ? 'guided-card-disabled' : ''}`}
                onClick={() => canClassify && setActiveAction('landcover')}
                disabled={!canClassify}
              >
                <div className="guided-card-header">
                  <span className="guided-card-icon">🌱</span>
                  {canClassify ? (
                    <span className="guided-card-status status-ready">✓ 5 bands ready</span>
                  ) : (
                    <span className="guided-card-status status-unavailable">Requires 5 bands (has {bandCount})</span>
                  )}
                </div>
                <div className="guided-card-title">Identify land cover</div>
                <p className="guided-card-desc">
                  Use EuroSAT AI to classify terrain into categories like forest, water, crops, or urban area.
                </p>
              </button>

              {/* Option 4: Compare two images */}
              <button
                type="button"
                className="guided-card guided-card-compare"
                onClick={handleOpenCompare}
              >
                <div className="guided-card-header">
                  <span className="guided-card-icon">⏱</span>
                  <span className="guided-card-status status-link">Open tool ↓</span>
                </div>
                <div className="guided-card-title">Compare two images</div>
                <p className="guided-card-desc">
                  Compare this image with an earlier or later image taken over the same area to see pixel change.
                </p>
              </button>
            </div>

            {/* TAB 1: Understand Image Values (Full-Image Measurement Summary) */}
            {activeAction === 'overview' && selected.analysis && stats && (
              <div className="upload-tab-panel" role="tabpanel">
                <div className="upload-interpretation-card" role="status">
                  <div className="upload-interpretation-header">
                    <h4>Full-Image Measurement Summary</h4>
                    <span className="upload-result-tag">Single-Band Analysis</span>
                  </div>

                  {/* What was measured */}
                  <div className="upload-interpretation-section">
                    <span className="upload-interpretation-title">What was measured</span>
                    <p className="upload-interpretation-p">
                      Measured genuine sensor values from Band {selected.analysis.source.selected_band || 1} across all {stats.total_pixel_count?.toLocaleString()} pixel locations in `{selected.name}`.
                    </p>
                  </div>

                  {/* Key Metrics Grid */}
                  <div className="upload-metrics-grid">
                    <div className="upload-metric-card">
                      <span className="upload-metric-label">
                        Usable Pixel Coverage
                        <InfoTooltip term="validPixels" />
                      </span>
                      <span className="upload-metric-value">
                        {((Number(stats.valid_pixel_fraction) || 0) * 100).toFixed(2)}%
                      </span>
                      <span className="upload-metric-sub">
                        {stats.valid_pixel_count?.toLocaleString()} / {stats.total_pixel_count?.toLocaleString()} usable pixels
                      </span>
                    </div>

                    <div className="upload-metric-card">
                      <span className="upload-metric-label">
                        Average Pixel Reading
                        <InfoTooltip term="statistics" />
                      </span>
                      <span className="upload-metric-value">
                        {Number(stats.mean).toFixed(4)}
                      </span>
                      <span className="upload-metric-sub">Spread (Std dev): {Number(stats.standard_deviation).toFixed(4)}</span>
                    </div>

                    <div className="upload-metric-card">
                      <span className="upload-metric-label">
                        Measurement Range
                      </span>
                      <span className="upload-metric-value">
                        {Number(stats.minimum).toFixed(2)} … {Number(stats.maximum).toFixed(2)}
                      </span>
                      <span className="upload-metric-sub">Median center: {Number(stats.median).toFixed(4)}</span>
                    </div>

                    <div className="upload-metric-card">
                      <span className="upload-metric-label">
                        Estimated Ground Area
                      </span>
                      <span className="upload-metric-value">
                        {stats.analysed_area_km2 != null ? `${Number(stats.analysed_area_km2).toFixed(3)} km²` : 'Not applicable'}
                      </span>
                      <span className="upload-metric-sub">
                        {stats.analysed_area_km2 != null ? 'Computed from valid pixels' : 'Map projection not in meters'}
                      </span>
                    </div>
                  </div>

                  {/* What the result means */}
                  <div className="upload-interpretation-section">
                    <span className="upload-interpretation-title">What the result means</span>
                    <p className="upload-interpretation-p">
                      Across the entire image, pixels have an average reading of <strong>{Number(stats.mean).toFixed(4)}</strong>, ranging from a minimum of {Number(stats.minimum).toFixed(2)} to a maximum of {Number(stats.maximum).toFixed(2)}. The standard deviation of {Number(stats.standard_deviation).toFixed(4)} indicates how much pixel brightness or reflectance varies from the average.
                    </p>
                    {selected.analysis.evidence.area_note && (
                      <p className="upload-interpretation-p" style={{ marginTop: 4, color: 'var(--muted)', fontSize: 12 }}>
                        {selected.analysis.evidence.area_note}
                      </p>
                    )}
                  </div>

                  {/* Important limitations */}
                  <div className="upload-interpretation-section section-limitations">
                    <span className="upload-interpretation-title">Important limitations</span>
                    <p className="upload-interpretation-p">
                      These figures are raw sensor numbers from Band 1. Without physical sensor calibration or index formulas (like NDVI), they do NOT directly indicate vegetation health, soil moisture, water depth, or environmental quality.
                    </p>
                  </div>

                  {/* Progressive Disclosure: Technical Details */}
                  <details className="technical-details-toggle">
                    <summary><span>⚙ Technical Details & Metadata (Advanced)</span></summary>
                    <div className="technical-details-content">
                      <p><strong>Operation:</strong> <code>{selected.analysis.operation}</code></p>
                      <p><strong>Selected Band:</strong> Band {selected.analysis.source.selected_band || 1}</p>
                      <p><strong>Map Projection (CRS):</strong> {selected.analysis.source.crs || 'None'}</p>
                      {Array.isArray(selected.analysis.source.bounds) && (
                        <p><strong>Bounding Extent:</strong> [{selected.analysis.source.bounds.join(', ')}]</p>
                      )}
                      <p><strong>Nodata Value:</strong> {String(selected.analysis.source.nodata ?? 'None')}</p>
                      {Array.isArray(selected.analysis.evidence.preprocessing) && (
                        <p><strong>Preprocessing Steps:</strong> {selected.analysis.evidence.preprocessing.join('; ')}</p>
                      )}
                    </div>
                  </details>
                </div>
              </div>
            )}

            {/* TAB 2: Analyze a Specific Area (Region Query Form & Result) */}
            {activeAction === 'region' && selected.rawFile && (
              <div className="upload-tab-panel" role="tabpanel">
                <form className="upload-region-form" onSubmit={handleRegionAnalysis}>
                  <div className="upload-section-intro">
                    <h3>Analyze a Specific Area (Rectangular Window)</h3>
                    <p>
                      Select a rectangular area inside your image to calculate measurements inside that boundary.
                      <InfoTooltip term="bbox" />
                    </p>
<p style={{ marginTop: 4, color: 'var(--muted)', fontSize: 12.5 }}>
                      Coordinates must match your image's map coordinate system ({selected.crs}).
                      <InfoTooltip term="crs" />
                    </p>
                  </div>

                  {Array.isArray(sourceBounds) && sourceBounds.length >= 4 && (
                    <div className="raster-bounds-guide">
                      <span>
                        <strong>Image Boundaries:</strong> Left: {Number(sourceBounds[0]).toFixed(2)}, Bottom: {Number(sourceBounds[1]).toFixed(2)}, Right: {Number(sourceBounds[2]).toFixed(2)}, Top: {Number(sourceBounds[3]).toFixed(2)}
                      </span>
                      <button type="button" className="bounds-fill-btn" onClick={handleFillExtent}>
                        Use full image bounds
                      </button>
                    </div>
                  )}

                  <div className="upload-region-fields">
                    <label>
                      <span>
                        Left Edge (Min X)
                        <InfoTooltip title="Left Boundary (Min X)" content="The westernmost or leftmost coordinate of the rectangle." />
                      </span>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="e.g. 500000"
                        value={regionValues.minX}
                        onChange={(event) => setRegionValues((prev) => ({ ...prev, minX: event.target.value }))}
                      />
                    </label>

                    <label>
                      <span>
                        Bottom Edge (Min Y)
                        <InfoTooltip title="Bottom Boundary (Min Y)" content="The southernmost or bottom coordinate of the rectangle." />
                      </span>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="e.g. 1999000"
                        value={regionValues.minY}
                        onChange={(event) => setRegionValues((prev) => ({ ...prev, minY: event.target.value }))}
                      />
                    </label>

                    <label>
                      <span>
                        Right Edge (Max X)
                        <InfoTooltip title="Right Boundary (Max X)" content="The easternmost or rightmost coordinate of the rectangle." />
                      </span>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="e.g. 501000"
                        value={regionValues.maxX}
                        onChange={(event) => setRegionValues((prev) => ({ ...prev, maxX: event.target.value }))}
                      />
                    </label>

                    <label>
                      <span>
                        Top Edge (Max Y)
                        <InfoTooltip title="Top Boundary (Max Y)" content="The northernmost or top coordinate of the rectangle." />
                      </span>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="e.g. 2000000"
                        value={regionValues.maxY}
                        onChange={(event) => setRegionValues((prev) => ({ ...prev, maxY: event.target.value }))}
                      />
                    </label>
                  </div>

                  <div className="upload-form-actions">
                    <button className="upload-primary-btn" type="submit" disabled={uploading}>
                      {uploading ? 'Calculating area measurements…' : 'Calculate area measurements'}
                    </button>
                  </div>

                  {regionError && (
                    <p className="upload-form-error" role="alert">
                      {regionError}
                    </p>
                  )}
                </form>

                {selected.analysis && selected.analysis.region && (
                  <div className="upload-interpretation-card" style={{ marginTop: 16 }} role="status">
                    <div className="upload-interpretation-header">
                      <h4>Selected Area Measurement Summary</h4>
                      <span className="upload-result-tag">Area Analysis</span>
                    </div>

                    <div className="upload-interpretation-section">
                      <span className="upload-interpretation-title">What was measured</span>
                      <p className="upload-interpretation-p">
                        Measured pixels inside the rectangular boundary [Left: {regionValues.minX}, Bottom: {regionValues.minY}, Right: {regionValues.maxX}, Top: {regionValues.maxY}] in map system {selected.crs}.
                      </p>
                    </div>

                    <div className="upload-metrics-grid">
                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Usable Pixels in Area</span>
                        <span className="upload-metric-value">
                          {((Number(stats?.valid_pixel_fraction) || 0) * 100).toFixed(2)}%
                        </span>
                        <span className="upload-metric-sub">
                          {stats?.valid_pixel_count?.toLocaleString()} / {stats?.total_pixel_count?.toLocaleString()} pixels
                        </span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Average in Area</span>
                        <span className="upload-metric-value">{Number(stats?.mean).toFixed(4)}</span>
                        <span className="upload-metric-sub">Std dev: {Number(stats?.standard_deviation).toFixed(4)}</span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Area Value Range</span>
                        <span className="upload-metric-value">{Number(stats?.minimum).toFixed(2)} … {Number(stats?.maximum).toFixed(2)}</span>
                        <span className="upload-metric-sub">Median: {Number(stats?.median).toFixed(4)}</span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Estimated Area</span>
                        <span className="upload-metric-value">
                          {stats?.analysed_area_km2 != null ? `${Number(stats?.analysed_area_km2).toFixed(3)} km²` : 'Not applicable'}
                        </span>
                        <span className="upload-metric-sub">Area inside rectangle</span>
                      </div>
                    </div>

                    <div className="upload-interpretation-section">
                      <span className="upload-interpretation-title">What the result means</span>
                      <p className="upload-interpretation-p">
                        Within this specific rectangular window, the average pixel reading is <strong>{Number(stats?.mean).toFixed(4)}</strong>, with {stats?.valid_pixel_count?.toLocaleString()} valid pixels analyzed.
                      </p>
                    </div>

                    <div className="upload-interpretation-section section-limitations">
                      <span className="upload-interpretation-title">Important limitations</span>
                      <p className="upload-interpretation-p">
                        Measurements apply strictly within the requested bounding box. Coordinates must accurately represent the area of interest in the image's coordinate reference system.
                      </p>
                    </div>

                    <details className="technical-details-toggle">
                      <summary><span>⚙ Technical Details & Metadata (Advanced)</span></summary>
                      <div className="technical-details-content">
                        <p><strong>Operation:</strong> <code>{selected.analysis.operation}</code></p>
                        <p><strong>Region CRS:</strong> {selected.analysis.region.crs}</p>
                        <p><strong>Coordinate Convention:</strong> {selected.analysis.region.coordinate_convention}</p>
                        <p><strong>Area Note:</strong> {selected.analysis.evidence.area_note}</p>
                      </div>
                    </details>
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: Identify Land Cover (Form & Result or Unsupported Guidance) */}
            {activeAction === 'landcover' && selected.rawFile && (
              <div className="upload-tab-panel" role="tabpanel">
                {!canClassify ? (
                  <div className="upload-unsupported-notice" role="alert">
                    <h4>Land-Cover Classification Unavailable for this Image</h4>
                    <p style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                      This image contains only {bandCount} band(s). Land-cover classification requires five compatible spectral bands: Blue, Green, Red, Near Infrared and Shortwave Infrared.
                    </p>
                    <p>
                      SatQuery AI uses a multispectral EuroSAT AI model trained on specific satellite wavelengths. Single-band or standard 3-band RGB imagery does not provide the required optical channels. SatQuery AI never invents or fabricates missing spectral data.
                    </p>
                    <p style={{ marginTop: 8 }}>
                      You can still use <strong>Understand image values</strong> or <strong>Analyze a specific area</strong> to inspect this file's genuine pixel measurements.
                    </p>
                  </div>
                ) : (
                  <form className="upload-region-form" onSubmit={handleLandCoverAnalysis}>
                    <div className="upload-section-intro">
                      <h3>Identify Land Cover (EuroSAT AI Model)</h3>
                      <p>
                        Map five sensor channel numbers in your image to the required EuroSAT spectral wavelengths. Values must represent surface reflectance.
                        <InfoTooltip term="bands" />
                      </p>
                    </div>

                    <div className="upload-region-fields land-cover-band-fields">
                      {LAND_COVER_BANDS.map((band) => (
                        <label key={band}>
                          <span>
                            {band === 'B02' ? 'Blue (B02)' : band === 'B03' ? 'Green (B03)' : band === 'B04' ? 'Red (B04)' : band === 'B08' ? 'Near-Infrared (B08)' : 'Shortwave-IR (B11)'}
                            <span className="band-channel-hint"> (Channel 1–{bandCount})</span>
                          </span>
                          <input
                            type="number"
                            min="1"
                            max={bandCount}
                            step="1"
                            required
                            placeholder={`1..${bandCount}`}
                            value={landCoverMapping[band]}
                            onChange={(event) => setLandCoverMapping((prev) => ({ ...prev, [band]: event.target.value }))}
                          />
                        </label>
                      ))}
                    </div>

                    <div className="upload-form-actions">
                      <button className="upload-primary-btn" type="submit" disabled={classifyingLandCover}>
                        {classifyingLandCover ? 'Classifying image terrain…' : 'Classify image terrain'}
                      </button>
                    </div>

                    {landCoverError && (
                      <p className="upload-form-error" role="alert">
                        {landCoverErrorKind === 'unsupported' ? 'Unsupported input: ' : landCoverErrorKind === 'validation' ? 'Validation error: ' : 'Server error: '}
                        {landCoverError} {t('upload.failedHint')}
                      </p>
                    )}
                  </form>
                )}

                {landCoverResult && landCoverFileIndex === selectedIdxEffective && (
                  <div className="upload-interpretation-card" style={{ marginTop: 16 }} role="status">
                    <div className="upload-interpretation-header">
                      <h4>AI Land-Cover Classification Summary</h4>
                      <span className="upload-result-tag">EuroSAT ResNet-18</span>
                    </div>

                    <div className="upload-interpretation-section">
                      <span className="upload-interpretation-title">What was measured</span>
                      <p className="upload-interpretation-p">
                        Analyzed {landCoverResult.metrics.classified_pixel_count.toLocaleString()} pixels across {landCoverResult.metrics.n_tiles_classified} tiles (64×64 pixels each) using your mapped spectral channels.
                      </p>
                    </div>

                    <div className="upload-metrics-grid">
                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Dominant Terrain</span>
                        <span className="upload-metric-value" style={{ color: '#16a34a' }}>
                          {landCoverResult.metrics.dominant_class}
                        </span>
                        <span className="upload-metric-sub">Most common detected class</span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Model Softmax Confidence</span>
                        <span className="upload-metric-value">
                          {(landCoverResult.confidence.mean_model_confidence * 100).toFixed(1)}%
                        </span>
                        <span className="upload-metric-sub">Mean tile prediction score</span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Classified Area</span>
                        <span className="upload-metric-value">
                          {(landCoverResult.metrics.classified_fraction * 100).toFixed(1)}%
                        </span>
                        <span className="upload-metric-sub">{landCoverResult.metrics.n_tiles_classified} tiles classified</span>
                      </div>

                      <div className="upload-metric-card">
                        <span className="upload-metric-label">Skipped Tiles</span>
                        <span className="upload-metric-value">
                          {landCoverResult.metrics.n_tiles_skipped}
                        </span>
                        <span className="upload-metric-sub">Due to missing/nodata pixels</span>
                      </div>
                    </div>

                    <div className="upload-interpretation-section">
                      <span className="upload-interpretation-title">What the result means</span>
                      <p className="upload-interpretation-p">
                        The AI model identified <strong>{landCoverResult.metrics.dominant_class}</strong> as the most prominent land type in this scene. The average prediction score across tiles was {(landCoverResult.confidence.mean_model_confidence * 100).toFixed(1)}%.
                      </p>
                      <h5 style={{ margin: '10px 0 6px', fontSize: 13, fontWeight: 700 }}>Class Distribution Breakdown</h5>
                      <ul className="upload-distribution-list">
                        {Object.entries(landCoverResult.metrics.distribution.classes).map(([name, values]) => (
                          <li key={name}>
                            <strong>{name}:</strong> {values.pixels.toLocaleString()} px ({values.fraction === null ? 'unavailable' : `${(values.fraction * 100).toFixed(2)}%`})
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="upload-interpretation-section section-limitations">
                      <span className="upload-interpretation-title">Important limitations</span>
                      <p className="upload-interpretation-p">
                        This is tile-level classification (the AI classifies 64×64 pixel patches rather than individual ground points). Prediction confidence reflects the model&apos;s internal softmax score, not ground-truth verified accuracy. It does not perform visual question answering, captioning, or text grounding.
                      </p>
                    </div>

                    <details className="technical-details-toggle">
                      <summary><span>⚙ Technical Details & Model Metadata (Advanced)</span></summary>
                      <div className="technical-details-content">
                        <p><strong>Architecture:</strong> {landCoverResult.model.architecture || 'ResNet18'}</p>
                        <p><strong>Training Dataset:</strong> {landCoverResult.model.trained_on || 'EuroSAT multispectral'}</p>
                        <p><strong>Radiometry Requirement:</strong> {landCoverResult.evidence.radiometry}</p>
                        <p><strong>Operation Code:</strong> <code>{landCoverResult.operation}</code></p>
                      </div>
                    </details>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <div className="upload-action-row">
          <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13.5 }}>
            <strong>Next steps:</strong> Select an analyzed file above to review full-image measurements, query a specific area, or classify land cover. To compare two separate image dates, use the comparison tool below.
          </p>
        </div>
      </div>

      {/* 5. Collapsed Advanced Section: Compare Two Dated Images */}
      <details className="upload-advanced-section">
        <summary className="upload-advanced-summary">
          <div className="upload-advanced-summary-text">
            <span className="advanced-badge">Advanced</span>
            <span className="advanced-title">Compare two dated images (Raw Pixel Difference)</span>
            <span className="advanced-subtext">Measure how raw pixel values changed between two dates by subtracting older image pixels from newer image pixels.</span>
          </div>
          <span className="advanced-chevron" aria-hidden="true">▾</span>
        </summary>

        <div className="upload-advanced-content">
          <form className="upload-change-form" onSubmit={handleChangeAnalysis}>
            <div className="upload-section-intro">
              <h3>Direct Pixel Change (Newer − Older)</h3>
              <p>
                Calculates direct pixel differences between two dated GeoTIFFs. Older pixel values are subtracted from newer pixel values (`After − Before`) at every matching location.
                <InfoTooltip term="diff" />
              </p>
              <p style={{ marginTop: 4, color: 'var(--muted)', fontSize: 12.5 }}>
                <strong>Requirement:</strong> Both images must cover the exact same spatial grid, dimensions, and map projection (CRS). This measures raw numbers; it does not automatically establish semantic land-cover change or environmental significance.
              </p>
            </div>

            <div className="compare-sections">
              <fieldset className="compare-raster-group">
                <legend>Earlier / Before Image</legend>
                <div className="upload-field">
                  <span>GeoTIFF image file</span>
                  <div className="custom-file-picker">
                    <label className="custom-file-btn">
                      Choose file
                      <input
                        type="file"
                        accept=".tif,.tiff"
                        required
                        onChange={(event) => setBeforeFile(event.target.files?.[0] ?? null)}
                      />
                    </label>
                    <span className="custom-file-name" title={beforeFile?.name || 'No file chosen'}>
                      {beforeFile ? beforeFile.name : 'No file chosen'}
                    </span>
                  </div>
                </div>

                <div className="compare-raster-meta">
                  <label className="upload-field">
                    <span>Acquisition Date</span>
                    <input
                      type="date"
                      required
                      value={beforeDate}
                      onChange={(event) => setBeforeDate(event.target.value)}
                    />
                  </label>
                  <label className="upload-field">
                    <span>
                      Band number
                      <InfoTooltip title="Band Number" content="1-based channel index in the file (e.g. 1 for Band 1)." />
                    </span>
                    <input
                      type="number"
                      min="1"
                      required
                      value={beforeBand}
                      onChange={(event) => setBeforeBand(event.target.value)}
                    />
                  </label>
                </div>
              </fieldset>

              <fieldset className="compare-raster-group">
                <legend>Later / After Image</legend>
                <div className="upload-field">
                  <span>GeoTIFF image file</span>
                  <div className="custom-file-picker">
                    <label className="custom-file-btn">
                      Choose file
                      <input
                        type="file"
                        accept=".tif,.tiff"
                        required
                        onChange={(event) => setAfterFile(event.target.files?.[0] ?? null)}
                      />
                    </label>
                    <span className="custom-file-name" title={afterFile?.name || 'No file chosen'}>
                      {afterFile ? afterFile.name : 'No file chosen'}
                    </span>
                  </div>
                </div>

                <div className="compare-raster-meta">
                  <label className="upload-field">
                    <span>Acquisition Date</span>
                    <input
                      type="date"
                      required
                      value={afterDate}
                      onChange={(event) => setAfterDate(event.target.value)}
                    />
                  </label>
                  <label className="upload-field">
                    <span>
                      Band number
                      <InfoTooltip title="Band Number" content="1-based channel index in the file (e.g. 1 for Band 1)." />
                    </span>
                    <input
                      type="number"
                      min="1"
                      required
                      value={afterBand}
                      onChange={(event) => setAfterBand(event.target.value)}
                    />
                  </label>
                </div>
              </fieldset>
            </div>

            <div className="upload-form-actions">
              <button
                className="upload-primary-btn"
                type="submit"
                disabled={comparing || !beforeFile || !afterFile}
              >
                {comparing ? 'Comparing images…' : 'Compare images'}
              </button>
            </div>

            {changeError && (
              <p className="upload-form-error" role="alert">
                {changeError} {t('upload.failedHint')}
              </p>
            )}

            {changeResult && (
              <div className="upload-interpretation-card" style={{ marginTop: 16 }} role="status">
                <div className="upload-interpretation-header">
                  <h4>Two-Date Raw Pixel Difference Summary</h4>
                  <span className="upload-result-tag">Difference Analysis</span>
                </div>

                <div className="upload-interpretation-section">
                  <span className="upload-interpretation-title">What was measured</span>
                  <p className="upload-interpretation-p">
                    Subtracted pixel values of `{changeResult.sources[0]?.filename || 'before.tif'}` ({changeResult.before_date}) from `{changeResult.sources[1]?.filename || 'after.tif'}` ({changeResult.after_date}) across matching pixels.
                  </p>
                </div>

                <div className="upload-metrics-grid">
                  <div className="upload-metric-card">
                    <span className="upload-metric-label">Overlapping Usable Pixels</span>
                    <span className="upload-metric-value">
                      {(changeResult.evidence.valid_pixel_fraction * 100).toFixed(2)}%
                    </span>
                    <span className="upload-metric-sub">
                      {changeResult.metrics.common_valid_pixel_count.toLocaleString()} / {changeResult.metrics.total_pixel_count.toLocaleString()} pixels
                    </span>
                  </div>

                  <div className="upload-metric-card">
                    <span className="upload-metric-label">Average Pixel Change</span>
                    <span className="upload-metric-value">
                      {changeResult.metrics.difference_mean.toFixed(4)}
                    </span>
                    <span className="upload-metric-sub">
                      Direction: {changeResult.description.direction}
                    </span>
                  </div>

                  <div className="upload-metric-card">
                    <span className="upload-metric-label">Typical (Median) Change</span>
                    <span className="upload-metric-value">
                      {changeResult.description.median_difference.toFixed(4)}
                    </span>
                    <span className="upload-metric-sub">
                      Mean absolute change: {changeResult.metrics.absolute_difference_mean.toFixed(4)}
                    </span>
                  </div>

                  <div className="upload-metric-card">
                    <span className="upload-metric-label">Extreme Change Range</span>
                    <span className="upload-metric-value">
                      {changeResult.metrics.difference_minimum.toFixed(2)} … {changeResult.metrics.difference_maximum.toFixed(2)}
                    </span>
                    <span className="upload-metric-sub">Max difference spread</span>
                  </div>
                </div>

                <div className="upload-interpretation-section">
                  <span className="upload-interpretation-title">What the result means</span>
                  <p className="upload-interpretation-p">
                    {changeResult.description.text} Across {changeResult.metrics.common_valid_pixel_count.toLocaleString()} overlapping pixels, the average difference is <strong>{changeResult.metrics.difference_mean.toFixed(6)}</strong>.
                  </p>
                </div>

                <div className="upload-interpretation-section section-limitations">
                  <span className="upload-interpretation-title">Important limitations</span>
                  <p className="upload-interpretation-p">
                    This is a direct mathematical subtraction of raw image values (`After − Before`). A change in raw numbers does NOT automatically establish semantic land-cover change, deforestation, or environmental significance. Both images must be radiometrically calibrated to support environmental claims.
                  </p>
                </div>

                <details className="technical-details-toggle">
                  <summary><span>⚙ Technical Details & Alignment Check (Advanced)</span></summary>
                  <div className="technical-details-content">
                    <p><strong>Formula:</strong> <code>{changeResult.evidence.formula}</code></p>
                    <p><strong>Alignment Status:</strong> CRS equivalent: {String(changeResult.alignment.crs_equivalent)}; Dimensions match: {String(changeResult.alignment.dimensions_identical)}; Transform match: {String(changeResult.alignment.affine_transform_equivalent)}</p>
                    <p><strong>Resampling & Reprojection:</strong> none</p>
                    {changeResult.description.source_units && (
                      <p><strong>Source Units:</strong> {changeResult.description.source_units}</p>
                    )}
                    <p><strong>Operation Code:</strong> <code>{changeResult.operation}</code></p>
                  </div>
                </details>
              </div>
            )}
          </form>
        </div>
      </details>
    </div>
  )
}
