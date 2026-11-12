import type { PolygonGeometry } from '../types/analysis'

export interface SavedAoi {
  id: string
  name: string
  geometry: PolygonGeometry
  createdAt: string
}

const STORAGE_KEY = 'satquery.savedAois.v1'

function isValidGeometry(value: unknown): value is PolygonGeometry {
  if (!value || typeof value !== 'object') return false
  const g = value as { type?: unknown; coordinates?: unknown }
  if (g.type !== 'Polygon' || !Array.isArray(g.coordinates) || g.coordinates.length < 1) return false
  const ring = g.coordinates[0]
  if (!Array.isArray(ring) || ring.length < 4) return false
  return ring.every((pt) => Array.isArray(pt) && pt.length >= 2 && Number.isFinite(pt[0]) && Number.isFinite(pt[1]))
}

export function loadSavedAois(): SavedAoi[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const out: SavedAoi[] = []
    for (const item of parsed) {
      if (!item || typeof item !== 'object') continue
      const rec = item as Record<string, unknown>
      const name = typeof rec.name === 'string' ? rec.name.trim() : ''
      if (!name || !isValidGeometry(rec.geometry)) continue
      out.push({
        id: typeof rec.id === 'string' && rec.id ? rec.id : crypto.randomUUID(),
        name,
        geometry: rec.geometry,
        createdAt: typeof rec.createdAt === 'string' ? rec.createdAt : new Date().toISOString(),
      })
    }
    return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  } catch {
    return []
  }
}

export function saveAoi(name: string, geometry: PolygonGeometry): SavedAoi[] {
  const trimmed = name.trim()
  if (!trimmed) throw new Error('Please enter a name for the saved area.')
  if (!isValidGeometry(geometry)) throw new Error('The selected area geometry is invalid and cannot be saved.')
  const items = loadSavedAois()
  const next: SavedAoi = { id: crypto.randomUUID(), name: trimmed, geometry, createdAt: new Date().toISOString() }
  const updated = [next, ...items.filter((i) => i.name.toLowerCase() !== trimmed.toLowerCase() || i.id === next.id)]
  localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
  return updated
}

export function deleteSavedAoi(id: string): SavedAoi[] {
  const updated = loadSavedAois().filter((i) => i.id !== id)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
  return updated
}

export function savedAoiStorageNote(): string {
  return 'Saved areas are stored in this browser on this device (local storage). They are not synced to your account or other devices.'
}