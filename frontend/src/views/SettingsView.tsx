import React, { useEffect, useState } from 'react'
import { API_BASE } from '../api/client'
import { QUERY_LANGUAGE_SUPPORT, UI_LANGUAGES, useLanguage, type UiLanguage } from '../i18n'

type BackendConnectivity = 'checking' | 'connected' | 'unavailable'

function sanitizeConnectivityError(error: unknown): string {
  if (error instanceof TypeError) return 'Could not reach the configured backend. Check that the server is running and the API URL is correct.'
  if (error instanceof Error && error.message && !/token|key|secret|password|credential|authorization/i.test(error.message)) {
    return 'Backend health check failed. Check server availability and configuration.'
  }
  return 'Backend health check failed. Check server availability and configuration.'
}

export const SettingsView: React.FC = () => {
  const { t, lang, setLang } = useLanguage()
  const [backendHealth, setBackendHealth] = useState<BackendConnectivity>('checking')
  const [healthDetail, setHealthDetail] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setBackendHealth('checking')
    setHealthDetail(null)
    void fetch(`${API_BASE}/health`, { method: 'GET' })
      .then((res) => {
        if (cancelled) return
        if (res.ok) {
          setBackendHealth('connected')
          return
        }
        setBackendHealth('unavailable')
        setHealthDetail(`Health endpoint returned HTTP ${res.status}.`)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setBackendHealth('unavailable')
        setHealthDetail(sanitizeConnectivityError(error))
      })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="settings-view-container">
      <div className="settings-header">
        <h2>{t('settings.title')}</h2>
        <p>{t('settings.subtitle')}</p>
      </div>

      <div className="settings-grid">
        <div className="settings-card">
          <div className="card-header-row">
            <h3>{t('settings.language')}</h3>
          </div>
          <div className="settings-field-group">
            <p className="setting-label" style={{ marginBottom: 8 }}>{t('settings.languageHelp')}</p>
            <div className="setting-row" style={{ alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
              {UI_LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  className={`filter-btn ${lang === l.code ? 'active' : ''}`}
                  onClick={() => setLang(l.code as UiLanguage)}
                  aria-pressed={lang === l.code}
                >
                  {l.native} ({l.label}){QUERY_LANGUAGE_SUPPORT[l.code] === 'ui_only' ? ' — UI' : ''}
                </button>
              ))}
            </div>
            <p className="setting-value" style={{ marginTop: 8, fontSize: 13, color: 'var(--muted)' }}>
              {QUERY_LANGUAGE_SUPPORT[lang] === 'ui_only'
                ? t('query.backendLangNoteTe')
                : 'Question processing in the current backend supports English and Hindi where configured.'}
            </p>
          </div>
        </div>

        {/* Backend & Core Health */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>{t('settings.backend')}</h3>
            <span className={`status-pill status-${backendHealth === 'connected' ? 'valid' : 'invalid'}`}>
              {backendHealth === 'connected' ? t('settings.connected') : backendHealth === 'checking' ? t('settings.checking') : t('settings.unavailable')}
            </span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">API Endpoint (configured)</span>
              <span className="setting-value code-font">{API_BASE}</span>
            </div>
            {backendHealth === 'unavailable' && healthDetail && (
              <div className="setting-row">
                <span className="setting-label">Connectivity (tested now)</span>
                <span className="setting-value">{healthDetail}</span>
              </div>
            )}
            <div className="setting-row">
              <span className="setting-label">FastAPI Architecture</span>
              <span className="setting-value">Pydantic v2 + BackgroundTasks (Local SQLite)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Test Suite Verification</span>
              <span className="setting-value">Run `python -m pytest -q` from backend/</span>
            </div>
          </div>
        </div>

        {/* Satellite Data Provider */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>Satellite Data Provider</h3>
            <span className="status-pill status-invalid">{t('settings.partial')}</span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">Primary STAC Provider</span>
              <span className="setting-value">Element84 Earth Search (Sentinel-2 L2A BOA) — requires outbound internet access</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Provider connectivity</span>
              <span className="setting-value">Not verified in Settings. Run an analysis in Map Mode to confirm live access.</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Fallback STAC Provider</span>
              <span className="setting-value">Not configured</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">SAR Provider</span>
              <span className="setting-value">Sentinel-1 RTC analysis and Sentinel-1 + Sentinel-2 fusion are implemented; live availability depends on provider/network access.</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">COG Windowed Reads</span>
              <span className="setting-value text-green">Enabled (AOI-clipped only)</span>
            </div>
          </div>
        </div>

        {/* Models & Remote Sensing VLM */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>AI & Vision-Language Models</h3>
            <span className="status-pill status-invalid">{t('settings.partial')}</span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">Land-Cover Classifier</span>
              <span className="setting-value">EuroSAT ResNet18 (BoA Reflectance)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Inference Mode</span>
              <span className="setting-value">High-speed Pure NumPy (Zero CUDA required)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Reported EuroSAT test metrics</span>
              <span className="setting-value">Checkpoint-reported dataset results, not accuracy estimates for this AOI. See Benchmarks for the test split and perturbation scope; accuracy on Indian scenes is unmeasured.</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">VLM Explainer Provider</span>
              <span className="setting-value">Grounded answers are text-only. Sentinel-2 captioning uses local BLIP and requires its model/runtime; image VQA and visual grounding are unavailable.</span>
            </div>
          </div>
        </div>

        {/* Verifier & Grounding */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>Deterministic Verifier</h3>
            <span className="status-pill status-valid">{t('settings.enforcing')}</span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">Grounding Validator</span>
              <span className="setting-value text-green">Strict (Numerical claim cross-check)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Confidence Scoring</span>
              <span className="setting-value">Deterministic Multi-Factor (Pixels, Cloud, Noise)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Statistical Testing</span>
              <span className="setting-value">Mann-Kendall + Sen&apos;s Slope (Spatial Honest)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
