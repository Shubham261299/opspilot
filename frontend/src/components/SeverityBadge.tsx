import { Badge } from '@/components/ui/badge'
import type { Severity } from '@/lib/api'
import { cn } from '@/lib/utils'

const STYLES: Record<Severity, string> = {
  error: 'bg-destructive/10 text-destructive',
  warning: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  info: 'bg-secondary text-secondary-foreground',
}

const NAMES: Record<Severity, string> = { error: 'Error', warning: 'Warning', info: 'Info' }

interface SeverityBadgeProps {
  severity: Severity
  count?: number
  className?: string
}

/** "Error", or with a count: "2 errors". */
export function SeverityBadge({ severity, count, className }: SeverityBadgeProps) {
  const text = count === undefined ? NAMES[severity] : `${count} ${NAMES[severity].toLowerCase()}${count === 1 ? '' : 's'}`
  return <Badge className={cn(STYLES[severity], className)}>{text}</Badge>
}
