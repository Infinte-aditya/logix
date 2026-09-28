import { useEffect, useRef, useState } from 'react'
import './App.css'
import { buildWsUrl } from './lib/ws'
import { downloadCsv, filterAlerts, severityRank, timeAgo, unacknowledgedCount } from './lib/alertUtils'

const MAX_ALERTS = 100

function SummaryCards({ alerts, now }) {
  const total = alerts.length
  const bySeverity = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 }
  const last10min = alerts.filter((a) => now - new Date(a.timestamp).getTime() < 600000)
  const maxSev = last10min.reduce((m, a) => Math.max(m, severityRank(a.severity)), 0)
  const sevLabels = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
  const highestSev = sevLabels[maxSev] || '—'
  const lastAlert = alerts.length > 0 ? timeAgo(alerts[0].timestamp, now) : '—'
  alerts.forEach((a) => { bySeverity[a.severity] = (bySeverity[a.severity] || 0) + 1 })
  const cards = [
    { label: 'Total', value: total, color: '#9ca3af' },
    { label: 'LOW', value: bySeverity.LOW, color: '#60a5fa' },
    { label: 'MEDIUM', value: bySeverity.MEDIUM, color: '#fbbf24' },
    { label: 'HIGH', value: bySeverity.HIGH, color: '#fb923c' },
    { label: 'CRITICAL', value: bySeverity.CRITICAL, color: '#f87171' },
    { label: 'Peak (10m)', value: highestSev, color: '#a78bfa' },
    { label: 'Latest', value: lastAlert, color: '#9ca3af' },
  ]
  return (
    <div className="summary-cards">
      {cards.map((c) => (
        <div key={c.label} className="card" style={{ '--card-color': c.color }}>
          <span className="card-label">{c.label}</span>
          <span className="card-value">{c.value}</span>
        </div>
      ))}
    </div>
  )
}

function AlertChart({ alerts }) {
  const canvasRef = useRef(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || alerts.length === 0) return
    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.scale(dpr, dpr)
    const w = rect.width
    const h = rect.height
    const pad = { top: 10, right: 10, bottom: 20, left: 40 }
    const pW = w - pad.left - pad.right
    const pH = h - pad.top - pad.bottom
    ctx.clearRect(0, 0, w, h)
    if (alerts.length < 2) {
      ctx.fillStyle = '#9ca3af'
      ctx.font = '12px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('Need at least 2 alerts for chart', w / 2, h / 2)
      return
    }
    const reversed = [...alerts].reverse()
    const _times = reversed.map((a) => new Date(a.timestamp).getTime())
    const rateMin = 0
    const rateMax = Math.max(...reversed.map((a) => a.error_rate), 0.1)
    const rateRange = rateMax - rateMin || 0.1
    function x(i) { return pad.left + (i / (reversed.length - 1)) * pW }
    function yRate(v) { return pad.top + pH - ((v - rateMin) / rateRange) * pH }
    ctx.strokeStyle = '#4ade80'
    ctx.lineWidth = 1
    ctx.setLineDash([2, 2])
    const baselineY = yRate(reversed[0].baseline_mean || 0.02)
    ctx.beginPath(); ctx.moveTo(pad.left, baselineY); ctx.lineTo(w - pad.right, baselineY); ctx.stroke()
    ctx.setLineDash([])
    const stdUpper = yRate((reversed[0].baseline_mean || 0.02) + 2 * (reversed[0].baseline_std || 0.01))
    const stdLower = yRate(Math.max(0, (reversed[0].baseline_mean || 0.02) - 2 * (reversed[0].baseline_std || 0.01)))
    ctx.fillStyle = 'rgba(74, 222, 128, 0.08)'
    ctx.fillRect(pad.left, stdUpper, pW, stdLower - stdUpper)
    ctx.strokeStyle = '#f87171'
    ctx.lineWidth = 2
    ctx.beginPath()
    reversed.forEach((a, i) => { const v = yRate(a.error_rate); i === 0 ? ctx.moveTo(x(i), v) : ctx.lineTo(x(i), v) })
    ctx.stroke()
    ctx.fillStyle = '#f87171'
    reversed.forEach((a, i) => { ctx.beginPath(); ctx.arc(x(i), yRate(a.error_rate), 3, 0, Math.PI * 2); ctx.fill() })
    ctx.fillStyle = '#9ca3af'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText((rateMax * 100).toFixed(0) + '%', pad.left - 4, pad.top + 10)
    ctx.fillText('0%', pad.left - 4, h - pad.bottom + 4)
  }, [alerts])
  return (
    <div className="chart-container">
      <canvas ref={canvasRef} style={{ width: '100%', height: 160 }} />
    </div>
  )
}

