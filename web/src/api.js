import { needAuth, readToken } from './auth'

const BASE = '/api/v1'

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, item))
      return
    }
    search.append(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (readToken.value) {
    headers['X-Read-Token'] = readToken.value
  }

  const response = await fetch(`${BASE}${path}`, { ...options, headers })

  if (response.status === 401) {
    needAuth.value = true
    throw new Error('读取令牌无效，请重新输入令牌')
  }

  if (!response.ok) {
    let detail = `请求失败 (${response.status})`
    try {
      const body = await response.json()
      if (body && body.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch (error) {
      // 保持默认提示
    }
    throw new Error(detail)
  }
  if (response.status === 204) {
    return null
  }
  return response.json()
}

export const api = {
  overview: () => request('/stats/overview'),
  devices: (params) => request(`/devices${query(params)}`),
  device: (id) => request(`/devices/${id}`),
  updateDevice: (id, payload) =>
    request(`/devices/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteDevice: (id) => request(`/devices/${id}`, { method: 'DELETE' }),
  metrics: (id, keys, hours = 168) =>
    request(`/devices/${id}/metrics${query({ key: keys, hours })}`),
  alerts: (params) => request(`/alerts${query(params)}`),
  resolveAlert: (id, note) =>
    request(`/alerts/${id}/resolve`, { method: 'PATCH', body: JSON.stringify({ note }) }),
  exportCsv: async () => {
    // 导出走 fetch 而不是直接打开链接，这样能带上读取令牌
    const headers = readToken.value ? { 'X-Read-Token': readToken.value } : {}
    const response = await fetch(`${BASE}/devices/export/csv`, { headers })
    if (response.status === 401) {
      needAuth.value = true
      throw new Error('读取令牌无效，请重新输入令牌')
    }
    if (!response.ok) {
      throw new Error(`导出失败 (${response.status})`)
    }
    return response.blob()
  },
}

export function parseTime(value) {
  if (!value) return null
  // 服务端统一输出朴素 UTC 时间，这里补上 Z 再交给浏览器按本地时区显示
  const text = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatTime(value) {
  const date = parseTime(value)
  if (!date) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDay(value) {
  if (!value) return '-'
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export const levelMeta = {
  critical: { label: '严重', type: 'danger' },
  warning: { label: '警告', type: 'warning' },
  notice: { label: '注意', type: 'info' },
  info: { label: '提示', type: 'success' },
}

export function levelLabel(level) {
  return (levelMeta[level] || { label: level }).label
}
