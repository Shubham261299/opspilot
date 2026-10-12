import { useEffect, useRef, useSyncExternalStore } from 'react'

import {
  liveStatus,
  onLiveEvent,
  onLiveStatus,
  type LiveEvent,
  type LiveEventType,
  type LiveStatus,
} from '@/lib/live'

/** Call `handler` for every live event while the component is on screen. */
export function useLiveEvents(handler: (event: LiveEvent) => void): void {
  // The latest handler, kept in a ref so a new function each render doesn't resubscribe.
  const latest = useRef(handler)
  useEffect(() => {
    latest.current = handler
  })
  useEffect(() => onLiveEvent((event) => latest.current(event)), [])
}

/**
 * Reload a page's data when one of `types` arrives. Events often come in bursts (the agents
 * explain proposals one after another), so they are gathered for `delayMs` into one reload.
 */
export function useReloadOn(types: LiveEventType[], reload: () => void, delayMs = 400): void {
  const timer = useRef<number | null>(null)
  useLiveEvents((event) => {
    if (!types.includes(event.type) || timer.current !== null) return
    timer.current = window.setTimeout(() => {
      timer.current = null
      reload()
    }, delayMs)
  })
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )
}

/**
 * Whether live updates are flowing. useSyncExternalStore is React's way to read a value that
 * lives outside React (here, the shared connection in lib/live.ts) and re-render when it changes.
 */
export function useLiveStatus(): LiveStatus {
  return useSyncExternalStore(onLiveStatus, liveStatus)
}
