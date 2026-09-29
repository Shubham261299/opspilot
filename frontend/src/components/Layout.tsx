import { Boxes } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'

import { cn } from '@/lib/utils'

const LINKS = [
  { to: '/upload', label: 'Upload' },
  { to: '/stock', label: 'Stock' },
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
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
