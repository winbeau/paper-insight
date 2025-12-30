import axios from 'axios'
import type { Paper, Stats, AppSettings } from '../types/paper'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export async function fetchPapers(params?: {
  skip?: number
  limit?: number
  min_score?: number
  processed_only?: boolean
}): Promise<Paper[]> {
  const { data } = await api.get<Paper[]>('/papers', { params })
  return data
}

export async function fetchPaper(id: number): Promise<Paper> {
  const { data } = await api.get<Paper>(`/papers/${id}`)
  return data
}

export async function fetchStats(): Promise<Stats> {
  const { data } = await api.get<Stats>('/stats')
  return data
}

export async function triggerFetch(): Promise<{ message: string }> {
  const { data } = await api.post<{ message: string }>('/papers/fetch')
  return data
}

export async function processPaper(id: number): Promise<{ message: string }> {
  const { data } = await api.post<{ message: string }>(`/papers/${id}/process`)
  return data
}

export async function fetchSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>('/settings')
  return data
}

export async function updateSettings(settings: AppSettings): Promise<AppSettings> {
  const { data } = await api.put<AppSettings>('/settings', settings)
  return data
}
