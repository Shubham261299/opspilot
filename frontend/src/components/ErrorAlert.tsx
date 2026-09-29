import { CircleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ApiError } from '@/lib/api'

interface ErrorAlertProps {
  error: Error
  title?: string
  children?: ReactNode
}

/** Shows what went wrong, plus the request id that finds the matching server log lines. */
export function ErrorAlert({ error, title = 'Something went wrong', children }: ErrorAlertProps) {
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{error.message}</p>
        {children}
        {requestId && <p className="text-xs">Request id: {requestId}</p>}
      </AlertDescription>
    </Alert>
  )
}
