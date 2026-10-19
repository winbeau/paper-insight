import type { AppSettings, Provider } from '../types/paper'

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '[::1]']

/** Remote endpoints need an API key; local servers (Ollama, LM Studio) don't. */
export function providerNeedsKey(provider: Provider): boolean {
  if (provider.api_key) return false
  try {
    const host = new URL(provider.base_url).hostname
    return !LOCAL_HOSTS.includes(host) && !host.endsWith('.local')
  } catch {
    return true
  }
}

export type SetupProblem =
  | { kind: 'model' }
  | { kind: 'key'; provider: Provider }

/** What is missing before papers can be analyzed (mirrors the backend's check). */
export function analysisSetupProblem(settings: AppSettings | null): SetupProblem | null {
  if (!settings) return null
  const reasoning = settings.pipeline.reasoning
  const provider = settings.providers.find(p => p.id === reasoning.provider_id)
  if (!reasoning.model || !provider) return { kind: 'model' }
  if (providerNeedsKey(provider)) return { kind: 'key', provider }
  return null
}
