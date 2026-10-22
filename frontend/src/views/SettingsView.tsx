import React, { useEffect, useState } from 'react'

export const SettingsView: React.FC = () => {
  const [backendHealth, setBackendHealth] = useState<'checking' | 'healthy' | 'unreachable'>('checking')

  useEffect(() => {
    fetch('http://127.0.0.1:8000/health')
      .then((res) => (res.ok ? setBackendHealth('healthy') : setBackendHealth('unreachable')))
      .catch(() => setBackendHealth('unreachable'))
  }, [])

  return (
    <div className="settings-view-container">
      <div className="settings-header">
        <h2>System Settings & Service Status</h2>
        <p>Integrations, satellite data providers, model parameters, and platform verification status.</p>
      </div>

      <div className="settings-grid">
        {/* Backend & Core Health */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>Backend Engine</h3>
            <span className={`status-pill status-${backendHealth === 'healthy' ? 'valid' : 'invalid'}`}>
              {backendHealth === 'healthy' ? 'Connected' : backendHealth === 'checking' ? 'Checking…' : 'Unreachable'}
            </span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">API Endpoint</span>
              <span className="setting-value code-font">http://127.0.0.1:8000</span>
            </div>
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
            <span className="status-pill status-valid">Active</span>
          </div>
          <div className="settings-field-group">
            <div className="setting-row">
              <span className="setting-label">Primary STAC Provider</span>
              <span className="setting-value">Element84 Earth Search (Sentinel-2 L2A BOA)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">Fallback STAC Provider</span>
              <span className="setting-value">Microsoft Planetary Computer</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">SAR Provider</span>
              <span className="setting-value">Not integrated</span>
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
            <span className="status-pill status-invalid">Partial</span>
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
              <span className="setting-label">Reported EuroSAT Accuracy</span>
              <span className="setting-value">98.74% (Clean), 96.0% (Robust under noise)</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">VLM Explainer Provider</span>
              <span className="setting-value">Text-only explanation; no image VQA/captioning VLM</span>
            </div>
          </div>
        </div>

        {/* Verifier & Grounding */}
        <div className="settings-card">
          <div className="card-header-row">
            <h3>Deterministic Verifier</h3>
            <span className="status-pill status-valid">Enforcing</span>
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
