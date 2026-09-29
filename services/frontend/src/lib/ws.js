export function buildWsUrl(env = import.meta.env) {
  return env.VITE_WS_URL || 'ws://localhost:8000/ws'
}