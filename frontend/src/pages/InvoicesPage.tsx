import { ArrowRight, Copy, type LucideIcon, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { PolicyCitations } from '@/components/PolicyCitations'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApi } from '@/hooks/useApi'
import { useReloadOn } from '@/hooks/useLive'
import { useScrollToHash } from '@/hooks/useScrollToHash'
import { api, type Invoice, type InvoiceStatus } from '@/lib/api'
import { formatDate, formatRupees, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

const STATUS: Record<InvoiceStatus, { label: string; className: string }> = {
  awaiting_approval: { label: 'Awaiting approval', className: 'bg-amber-100 text-amber-900' },
  approved_for_payment: { label: 'Approved for payment', className: 'bg-emerald-100 text-emerald-900' },
  rejected: { label: 'Rejected', className: 'bg-muted text-foreground' },
  duplicate: { label: 'Duplicate: never paid', className: 'bg-red-100 text-red-900' },
}

export function InvoicesPage() {
  const { data, error, loading, reload } = useApi(api.invoices)
  useReloadOn(['upload.finished', 'proposal.decided', 'reconnected'], reload)
  const items = data?.items ?? []
  useScrollToHash(data !== null)

  return (
    <>
      <PageHeader
        title="Supplier invoices"
        description="Read from PDFs, with every figure checked by code. Approve or reject them for payment in the Approval Inbox."
        actions={
          <Button asChild variant="outline">
            <Link to="/inbox">
              Approval Inbox
              <ArrowRight data-icon="inline-end" />
            </Link>
          </Button>
        }
      />
      {error && <ErrorAlert error={error} title="Couldn't load the invoices" />}
      {loading && !data && <Skeleton className="h-40 w-full" />}
      {data && items.length === 0 && (
        <Card className="flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">No invoices yet. Drop the invoice PDFs on the Upload page.</p>
          <Button asChild size="sm">
            <Link to="/upload">Upload</Link>
          </Button>
        </Card>
      )}
      <div className="space-y-6">
        {items.map((invoice) => (
          <InvoiceCard key={invoice.id} invoice={invoice} />
        ))}
      </div>
    </>
  )
}

function InvoiceCard({ invoice }: { invoice: Invoice }) {
  const status = STATUS[invoice.status]
  return (
    <Card id={`invoice-${invoice.id}`} className="scroll-mt-4 gap-4">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {invoice.supplier_code && <span className="font-mono text-sm">{invoice.supplier_code}</span>}
          {invoice.supplier_name}
          <span className="text-muted-foreground">· {invoice.invoice_no}</span>
          <Badge className={cn('ml-auto', status.className)}>{status.label}</Badge>
        </CardTitle>
        <CardDescription className="flex flex-wrap gap-x-4 gap-y-1">
          <span>Dated {formatDate(invoice.invoice_date)}</span>
          {invoice.supplier_gstin && <span>GSTIN {invoice.supplier_gstin}</span>}
          <span>
            {invoice.lines_read_by === 'table'
              ? 'Lines read from the printed table by code'
              : 'Lines read by the language model, checked by code'}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!invoice.supplier_code && (
          <Notice>“{invoice.supplier_name}” is not a known supplier, so this invoice can't be approved.</Notice>
        )}
        {invoice.marked_duplicate && invoice.status !== 'duplicate' && (
          <Notice icon={Copy}>
            Stamped DUPLICATE COPY, but no original was uploaded. Check it wasn't paid outside OpsPilot.
          </Notice>
        )}
        <InvoiceLines invoice={invoice} />
        <PolicyCitations citations={invoice.policy} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          {invoice.price_jumps !== null && invoice.price_jumps > 0 && (
            <Badge className="bg-amber-100 text-amber-900">
              {plural(invoice.price_jumps, 'rate')} more than 10% above the last purchase rate
            </Badge>
          )}
          {invoice.ready === false && (
            <Badge variant="destructive">Can't be approved yet: see the Inbox card</Badge>
          )}
          {invoice.notes.map((note) => (
            <span key={note} className="text-muted-foreground">
              Note on the invoice: “{note}”
            </span>
          ))}
          <span className="ml-auto flex gap-4">
            <Link to={`/issues?upload=${invoice.upload_id}`} className="underline">
              Issues
            </Link>
            {invoice.status === 'awaiting_approval' && invoice.proposal_id !== null && (
              <Link to="/inbox" className="underline">
                Decide in the Inbox
              </Link>
            )}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

function InvoiceLines({ invoice }: { invoice: Invoice }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">#</TableHead>
          <TableHead>As printed</TableHead>
          <TableHead>Our product</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">Rate</TableHead>
          <TableHead className="text-right">Last purchase rate</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoice.lines.map((line) => (
          <TableRow key={line.line_no}>
            <TableCell className="tabular-nums text-muted-foreground">{line.line_no}</TableCell>
            <TableCell>{line.description}</TableCell>
            <TableCell>
              {line.sku ? (
                <>
                  {line.name} <span className="font-mono text-xs text-muted-foreground">{line.sku}</span>
                  {line.matched_on === 'model' && (
                    <span className="block text-xs text-muted-foreground">matched by AI, check it</span>
                  )}
                </>
              ) : (
                <span className="text-destructive">not matched</span>
              )}
            </TableCell>
            <TableCell className="text-right tabular-nums">{Number(line.qty)}</TableCell>
            <TableCell className={cn('text-right tabular-nums', line.jump_percent && 'font-semibold text-amber-800')}>
              {formatRupees(line.rate)}
              {line.jump_percent && <span className="block text-xs">+{line.jump_percent}%</span>}
            </TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground" title={line.last_rate_from ?? ''}>
              {line.last_rate ? formatRupees(line.last_rate) : '—'}
              {line.last_rate_from && <span className="block text-xs">{shortSource(line.last_rate_from)}</span>}
            </TableCell>
            <TableCell className="text-right tabular-nums">{formatRupees(line.amount)}</TableCell>
          </TableRow>
        ))}
        <TotalRow label="Subtotal" amount={invoice.subtotal} />
        <TotalRow label="GST" amount={invoice.gst_amount} />
        <TotalRow label="Grand total" amount={invoice.grand_total} strong />
      </TableBody>
    </Table>
  )
}

function TotalRow({ label, amount, strong }: { label: string; amount: string; strong?: boolean }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={6} className={cn('text-right', strong ? 'font-semibold' : 'text-muted-foreground')}>
        {label}
      </TableCell>
      <TableCell className={cn('text-right tabular-nums', strong && 'font-semibold')}>{formatRupees(amount)}</TableCell>
    </TableRow>
  )
}

function Notice({ children, icon: Icon = TriangleAlert }: { children: ReactNode; icon?: LucideIcon }) {
  return (
    <p className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
      <Icon className="size-4 shrink-0" aria-hidden />
      {children}
    </p>
  )
}

/** "the product master's cost price" -> "cost price"; "invoice X of 12 Sep 2026" stays. */
function shortSource(from: string): string {
  return from === "the product master's cost price" ? 'cost price' : from
}
