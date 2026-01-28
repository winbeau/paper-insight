const rawApiBase = import.meta.env.VITE_API_BASE_URL || '/paper-insight/api'
const apiBase = rawApiBase.endsWith('/') ? rawApiBase.slice(0, -1) : rawApiBase
const rawBase = import.meta.env.BASE_URL || '/'
const basePath = rawBase.endsWith('/') ? rawBase.slice(0, -1) : rawBase

export function resolveApiUrl(path?: string | null): string | null {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path
  if (path.startsWith(apiBase)) return path
  if (path.startsWith('/')) return `${apiBase}${path}`
  return `${apiBase}/${path}`
}

export function resolveStaticUrl(path?: string | null): string | null {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path
  if (path.startsWith(basePath)) return path
  if (path.startsWith('/')) return `${basePath}${path}`
  return `${basePath}/${path}`
}
