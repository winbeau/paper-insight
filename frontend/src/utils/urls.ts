// The desktop app serves the UI and the API from one origin: the API lives under /api.
const rawApiBase = import.meta.env.VITE_API_BASE_URL || '/api'
export const apiBase = rawApiBase.endsWith('/') ? rawApiBase.slice(0, -1) : rawApiBase

export function resolveApiUrl(path?: string | null): string | null {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path
  if (path.startsWith(apiBase)) return path
  if (path.startsWith('/')) return `${apiBase}${path}`
  return `${apiBase}/${path}`
}
