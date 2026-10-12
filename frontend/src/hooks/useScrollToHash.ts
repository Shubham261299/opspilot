import { useEffect } from 'react'
import { useLocation } from 'react-router'

/**
 * Scroll to the element named in the URL's #hash (e.g. /orders#order-12) once the page's data
 * has arrived. React Router changes pages without a full load, so the browser doesn't do it.
 */
export function useScrollToHash(loaded: boolean): void {
  const { hash } = useLocation()
  useEffect(() => {
    if (!loaded || !hash) return
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: 'start' })
  }, [loaded, hash])
}
