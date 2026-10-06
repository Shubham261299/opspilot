import { CircleX } from 'lucide-react'
import { Fragment, useCallback, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { SeverityBadge } from '@/components/SeverityBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApi } from '@/hooks/useApi'
import { api, type Issue, type Upload } from '@/lib/api'
import { formatDate, formatDateTime } from '@/lib/format'
import { groupIssues, SEVERITIES, SEVERITY_MEANING } from '@/lib/issues'

export function IssuesPage() {
  // /issues shows the latest upload; /issues?upload=3 shows upload 3.
  const [params] = useSearchParams()
  const uploadId = Number(params.get('upload')) || undefined
  const load = useCallback(() => api.issues(uploadId), [uploadId])
  const { data, error, loading } = useApi(load)
  const uploads = useApi(api.uploads)

  const issues = useMemo(() => data?.items ?? [], [data])
  const groups = useMemo(() => groupIssues(issues), [issues])
  const upload = data?.upload ?? null

  return (
    <>
      <PageHeader
        title="Issues"
        description={
          upload
            ? `${upload.filename} · upload #${upload.id} · uploaded ${formatDateTime(upload.created_at)}` +
              (upload.as_of ? ` · count of ${formatDate(upload.as_of)}` : '')
            : 'Every problem found in the latest upload. Nothing is dropped silently.'
        }
        actions={
          uploads.data && uploads.data.items.length > 0 ? (
            <UploadPicker uploads={uploads.data.items} selected={upload?.id ?? null} />
          ) : undefined
        }
      />

      {error && <ErrorAlert error={error} title="Couldn't load the issues" />}
      {loading && !data && <Skeleton className="h-40 w-full" />}

      {data && !upload && (
        <Card className="flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">Nothing uploaded yet, so there are no issues to show.</p>
          <Button asChild size="sm">
            <Link to="/upload">Upload</Link>
          </Button>
        </Card>
      )}

      {upload?.status === 'failed' && (
        <Alert variant="destructive">
          <CircleX />
          <AlertTitle>This upload failed, so nothing from it was saved</AlertTitle>
          <AlertDescription>{upload.error}</AlertDescription>
        </Alert>
      )}

      {issues.length > 0 && (
        <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          {SEVERITIES.map((severity) => (
            <span key={severity} className="flex items-center gap-1.5">
              <SeverityBadge severity={severity} count={issues.filter((i) => i.severity === severity).length} />
              <span className="text-muted-foreground">{SEVERITY_MEANING[severity]}</span>
            </span>
          ))}
        </div>
      )}

      <div className="space-y-6">
        {groups.map((group) => (
          <Card key={group.issueType} className="gap-3 pb-0">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="text-base">{group.label}</CardTitle>
              <div className="flex items-center gap-2">
                <SeverityBadge severity={group.severity} />
                <Badge variant="outline" className="tabular-nums">
                  {group.issues.length}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="px-0">
              <IssueTable issues={group.issues} />
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}

function IssueTable({ issues }: { issues: Issue[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16 pl-6">Row</TableHead>
          <TableHead className="w-56">Product / customer</TableHead>
          <TableHead className="pr-6">What happened</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {issues.map((issue) => (
          <TableRow key={issue.id}>
            <TableCell className="pl-6 align-top tabular-nums">{issue.source_row ?? 'File'}</TableCell>
            <TableCell className="align-top whitespace-normal">
              {issue.sku || issue.customer_code ? (
                <>
                  <div className="font-mono text-xs">{issue.sku ?? issue.customer_code}</div>
                  <div className="text-xs text-muted-foreground">{issue.product_name ?? issue.customer_name}</div>
                </>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="pr-6 whitespace-normal">
              <p>{issue.detail}</p>
              {issue.raw && issue.source_row !== null && <OriginalCells raw={issue.raw} />}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/** The row exactly as it was in the spreadsheet, folded away until clicked. */
function OriginalCells({ raw }: { raw: Record<string, unknown> }) {
  return (
    <details className="mt-1 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none">Original cells</summary>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        {Object.entries(raw).map(([column, value]) => (
          <Fragment key={column}>
            <dt>{column}</dt>
            {/* JSON.stringify shows text in quotes, so stray spaces stay visible */}
            <dd className="font-mono break-all">{JSON.stringify(value)}</dd>
          </Fragment>
        ))}
      </dl>
    </details>
  )
}

const KIND_NAMES: Record<string, string> = {
  stock_register: 'Stock register',
  customers: 'Customers',
  outstanding_dues: 'Outstanding dues',
  sales_history: 'Sales history',
  whatsapp_chat: 'WhatsApp chat',
}

/** Choose which upload's issues to show; the choice lives in the URL (?upload=3). */
function UploadPicker({ uploads, selected }: { uploads: Upload[]; selected: number | null }) {
  const navigate = useNavigate()
  return (
    <select
      aria-label="Upload"
      value={selected ?? ''}
      onChange={(event) => void navigate(`/issues?upload=${event.target.value}`)}
      className="h-9 rounded-md border bg-background px-3 text-sm"
    >
      {uploads.map((u) => (
        <option key={u.id} value={u.id}>
          #{u.id} · {KIND_NAMES[u.kind] ?? u.kind} · {u.filename}
          {u.status === 'failed' ? ' (failed)' : ''}
        </option>
      ))}
    </select>
  )
}
