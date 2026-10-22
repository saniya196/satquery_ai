import React from 'react'
import type { NavView } from './Sidebar'

interface AppHeaderProps {
  currentView: NavView
  activeJobId: string | null
  jobStatus?: string | null
}

const VIEW_TITLES: Record<NavView, { title: string; subtitle: string }> = {
  home: {
    title: 'Dashboard',
    subtitle: 'Analyze satellite imagery, ask questions in natural language, and get accurate insights',
  },
  map: {
    title: 'Map Mode — Draw & Ask',
    subtitle: 'Interactive geospatial selection and Sentinel-2 natural-language analysis',
  },
  multisensor: {
    title: 'Sentinel-2 Analytics & Sensor Status',
    subtitle: 'Sentinel-2 analysis; Sentinel-1 SAR fusion is not yet available',
  },
  change: {
    title: 'Change Detection & Hotspots',
    subtitle: '5-class temporal change categorization and spatial degradation cluster identification',
  },
  upload: {
    title: 'Upload Mode — GeoTIFF',
    subtitle: 'Single-band statistics, region statistics, and aligned raw-raster comparison',
  },
  history: {
    title: 'Analysis History',
    subtitle: 'Audit trail of past satellite queries, deterministic calculations, and verified evidence',
  },
  benchmarks: {
    title: 'Evaluation & Benchmarks',
    subtitle: 'Benchmark status; no external SatQuery evaluations are currently checked in',
  },
  settings: {
    title: 'System Settings',
    subtitle: 'Integrations, data providers, model availability, and platform configuration',
  },
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  currentView,
  activeJobId,
  jobStatus,
}) => {
  const info = VIEW_TITLES[currentView]

  return (
    <header className="app-topbar">
      <div className="topbar-title-block">
        <h1 className="topbar-page-title">{info.title}</h1>
        <span className="topbar-page-subtitle">{info.subtitle}</span>
      </div>

      <div className="topbar-actions-block">
        {activeJobId && (
          <div className="topbar-job-pill">
            <span className="live-pulse-dot" />
            <span className="job-pill-text">Job {activeJobId.slice(0, 8)}… ({jobStatus || 'processing'})</span>
          </div>
        )}

        <div className="topbar-badge provider-badge">
          <span className="badge-dot active-dot" />
          <span>Sentinel-2 L2A (STAC)</span>
        </div>

        <div className="topbar-badge crs-badge">
          <span>CRS: WGS 84</span>
        </div>
      </div>
    </header>
  )
}
