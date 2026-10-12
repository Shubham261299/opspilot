import { Boxes } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'

import { useLiveStatus } from '@/hooks/useLive'
import { cn } from '@/lib/utils'

const LINKS = [
  { to: '/upload', label: 'Upload' },
  { to: '/inbox', label: 'Approval Inbox' },
  { to: '/orders', label: 'Orders' },
  { to: '/invoices', label: 'Invoices' },
  { to: '/stock', label: 'Stock' },
  { to: '/customers', label: 'Customers' },
  { to: '/issues', label: 'Issues' },
]

/** The frame around every page: header with navigation, then the page itself (<Outlet />). */
export function Layout() {
  return (
    <div className="min-h-svh bg-muted/40">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
          <div className="flex items-center gap-2 font-semibold">
            <Boxes className="size-5" aria-hidden />
            OpsPilot
            <span className="text-sm font-normal text-muted-foreground">Sharma Traders, Pune</span>
          </div>
          <nav className="flex gap-1" aria-label="Main">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground',
                    isActive && 'bg-muted text-foreground',
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <LiveIndicator />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

/** A dot in the header: green while the server's live updates are reaching this page. */
function LiveIndicator() {
  const status = useLiveStatus()
  const live = status === 'live'
  return (
    <span
      className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground"
      title={
        live
          ? 'Pages update by themselves when something changes'
          : 'Not receiving live updates; trying again. Pages still work, refresh to see changes.'
      }
    >
      <span
        aria-hidden
        className={cn('size-2 rounded-full', live ? 'bg-emerald-500' : 'animate-pulse bg-amber-500')}
      />
      {live ? 'Live' : status === 'connecting' ? 'Connecting…' : 'Reconnecting…'}
    </span>
  )
}
