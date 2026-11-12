import React from 'react'

interface LogoMarkProps {
  size?: number
  className?: string
  /** Adds the rounded badge background (for standalone/app-icon usage). */
  badge?: boolean
  title?: string
}

/**
 * SatQuery AI brand mark: an orbital ring with a satellite riding it around a
 * target reticle — a query locked onto a point on Earth.
 */
export const LogoMark: React.FC<LogoMarkProps> = ({ size = 34, className, badge = false, title }) => (
  <svg
    viewBox="0 0 64 64"
    width={size}
    height={size}
    fill="none"
    className={className}
    role={title ? 'img' : 'presentation'}
    aria-hidden={title ? undefined : true}
  >
    {title && <title>{title}</title>}
    <defs>
      <linearGradient id="sqOrbit" x1="8" y1="16" x2="56" y2="48" gradientUnits="userSpaceOnUse">
        <stop stopColor="#568bff" />
        <stop offset="1" stopColor="#35d5f2" />
      </linearGradient>
      <radialGradient id="sqGlow" cx="32" cy="32" r="27" gradientUnits="userSpaceOnUse">
        <stop stopColor="#35d5f2" stopOpacity="0.3" />
        <stop offset="1" stopColor="#35d5f2" stopOpacity="0" />
      </radialGradient>
      <linearGradient id="sqBadge" x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
        <stop stopColor="#12233f" />
        <stop offset="1" stopColor="#070e1b" />
      </linearGradient>
    </defs>
    {badge && (
      <>
        <rect x="2" y="2" width="60" height="60" rx="15" fill="url(#sqBadge)" />
        <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="14.25" stroke="#35d5f2" strokeOpacity="0.28" strokeWidth="1.5" />
      </>
    )}
    <circle cx="32" cy="32" r="26" fill="url(#sqGlow)" />
    <path d="M15.5 24.7a20 20 0 0 1 33 0" stroke="#35d5f2" strokeOpacity="0.32" strokeWidth="2" strokeLinecap="round" />
    <g transform="rotate(-26 32 32)">
      <ellipse cx="32" cy="32" rx="21" ry="8.6" stroke="url(#sqOrbit)" strokeWidth="2.2" />
      <g transform="translate(17.2 25.9) rotate(-22.3)">
        <rect x="-2.6" y="-1.7" width="5.2" height="3.4" rx="1" fill="#e8eef5" />
        <rect x="-5.5" y="-1.05" width="2.2" height="2.1" rx="0.45" fill="#35d5f2" />
        <rect x="3.3" y="-1.05" width="2.2" height="2.1" rx="0.45" fill="#35d5f2" />
      </g>
    </g>
    <circle cx="32" cy="32" r="6.6" stroke="#35d5f2" strokeWidth="2.2" />
    <path d="M32 20.6v3M32 40.4v3M20.6 32h3M40.4 32h3" stroke="#e8eef5" strokeWidth="2" strokeLinecap="round" />
    <circle cx="32" cy="32" r="4.4" fill="#35d5f2" fillOpacity="0.22" />
    <circle cx="32" cy="32" r="2.2" fill="#35d5f2" />
  </svg>
)

interface LogoLockupProps {
  height?: number
  className?: string
}

/** Wordmark lockup: mark + "SatQuery AI" set in the display face. */
export const LogoLockup: React.FC<LogoLockupProps> = ({ height = 30, className }) => (
  <span className={`logo-lockup ${className ?? ''}`} style={{ height }}>
    <LogoMark size={height} />
    <span className="logo-wordmark">
      SatQuery <em>AI</em>
    </span>
  </span>
)
