import { ArrowRight, CircleCheck, CircleX, LoaderCircle } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { FileDropZone } from '@/components/FileDropZone'
import { PageHeader } from '@/components/PageHeader'
import { SeverityBadge } from '@/components/SeverityBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  api,
  ApiError,
  type CustomersUploadResult,
  type DuesUploadResult,
  type SalesUploadResult,
  type StockUploadResult,
  type Upload,
  type UploadSummary,
} from '@/lib/api'
import { formatDate, formatRupees, plural } from '@/lib/format'
import { SEVERITIES } from '@/lib/issues'

interface FileKind<T extends UploadSummary> {
  title: string
  description: string
  example: string // the sample file's name
  extension: '.xlsx' | '.csv'
  send: (file: File) => Promise<T>
  details: (result: T) => ReactNode // what this kind of file adds to the summary
}

const STOCK: FileKind<StockUploadResult> = {
  title: '1 · Stock register',
  description: 'The godown count. Clean rows become stock counts.',
  example: 'stock_register.xlsx',
  extension: '.xlsx',
  send: api.uploadStockRegister,
  details: (r) => (
    <>
      {plural(r.upload.rows_loaded, 'stock count')} saved, as of {formatDate(r.upload.as_of)}
      {r.po_notes.length > 0 && ` · ${plural(r.po_notes.length, 'open order')} found in remarks`}
    </>
  ),
}

const CUSTOMERS: FileKind<CustomersUploadResult> = {
  title: '2 · Customers',
  description: 'Shops, phone numbers and credit terms. Upload before dues and sales.',
  example: 'customers.xlsx',
  extension: '.xlsx',
  send: api.uploadCustomers,
  details: (r) => (
    <>
      {plural(r.added.length, 'customer')} added · {r.updated.length} updated
    </>
  ),
}

const DUES: FileKind<DuesUploadResult> = {
  title: '3 · Outstanding dues',
  description: 'Unpaid bills, for payment reminders and holds.',
  example: 'outstanding_dues.xlsx',
  extension: '.xlsx',
  send: api.uploadDues,
  details: (r) => (
    <>
      {plural(r.bills_loaded, 'unpaid bill')} · {formatRupees(r.total_balance)} outstanding
    </>
  ),
}

const SALES: FileKind<SalesUploadResult> = {
  title: '4 · Sales history',
  description: 'The last 90 days of sales, for average daily demand.',
  example: 'sales_history_90d.csv',
  extension: '.csv',
  send: api.uploadSales,
  details: (r) => (
    <>
      {plural(r.lines_loaded, 'sales line')} · last sale {formatDate(r.last_sale)}
    </>
  ),
}

export function UploadPage() {
  return (
    <>
      <PageHeader
        title="Upload"
        description="Drop each file on its card. Clean rows are saved; every problem is listed on the Issues page."
        actions={
          <Button asChild>
            <Link to="/inbox">
              Go to the Approval Inbox
              <ArrowRight data-icon="inline-end" />
            </Link>
          </Button>
        }
      />
      <div className="grid gap-6 md:grid-cols-2">
        <UploadCard kind={STOCK} />
        <UploadCard kind={CUSTOMERS} />
        <UploadCard kind={DUES} />
        <UploadCard kind={SALES} />
        <WhatsAppCard />
      </div>
    </>
  )
}

function UploadCard<T extends UploadSummary>({ kind }: { kind: FileKind<T> }) {
  const [sending, setSending] = useState<string | null>(null)
  const [result, setResult] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)

  async function send(file: File) {
    if (sending) return // one upload at a time per card
    setResult(null)
    setError(null)
    if (!file.name.toLowerCase().endsWith(kind.extension)) {
      setError(new Error(`"${file.name}" is not a ${kind.extension} file.`))
      return
    }
    setSending(file.name)
    try {
      setResult(await kind.send(file))
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setSending(null)
    }
  }

  const failedUploadId = error instanceof ApiError ? uploadIdFrom(error.details) : null
  const accept = kind.extension === '.csv' ? '.csv,text/csv' : '.xlsx'

  return (
    <Card>
      <CardHeader>
        <CardTitle>{kind.title}</CardTitle>
        <CardDescription>{kind.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FileDropZone
          label={`Drop ${kind.example} here`}
          hint={`or click to choose · ${kind.extension}, up to 5 MB`}
          accept={accept}
          busyLabel={sending && `Uploading ${sending}…`}
          onFile={(file) => void send(file)}
        />
        {error && (
          <ErrorAlert error={error} title="The file was not loaded">
            {failedUploadId !== null && (
              <p>
                Recorded as failed upload #{failedUploadId}.{' '}
                <Link to={`/issues?upload=${failedUploadId}`}>See why</Link>.
              </p>
            )}
          </ErrorAlert>
        )}
        {result && <Summary result={result} details={kind.details(result)} />}
      </CardContent>
    </Card>
  )
}

