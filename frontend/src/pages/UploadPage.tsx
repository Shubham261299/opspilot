import { ArrowRight, CircleCheck, FileSpreadsheet, LoaderCircle } from 'lucide-react'
import { type DragEvent, useRef, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { SeverityBadge } from '@/components/SeverityBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { api, ApiError, type StockUploadResult } from '@/lib/api'
import { formatDate, plural } from '@/lib/format'
import { SEVERITIES, SEVERITY_MEANING } from '@/lib/issues'
import { cn } from '@/lib/utils'

export function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploadingName, setUploadingName] = useState<string | null>(null)
  const [result, setResult] = useState<StockUploadResult | null>(null)
  const [error, setError] = useState<Error | null>(null)

  async function send(file: File) {
    if (uploadingName) return // one upload at a time
    setResult(null)
    setError(null)
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      setError(new Error(`"${file.name}" is not an Excel .xlsx file.`))
      return
    }
    setUploadingName(file.name)
    try {
      setResult(await api.uploadStockRegister(file))
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setUploadingName(null)
    }
  }

  function openFilePicker() {
    inputRef.current?.click()
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault() // stop the browser from opening the file itself
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void send(file)
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>) {
    // Moving over a child element also fires "dragleave"; react only when really leaving.
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  const failedUploadId = error instanceof ApiError ? uploadIdFrom(error.details) : null

  return (
    <>
      <PageHeader
        title="Upload the stock register"
        description="Drop the godown's Excel stock sheet. Clean rows are saved as stock counts; every problem is listed on the Issues page."
      />

      <div
        role="button"
        tabIndex={0}
        aria-label="Choose the stock register file"
        aria-busy={uploadingName !== null}
        onClick={openFilePicker}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            openFilePicker()
          }
        }}
        onDragOver={(event) => {
          event.preventDefault() // required, or the browser won't allow dropping here
          setDragging(true)
        }}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          'flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed bg-background px-6 py-14 text-center transition-colors',
          dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-muted-foreground/40',
        )}
      >
        {uploadingName ? (
          <LoaderCircle className="size-9 animate-spin text-muted-foreground" aria-hidden />
        ) : (
          <FileSpreadsheet className="size-9 text-muted-foreground" aria-hidden />
        )}
        <div className="space-y-1">
          <p className="font-medium">
            {uploadingName ? `Uploading ${uploadingName}…` : 'Drag and drop stock_register.xlsx here'}
          </p>
          <p className="text-sm text-muted-foreground">or click to choose a file · Excel .xlsx, up to 5 MB</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="hidden"
          onClick={(event) => event.stopPropagation()} // don't bubble back to the drop zone
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = '' // so choosing the same file again still triggers onChange
            if (file) void send(file)
          }}
        />
      </div>

      <div className="mt-6 space-y-6">
        {error && (
          <ErrorAlert error={error} title="The file was not loaded">
            {failedUploadId !== null && (
              <p>
                It is recorded as failed upload #{failedUploadId}.{' '}
                <Link to={`/issues?upload=${failedUploadId}`}>See it on the Issues page</Link>.
              </p>
            )}
          </ErrorAlert>
        )}
        {result && <UploadSummary result={result} />}
      </div>
    </>
  )
}

function UploadSummary({ result }: { result: StockUploadResult }) {
  const { upload, issues_by_severity: counts, po_notes: poNotes } = result
  const totalIssues = counts.error + counts.warning + counts.info
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CircleCheck className="size-5 text-emerald-600" aria-hidden />
          {upload.filename} processed
        </CardTitle>
        <CardDescription>
          Upload #{upload.id} · stock count of {formatDate(upload.as_of)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Item rows read" value={upload.rows_read} />
          <Stat label="Stock counts saved" value={upload.rows_loaded} />
          <Stat label="Open orders found" value={poNotes.length} />
          <Stat label="Issues listed" value={totalIssues} />
        </dl>
        <ul className="space-y-1.5 text-sm">
          {SEVERITIES.map((severity) => (
            <li key={severity} className="flex items-center gap-2">
              <SeverityBadge severity={severity} count={counts[severity]} className="w-24" />
              <span className="text-muted-foreground">{SEVERITY_MEANING[severity]}</span>
            </li>
          ))}
        </ul>
        {poNotes.length > 0 && (
          <div className="space-y-1.5">
            <h3 className="text-sm font-medium">Open purchase orders found in remarks</h3>
            <ul className="space-y-1 text-sm text-muted-foreground">
              {poNotes.map((note) => (
                <li key={note.source_row}>
                  Row {note.source_row}: {note.qty} × {note.sku}
                  {note.supplier_code && ` from ${note.supplier_code}`}
                  {note.ordered_on && `, ordered ${formatDate(note.ordered_on)}`} (“{note.note}”)
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
      <CardFooter className="gap-2">
        <Button asChild>
          <Link to={`/issues?upload=${upload.id}`}>
            Review {plural(totalIssues, 'issue')}
            <ArrowRight data-icon="inline-end" />
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/stock">View stock</Link>
        </Button>
      </CardFooter>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
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
