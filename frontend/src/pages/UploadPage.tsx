import { ArrowRight, CircleCheck, CircleX, FileText, LoaderCircle, type LucideIcon } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
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
  type PolicyUploadResult,
  type SalesUploadResult,
  type StockUploadResult,
  type Upload,
  type UploadSummary,
} from '@/lib/api'
import { formatDate, formatRupees, plural } from '@/lib/format'
import { useLiveEvents } from '@/hooks/useLive'
import { SEVERITIES } from '@/lib/issues'
import { cn } from '@/lib/utils'

interface FileKind<T extends UploadSummary> {
  title: string
  description: string
  example: string // the sample file's name
  extension: '.xlsx' | '.csv' | '.pdf'
  icon?: LucideIcon
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

const POLICY: FileKind<PolicyUploadResult> = {
  title: '7 · Company policy',
  description: 'The rules proposals follow. Each rule is embedded so the Policy page can search them by meaning.',
  example: 'company_policy.pdf',
  extension: '.pdf',
  icon: FileText,
  send: api.uploadPolicy,
  details: (r) => (
    <>
      {plural(r.rules_loaded, 'rule')} saved, embedded with {r.embedding_model} ·{' '}
      <Link to="/policy" className="underline">
        Open the Policy page
      </Link>
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
        <InvoiceCard />
        <UploadCard kind={POLICY} />
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
  const accept = { '.csv': '.csv,text/csv', '.pdf': '.pdf,application/pdf', '.xlsx': '.xlsx' }[kind.extension]

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
          icon={kind.icon}
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

  // While the model reads the chat: the server says when it's done (a live event), and the
  // card also asks every 15 seconds in case live updates aren't getting through.
  useEffect(() => {
    if (upload?.status !== 'processing') return
    const timer = setInterval(() => {
      api.upload(upload.id).then(setUpload, (err: unknown) => {
        setError(err instanceof Error ? err : new Error(String(err)))
      })
    }, 15_000)
    return () => clearInterval(timer)
  }, [upload])
  useLiveEvents((event) => {
    if (event.type !== 'upload.finished' || event.upload_id !== upload?.id) return
    api.upload(event.upload_id).then(setUpload, (err: unknown) => {
      setError(err instanceof Error ? err : new Error(String(err)))
    })
  })

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

/** One invoice PDF on the card: being sent, being read, or done. */
interface InvoiceFile {
  key: number
  filename: string
  upload: Upload | null // null while the file is being sent
  error: Error | null // the API refused it (not a PDF, no text, already uploaded)
}

/**
 * Several PDFs can be dropped at once. Each is read in the background (the model reads one at
 * a time, so later ones wait their turn); a live event says when each is done.
 */
function InvoiceCard() {
  const [files, setFiles] = useState<InvoiceFile[]>([])
  const nextKey = useRef(0)

  function change(match: (f: InvoiceFile) => boolean, update: Partial<InvoiceFile>) {
    setFiles((all) => all.map((f) => (match(f) ? { ...f, ...update } : f)))
  }

  function refresh(uploadId: number) {
    api.upload(uploadId).then(
      (upload) => change((f) => f.upload?.id === uploadId, { upload }),
      () => undefined, // keep what's shown; the next event or check tries again
    )
  }

  async function send(file: File) {
    const key = nextKey.current++
    setFiles((all) => [...all, { key, filename: file.name, upload: null, error: null }])
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      change((f) => f.key === key, { error: new Error(`"${file.name}" is not a .pdf file.`) })
      return
    }
    try {
      const { upload } = await api.uploadInvoice(file)
      change((f) => f.key === key, { upload })
    } catch (err) {
      change((f) => f.key === key, { error: err instanceof Error ? err : new Error(String(err)) })
    }
  }

  useLiveEvents((event) => {
    if (event.type === 'upload.finished' && files.some((f) => f.upload?.id === event.upload_id)) {
      refresh(event.upload_id)
    }
  })
  // A fallback in case live updates aren't getting through.
  const waiting = files.filter((f) => f.upload?.status === 'processing').map((f) => f.upload!.id)
  const waitingKey = waiting.join(',')
  useEffect(() => {
    if (!waitingKey) return
    const timer = setInterval(() => {
      for (const id of waitingKey.split(',')) refresh(Number(id))
    }, 15_000)
    return () => clearInterval(timer)
  }, [waitingKey])

  const sending = files.filter((f) => f.upload === null && f.error === null).length
  return (
    <Card className="md:col-span-2">
      <CardHeader>
        <CardTitle>6 · Supplier invoices</CardTitle>
        <CardDescription>
          Tax invoices as PDFs (with text, not scans). Code reads the item table and checks every figure; the
          language model reads the rest. Each invoice then waits in the Approval Inbox to be approved for payment,
          and a second copy of an invoice is caught and never paid.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FileDropZone
          label="Drop the invoice_*.pdf files here"
          hint="or click to choose · .pdf, several at once, up to 5 MB each"
          accept=".pdf,application/pdf"
          multiple
          icon={FileText}
          busyLabel={sending > 0 ? `Uploading ${plural(sending, 'file')}…` : null}
          onFile={(file) => void send(file)}
        />
        {files.length > 0 && (
          <ul className="divide-y rounded-lg border bg-muted/30 text-sm">
            {files.map((file) => (
              <InvoiceFileRow key={file.key} file={file} />
            ))}
          </ul>
        )}
        {files.some((f) => f.upload?.status === 'processed') && (
          <div className="flex flex-wrap gap-4 text-sm">
            <Link to="/invoices" className="underline">
              See the invoices
            </Link>
            <Link to="/inbox" className="underline">
              Approve them in the Approval Inbox
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function InvoiceFileRow({ file }: { file: InvoiceFile }) {
  const { upload, error } = file
  const seconds = useSecondsSince(upload?.status === 'processing' ? upload.created_at : null)
  const existingId = error instanceof ApiError ? uploadIdFrom(error.details) : null
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
      {error || upload?.status === 'failed' ? (
        <CircleX className="size-4 shrink-0 text-destructive" aria-hidden />
      ) : upload?.status === 'processed' ? (
        <CircleCheck className="size-4 shrink-0 text-emerald-600" aria-hidden />
      ) : (
        <LoaderCircle className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
      )}
      <span className="font-medium">{file.filename}</span>
      <span className={cn('text-muted-foreground', (error || upload?.status === 'failed') && 'text-destructive')}>
        {error ? (
          <>
            {error.message}
            {existingId !== null && (
              <>
                {' '}
                <Link to={`/issues?upload=${existingId}`} className="underline">
                  See upload #{existingId}
                </Link>
              </>
            )}
          </>
        ) : upload === null ? (
          'Uploading…'
        ) : upload.status === 'processing' ? (
          `Reading… ${seconds}s (about a minute each; later files wait their turn)`
        ) : upload.status === 'failed' ? (
          upload.error
        ) : (
          <>
            {plural(upload.rows_read, 'line')} read
            {upload.as_of && `, dated ${formatDate(upload.as_of)}`} ·{' '}
            <Link to={`/issues?upload=${upload.id}`} className="underline">
              Issues
            </Link>
          </>
        )}
      </span>
    </li>
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