/** The chat is read by the language model in the background, so this card shows progress. */
function WhatsAppCard() {
  const [sending, setSending] = useState<string | null>(null)
  const [upload, setUpload] = useState<Upload | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const seconds = useSecondsSince(upload?.status === 'processing' ? upload.created_at : null)

  // While the model reads the chat, ask the API for the upload's status every 5 seconds.
  useEffect(() => {
    if (upload?.status !== 'processing') return
    const timer = setInterval(() => {
      api.upload(upload.id).then(setUpload, (err: unknown) => {
        setError(err instanceof Error ? err : new Error(String(err)))
      })
    }, 5000)
    return () => clearInterval(timer)
  }, [upload])

  async function send(file: File) {
    if (sending || upload?.status === 'processing') return
    setUpload(null)
    setError(null)
    if (!file.name.toLowerCase().endsWith('.txt')) {
      setError(new Error(`"${file.name}" is not a .txt chat export.`))
      return
    }
    setSending(file.name)
    try {
      setUpload((await api.uploadWhatsapp(file)).upload)
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setSending(null)
    }
  }

  const failedUploadId = error instanceof ApiError ? uploadIdFrom(error.details) : null
  return (
    <Card className="md:col-span-2">
      <CardHeader>
        <CardTitle>5 · WhatsApp orders</CardTitle>
        <CardDescription>
          A chat exported from WhatsApp ("Export chat", without media). The language model reads each
          customer's messages; every order then waits in the Approval Inbox for you to confirm.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FileDropZone
          label="Drop whatsapp_orders_export.txt here"
          hint="or click to choose · .txt, up to 5 MB"
          accept=".txt,text/plain"
          busyLabel={sending && `Uploading ${sending}…`}
          onFile={(file) => void send(file)}
        />
        {error && (
          <ErrorAlert error={error} title="The chat was not loaded">
            {failedUploadId !== null && (
              <p>
                {error instanceof ApiError && error.code === 'already_uploaded' ? 'It is' : 'Recorded as'}{' '}
                upload #{failedUploadId}. <Link to={`/issues?upload=${failedUploadId}`}>See it</Link>.
              </p>
            )}
          </ErrorAlert>
        )}
        {upload?.status === 'processing' && (
          <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-4 text-sm">
            <LoaderCircle className="size-4 animate-spin text-muted-foreground" aria-hidden />
            <span>
              Reading {upload.rows_read} messages with the language model… {seconds}s. On a laptop this takes a
              few minutes; you can leave this page and come back.
            </span>
          </div>
        )}
        {upload?.status === 'processed' && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 p-4 text-sm">
            <CircleCheck className="size-4 text-emerald-600" aria-hidden />
            <span className="font-medium">
              {upload.filename}: {plural(upload.rows_loaded, 'order')} read from {upload.rows_read} messages
            </span>
            <Link to="/inbox" className="ml-auto underline">
              Confirm them in the Approval Inbox
            </Link>
            <Link to="/orders" className="underline">
              See the orders
            </Link>
            <Link to={`/issues?upload=${upload.id}`} className="underline">
              Issues
            </Link>
          </div>
        )}
        {upload?.status === 'failed' && (
          <div className="flex items-center gap-3 rounded-lg border border-destructive/40 p-4 text-sm text-destructive">
            <CircleX className="size-4" aria-hidden />
            {upload.error}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** Whole seconds since an ISO time, updated every second; 0 when there is no time. */
function useSecondsSince(since: string | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!since) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [since])
  return since ? Math.max(0, Math.round((now - new Date(since).getTime()) / 1000)) : 0
}

function Summary({ result, details }: { result: UploadSummary; details: ReactNode }) {
  const counts = result.issues_by_severity
  const total = counts.error + counts.warning + counts.info
  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <CircleCheck className="size-4 text-emerald-600" aria-hidden />
        {result.upload.filename} processed (upload #{result.upload.id})
      </p>
      <p className="text-muted-foreground">{details}</p>
      <div className="flex flex-wrap items-center gap-2">
        {SEVERITIES.map((severity) => (
          <SeverityBadge key={severity} severity={severity} count={counts[severity]} />
        ))}
        {total > 0 && (
          <Link to={`/issues?upload=${result.upload.id}`} className="ml-auto text-sm underline">
            Review {plural(total, 'issue')}
          </Link>
        )}
      </div>
    </div>
  )
}

function uploadIdFrom(details: unknown): number | null {
  if (typeof details === 'object' && details !== null && 'upload_id' in details) {
    const id = (details as { upload_id: unknown }).upload_id
    return typeof id === 'number' ? id : null
  }
  return null
}
