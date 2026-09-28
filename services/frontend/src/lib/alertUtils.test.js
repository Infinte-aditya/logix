import { describe, expect, it } from 'vitest'
import { alertsToCsv, filterAlerts, severityRank, timeAgo } from './alertUtils'

const alerts = [
  { id: '1', timestamp: '2026-09-28T12:00:00Z', severity: 'HIGH', error_rate: 0.3, baseline_mean: 0.02, baseline_std: 0.01, z_score: 28, window_seconds: 60, message: 'high rate' },
  { id: '2', timestamp: '2026-09-28T12:01:00Z', severity: 'LOW', error_rate: 0.1, baseline_mean: 0.02, baseline_std: 0.01, z_score: 8, window_seconds: 60, message: 'low rate' },
]

describe('severityRank', () => {
  it('returns correct ordering', () => {
    expect(severityRank('LOW')).toBe(1)
    expect(severityRank('MEDIUM')).toBe(2)
    expect(severityRank('HIGH')).toBe(3)
    expect(severityRank('CRITICAL')).toBe(4)
    expect(severityRank('UNKNOWN')).toBe(0)
  })
})

describe('filterAlerts', () => {
  it('filters by severity', () => {
    expect(filterAlerts(alerts, { severity: 'HIGH' })).toHaveLength(1)
  })
  it('filters by search', () => {
    expect(filterAlerts(alerts, { search: 'low' })).toHaveLength(1)
  })
  it('returns all when no filters', () => {
    expect(filterAlerts(alerts, {})).toHaveLength(2)
  })
})

describe('alertsToCsv', () => {
  it('produces header and data rows', () => {
    const csv = alertsToCsv(alerts)
    expect(csv).toContain('id,timestamp,severity')
    expect(csv).toContain('1,2026-09-28T12:00:00Z,HIGH')
    expect(csv).toContain('2,2026-09-28T12:01:00Z,LOW')
  })
})

describe('timeAgo', () => {
  const now = new Date('2026-09-28T12:10:00Z').getTime()
  it('shows seconds', () => {
    expect(timeAgo('2026-09-28T12:09:30Z', now)).toBe('30s ago')
  })
  it('shows minutes', () => {
    expect(timeAgo('2026-09-28T12:08:00Z', now)).toBe('2m ago')
  })
  it('shows just now for future', () => {
    expect(timeAgo('2026-10-01T12:00:00Z', now)).toBe('just now')
  })
})