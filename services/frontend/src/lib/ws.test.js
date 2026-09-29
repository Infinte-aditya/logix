import { describe, expect, it } from 'vitest'
import App from '../App.jsx'
import { buildWsUrl } from './ws'

describe('buildWsUrl', () => {
  it('falls back to the host gateway when VITE_WS_URL is unset', () => {
    expect(buildWsUrl({})).toBe('ws://localhost:8000/ws')
  })

  it('uses VITE_WS_URL when set', () => {
    expect(buildWsUrl({ VITE_WS_URL: 'ws://gateway.example/ws' })).toBe(
      'ws://gateway.example/ws',
    )
  })
})

describe('App', () => {
  it('is a renderable component', () => {
    expect(typeof App).toBe('function')
  })
})