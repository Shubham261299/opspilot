// Live updates from the API (backend: app/events.py and app/api/ws.py).
//
// A WebSocket is a connection that stays open after it is made, so the server can send a
// message whenever something changes, instead of the page asking again and again. Messages
// only say *what* changed ("proposal 42 was explained"); pages then reload their data with
// the normal API calls in lib/api.ts. One connection is shared by the whole app, and it is
// reopened by itself if it drops (server restart, laptop asleep).

/** Mirrors the event functions in backend/app/events.py. */
export type LiveEvent =
  | { type: 'hello' } // connected; events flow from here on
  | { type: 'reconnected' } // made here, not sent by the server: events may have been missed
  | { type: 'proposal.created'; proposal_ids: number[] }
  | { type: 'proposal.updated'; proposal_ids: number[] }
  | { type: 'proposal.explained'; proposal_id: number }
  | { type: 'proposal.decided'; proposal_id: number; status: 'approved' | 'rejected' }
  | { type: 'upload.finished'; upload_id: number; kind: string; status: 'processed' | 'failed' }

export type LiveEventType = LiveEvent['type']
export type LiveStatus = 'connecting' | 'live' | 'offline'

type Listener = (event: LiveEvent) => void

const listeners = new Set<Listener>()
const statusListeners = new Set<() => void>()
let socket: WebSocket | null = null
let status: LiveStatus = 'connecting'
let wasConnected = false
let retryMs = 1000

/** Hear every event. Returns the function that stops listening. */
export function onLiveEvent(listener: Listener): () => void {
  listeners.add(listener)
  start()
  return () => listeners.delete(listener)
}

/** For useSyncExternalStore: be told when the status changes, and read it. */
export function onLiveStatus(listener: () => void): () => void {
  statusListeners.add(listener)
  start()
  return () => statusListeners.delete(listener)
}

export function liveStatus(): LiveStatus {
  return status
}

function start() {
  if (socket === null && status !== 'offline') connect()
}

function connect() {
  // The page's own address: Vite (dev) and nginx (Docker) forward /api/ws to the API.
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${scheme}://${window.location.host}/api/ws`)
  socket = ws
  ws.onmessage = (message: MessageEvent<string>) => {
    let event: LiveEvent
    try {
      event = JSON.parse(message.data) as LiveEvent
    } catch {
      return // not ours; ignore
    }
    if (event.type === 'hello') {
      retryMs = 1000
      setStatus('live')
      if (wasConnected) emit({ type: 'reconnected' })
      wasConnected = true
    }
    emit(event)
  }
  ws.onclose = () => {
    socket = null
    setStatus('offline')
    // Try again after 1 s, then 2, 4, 8, at most every 15 s.
    window.setTimeout(connect, retryMs)
    retryMs = Math.min(retryMs * 2, 15_000)
  }
}

function emit(event: LiveEvent) {
  for (const listener of listeners) listener(event)
}

function setStatus(next: LiveStatus) {
  if (next === status) return
  status = next
  for (const listener of statusListeners) listener()
}
