import { useCallback, useEffect, useState } from 'react'

export interface ApiState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
}

interface Answer<T> {
  load: () => Promise<T> // which request this answer belongs to
  version: number
  data: T | null
  error: Error | null
}

/**
 * Load data when a page appears, and again whenever `reload()` is called.
 *
 * `load` must be a stable function (declared outside the component, or wrapped in
 * useCallback); otherwise the effect would run again on every render.
 */
export function useApi<T>(load: () => Promise<T>): ApiState<T> {
  const [version, setVersion] = useState(0)
  const [answer, setAnswer] = useState<Answer<T> | null>(null)

  useEffect(() => {
    let active = true // ignore a late answer if the page was left or the request changed
    load().then(
      (data) => {
        if (active) setAnswer({ load, version, data, error: null })
      },
      (err: unknown) => {
        const error = err instanceof Error ? err : new Error(String(err))
        // Keep the previous data on screen when a reload fails.
        if (active) setAnswer((previous) => ({ load, version, data: previous?.data ?? null, error }))
      },
    )
    return () => {
      active = false
    }
  }, [load, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  // Derived, not stored: we're loading until there's an answer for the *current* request.
  const loading = answer === null || answer.load !== load || answer.version !== version
  return { data: answer?.data ?? null, error: answer?.error ?? null, loading, reload }
}
