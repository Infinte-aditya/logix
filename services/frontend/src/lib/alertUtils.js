const SEVERITY_RANK = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 }

export function severityRank(s) {
  return SEVERITY_RANK[s] || 0
}

export function filterAlerts(alerts, { severity, search, unackOnly }) {
  return alerts.filter((a) => {
    if (severity && severity !== 'ALL' && a.severity !== severity) return false
    if (search && !a.message.toLowerCase().includes(search.toLowerCase())) return false
    if (unackOnly && localStorage.getItem(`ack:${a.id}`)) return false
    return true
  })
}

export function alertsToCsv(alerts) {
  const header = 'id,timestamp,severity,error_rate,baseline_mean,baseline_std,z_score,window_seconds,message'
  const rows = alerts.map((a) =>
    [
      a.id,
      a.timestamp,
      a.severity,
      a.error_rate,
      a.baseline_mean,
      a.baseline_std,
      a.z_score,
      a.window_seconds,
      `"${(a.message || '').replace(/"/g, '""')}"`,
    ].join(','),
  )
  return [header, ...rows].join('\n')
}

export function downloadCsv(alerts, filename = 'alerts.csv') {
  const blob = new Blob([alertsToCsv(alerts)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function timeAgo(ts, now) {
  const sec = Math.floor((now - new Date(ts + (ts.endsWith('Z') ? '' : 'Z')).getTime()) / 1000)
  if (sec < 0) return 'just now'
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  return `${min}m ago`
}

export function unacknowledgedCount(alerts) {
  return alerts.filter((a) => !localStorage.getItem(`ack:${a.id}`)).length
}