function AlertDetailDrawer({ alert, onClose }) {
  if (!alert) return null
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span>Alert {alert.id.slice(0, 8)}</span>
          <button className="drawer-close" onClick={onClose}>x</button>
        </div>
        <div className="drawer-body">
          <table className="drawer-fields">
            <tbody>
              {Object.entries(alert).map(([k, v]) => (
                <tr key={k}>
                  <td className="field-key">{k}</td>
                  <td className="field-value">{typeof v === 'number' ? v.toFixed(4) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="drawer-json">
            <div className="drawer-json-header">
              <span>Raw JSON</span>
              <button className="btn-sm" onClick={() => { navigator.clipboard.writeText(JSON.stringify(alert, null, 2)) }}>Copy</button>
            </div>
            <pre>{JSON.stringify(alert, null, 2)}</pre>
          </div>
        </div>
      </div>
    </div>
  )
}

function Controls({ onFilterChange, onClear, onPause, paused }) {
  const [severity, setSeverity] = useState('ALL')
  const [search, setSearch] = useState('')
  const [unackOnly, setUnackOnly] = useState(false)
  useEffect(() => { onFilterChange({ severity, search, unackOnly }) }, [severity, search, unackOnly, onFilterChange])
  return (
    <div className="controls">
      <button className="btn-sm" onClick={onPause}>{paused ? 'Resume' : 'Pause'}</button>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="select-sm">
        <option value="ALL">All Severities</option>
        <option value="LOW">LOW</option>
        <option value="MEDIUM">MEDIUM</option>
        <option value="HIGH">HIGH</option>
        <option value="CRITICAL">CRITICAL</option>
      </select>
      <input type="text" placeholder="Search message..." value={search} onChange={(e) => setSearch(e.target.value)} className="input-sm" />
      <label className="ack-toggle">
        <input type="checkbox" checked={unackOnly} onChange={(e) => setUnackOnly(e.target.checked)} />
        {' '}Unacknowledged only
      </label>
      <button className="btn-sm" onClick={onClear}>Clear</button>
    </div>
  )
}

function AlertBar({ pct, severity }) {
  const colors = { LOW: '#60a5fa', MEDIUM: '#fbbf24', HIGH: '#fb923c', CRITICAL: '#f87171' }
  return (
    <div className="bar-track">
      <div className="bar-fill" style={{ width: `${Math.min(pct * 100, 100)}%`, background: colors[severity] || '#60a5fa' }} />
    </div>
  )
}

function LogsPanel() {
  const [lines, setLines] = useState([])
  const ref = useRef()
  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const r = await fetch('/logs?lines=30')
        const d = await r.json()
        if (d.lines) setLines(d.lines)
      } catch {}
    }
    fetchLogs()
    const id = setInterval(fetchLogs, 2000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [lines])
  return (
    <pre className="logs" ref={ref}>
      {lines.map((l, i) => (
        <span key={i} className={l.includes('ERROR') ? 'log-error' : l.includes('WARN') ? 'log-warn' : ''}>{l}</span>
      ))}
    </pre>
  )
}

function SettingsPanel() {
  const [settings, setSettings] = useState(null)
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    fetch('/settings').then((r) => r.json()).then(setSettings).catch(() => setMsg('Failed to load settings'))
  }, [])
  const handleSave = async () => {
    setSaving(true)
    try {
      const r = await fetch('/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) })
      if (!r.ok) { const err = await r.json(); setMsg(`Error: ${err.detail || r.statusText}`) }
      else { setMsg('Saved') }
    } catch { setMsg('Failed to save') }
    setSaving(false)
  }
  const handleReset = async () => {
    try {
      const r = await fetch('/settings/reset', { method: 'POST' })
      if (r.ok) { const data = await r.json(); setSettings(data); setMsg('Reset to defaults') }
      else { setMsg('Reset failed') }
    } catch { setMsg('Reset failed') }
  }
  if (!settings) return <p className="empty">Loading settings...</p>
  return (
    <div className="settings-panel">
      <h2>Settings</h2>
      {Object.entries(settings).map(([k, v]) => (
        <div key={k} className="setting-row">
          <label>{k}</label>
          <input type={typeof v === 'number' ? 'number' : 'text'} value={v} onChange={(e) => setSettings({ ...settings, [k]: typeof v === 'number' ? Number(e.target.value) : e.target.value })} className="input-sm" />
        </div>
      ))}
      <div className="setting-actions">
        <button className="btn-sm" onClick={handleSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
        <button className="btn-sm" onClick={handleReset}>Reset to defaults</button>
      </div>
      {msg && <p className="setting-msg">{msg}</p>}
    </div>
  )
}

export default function App() {
  const [alerts, setAlerts] = useState([])
  const [status, setStatus] = useState('connecting')
  const [tab, setTab] = useState('alerts')
  const [now, setNow] = useState(Date.now())
  const [paused, setPaused] = useState(false)
  const [filters, setFilters] = useState({ severity: 'ALL', search: '', unackOnly: false })
  const [detailAlert, setDetailAlert] = useState(null)
  const [soundEnabled, setSoundEnabled] = useState(false)
  const [darkMode, setDarkMode] = useState(true)
  const [lastMsgTime, setLastMsgTime] = useState(null)
  const retries = useRef(0)
  const bufRef = useRef([])
  const highlightedRef = useRef(new Set())

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const unack = unacknowledgedCount(alerts)
    document.title = unack > 0 ? `(${unack}) logix` : 'logix'
  }, [alerts])

  useEffect(() => {
    if (!soundEnabled) return
    const recent = alerts.filter((a) => highlightedRef.current.has(a.id) && (a.severity === 'HIGH' || a.severity === 'CRITICAL'))
    if (recent.length > 0) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)()
        const osc = ctx.createOscillator()
        osc.frequency.value = 880
        osc.type = 'sine'
        const gain = ctx.createGain()
        gain.gain.value = 0.1
        osc.connect(gain); gain.connect(ctx.destination)
        osc.start(); setTimeout(() => { osc.stop(); ctx.close() }, 200)
      } catch {}
    }
  }, [alerts, soundEnabled])

  useEffect(() => {
    let socket; let closed = false
    const connect = () => {
      socket = new WebSocket(buildWsUrl())
      socket.onopen = () => { retries.current = 0; setStatus('live') }
      socket.onmessage = (event) => {
        setLastMsgTime(Date.now())
        try {
          const alert = JSON.parse(event.data)
          if (alert && alert.id) {
            if (paused) {
              bufRef.current.push(alert)
            } else {
              highlightedRef.current.add(alert.id)
              setAlerts((prev) => [alert, ...prev].slice(0, MAX_ALERTS))
              setTimeout(() => highlightedRef.current.delete(alert.id), 2000)
            }
          }
        } catch {}
      }
      socket.onclose = () => {
        if (closed) return
        setStatus('reconnecting')
        const delay = Math.min(1000 * 2 ** retries.current, 10000)
        retries.current += 1
        setTimeout(connect, delay)
      }
      socket.onerror = () => socket.close()
    }
    connect()
    return () => { closed = true; socket.close() }
  }, [paused])

  useEffect(() => {
    if (!paused && bufRef.current.length > 0) {
      const batch = bufRef.current.splice(0)
      setAlerts((prev) => [...batch, ...prev].slice(0, MAX_ALERTS))
    }
  }, [paused])

  const handleClear = () => {
    setAlerts([])
    highlightedRef.current.clear()
    bufRef.current = []
  }

  const visibleAlerts = filterAlerts(alerts, filters)

  return (
    <main>
      <header>
        <h1>logix</h1>
        <nav className="tabs">
          <button className={`tab ${tab === 'alerts' ? 'active' : ''}`} onClick={() => setTab('alerts')}>Alerts</button>
          <button className={`tab ${tab === 'logs' ? 'active' : ''}`} onClick={() => setTab('logs')}>Live Logs</button>
          <button className={`tab ${tab === 'settings' ? 'active' : ''}`} onClick={() => setTab('settings')}>Settings</button>
        </nav>
        <div className="header-controls">
          <label className="sound-toggle" title="Alert sound (HIGH/CRITICAL)">
            <input type="checkbox" checked={soundEnabled} onChange={(e) => setSoundEnabled(e.target.checked)} />
          </label>
          <button className="theme-toggle" onClick={() => setDarkMode((d) => !d)} title="Toggle theme">
            {darkMode ? '☀' : '☾'}
          </button>
          <span className={`status ${status === 'live' ? 'up' : 'down'}`}>
            {status}{lastMsgTime ? ` · ${timeAgo(new Date(lastMsgTime).toISOString(), now)}` : ''}
          </span>
        </div>
      </header>
      {tab === 'alerts' ? (
        <>
          <SummaryCards alerts={alerts} now={now} />
          <AlertChart alerts={alerts} />
          <div className="toolbar">
            <Controls onFilterChange={setFilters} onClear={handleClear} onPause={() => setPaused((p) => !p)} paused={paused} />
            <button className="btn-sm" onClick={() => downloadCsv(visibleAlerts)} disabled={visibleAlerts.length === 0}>Export CSV</button>
            <span className="count">{visibleAlerts.length} of {alerts.length} alert{alerts.length === 1 ? '' : 's'}</span>
          </div>
          {alerts.length === 0 ? (
            <p className="empty">No alerts yet — waiting for the detector…</p>
          ) : visibleAlerts.length === 0 ? (
            <p className="empty">No alerts match the current filters.</p>
          ) : (
            <ul className="alerts">
              {visibleAlerts.map((alert) => {
                const pct = alert.error_rate
                const acked = !!localStorage.getItem(`ack:${alert.id}`)
                return (
                  <li key={alert.id} className={`alert ${String(alert.severity).toLowerCase()} ${highlightedRef.current.has(alert.id) ? 'highlight' : ''} ${acked ? 'acked' : ''}`} onClick={() => setDetailAlert(alert)}>
                    <div className="alert-head">
                      <span className="sev">{alert.severity}</span>
                      <span className="when">{timeAgo(alert.timestamp, now)}</span>
                    </div>
                    <AlertBar pct={pct} severity={alert.severity} />
                    <div className="alert-stats">
                      <span>{alert.window_seconds}s · {(pct * 100).toFixed(1)}% errors</span>
                      <span>z={Number(alert.z_score).toFixed(1)}</span>
                    </div>
                    <p className="msg">{alert.message}</p>
                    <div className="alert-actions">
                      <button className="btn-sm" onClick={(e) => { e.stopPropagation(); localStorage.setItem(`ack:${alert.id}`, '1'); setAlerts([...alerts]) }}>
                        {acked ? 'Acknowledged' : 'Acknowledge'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      ) : tab === 'logs' ? (
        <LogsPanel />
      ) : (
        <SettingsPanel />
      )}
      <AlertDetailDrawer alert={detailAlert} onClose={() => setDetailAlert(null)} />
    </main>
  )
}