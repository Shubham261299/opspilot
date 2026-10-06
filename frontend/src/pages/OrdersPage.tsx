import { Check, LoaderCircle, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApi } from '@/hooks/useApi'
import { api, type Order, type OrderLine, type OrderStatus, type Product } from '@/lib/api'
import { formatDateTime, plural } from '@/lib/format'

const STATUS: Record<OrderStatus, { label: string; className: string }> = {
  awaiting_confirmation: { label: 'Awaiting confirmation', className: 'bg-amber-100 text-amber-900' },
  confirmed: { label: 'Confirmed', className: 'bg-emerald-100 text-emerald-900' },
  rejected: { label: 'Rejected', className: 'bg-muted text-foreground' },
}

const HOW_MATCHED: Record<string, string> = {
  name: 'exact name',
  alias: 'known alias',
  'same words': 'same words',
  model: 'matched by AI, check it',
  owner: 'chosen by you',
}

export function OrdersPage() {
  const orders = useApi(api.orders)
  const products = useApi(api.products)
  const enquiries = useApi(api.enquiries)
  const items = orders.data?.items ?? []
  const waiting = items.filter((o) => o.status === 'awaiting_confirmation')
  const done = items.filter((o) => o.status !== 'awaiting_confirmation')

  return (
    <>
      <PageHeader
        title="Orders"
        description="Orders read from WhatsApp. Fix a line here; confirm or reject the order in the Approval Inbox."
        actions={
          <Button asChild variant="outline">
            <Link to="/inbox">Approval Inbox</Link>
          </Button>
        }
      />
      {orders.error && <ErrorAlert error={orders.error} title="Couldn't load the orders" />}
      {orders.loading && !orders.data && <Skeleton className="h-40 w-full" />}
      {orders.data && items.length === 0 && (
        <Card className="flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">No orders yet. Upload a WhatsApp chat export first.</p>
          <Button asChild size="sm">
            <Link to="/upload">Upload</Link>
          </Button>
        </Card>
      )}

      <div className="space-y-4">
        {[...waiting, ...done].map((order) => (
          <OrderCard
            key={order.id}
            order={order}
            products={products.data?.items ?? []}
            onChanged={orders.reload}
          />
        ))}
      </div>

      {enquiries.data && enquiries.data.items.length > 0 && (
        <Card className="mt-8 gap-3">
          <CardHeader>
            <CardTitle className="text-base">Enquiries: questions, not orders</CardTitle>
            <CardDescription>Prices, stock, and products we may not sell (policy 3.3).</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm">
              {enquiries.data.items.map((enquiry) => (
                <li key={enquiry.id}>
                  <span className="font-medium">{enquiry.sender}</span>
                  {enquiry.customer_code && (
                    <span className="ml-1 font-mono text-xs text-muted-foreground">{enquiry.customer_code}</span>
                  )}
                  : “{enquiry.text}”
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </>
  )
}

function OrderCard({ order, products, onChanged }: { order: Order; products: Product[]; onChanged: () => void }) {
  const editable = order.status === 'awaiting_confirmation'
  const needsWork = order.lines.filter((line) => !line.sku).length
  return (
    <Card id={`order-${order.id}`} className="gap-3 scroll-mt-4">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {order.customer_name ?? order.sender}
          {order.customer_code ? (
            <span className="font-mono text-xs text-muted-foreground">{order.customer_code}</span>
          ) : (
            <Badge variant="destructive">Unknown sender</Badge>
          )}
          <Badge className={STATUS[order.status].className}>{STATUS[order.status].label}</Badge>
          {editable && needsWork > 0 && <Badge variant="outline">{plural(needsWork, 'line')} to fix</Badge>}
        </CardTitle>
        <CardDescription>
          Order #{order.id} · first message {formatDateTime(order.first_sent_at)} · chat lines{' '}
          {order.source_lines.join(', ')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-6">Customer wrote</TableHead>
              <TableHead>Product</TableHead>
              <TableHead className="w-24">Qty</TableHead>
              <TableHead className="pr-6">{editable ? '' : 'Matched by'}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {order.lines.map((line) =>
              editable ? (
                <EditableLine key={line.id} orderId={order.id} line={line} products={products} onChanged={onChanged} />
              ) : (
                <TableRow key={line.id}>
                  <TableCell className="pl-6">“{line.written}”</TableCell>
                  <TableCell>{line.name ?? '—'}</TableCell>
                  <TableCell className="tabular-nums">{line.qty}</TableCell>
                  <TableCell className="pr-6 text-xs text-muted-foreground">
                    {line.matched_on ? HOW_MATCHED[line.matched_on] : ''}
                  </TableCell>
                </TableRow>
              ),
            )}
          </TableBody>
        </Table>
        {order.unclear.map((question) => (
          <p key={question} className="px-6 text-sm text-amber-900 dark:text-amber-200">
            Ask the customer: {question}
          </p>
        ))}
      </CardContent>
    </Card>
  )
}

interface EditableLineProps {
  orderId: number
  line: OrderLine
  products: Product[]
  onChanged: () => void
}

/** One order line the owner can fix: choose the product, correct the quantity, or remove it. */
function EditableLine({ orderId, line, products, onChanged }: EditableLineProps) {
  const [sku, setSku] = useState(line.sku ?? '')
  const [qty, setQty] = useState(String(line.qty))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const options = useMemo(() => [...products].sort((a, b) => a.name.localeCompare(b.name)), [products])

  const qtyNumber = Number(qty)
  const qtyValid = Number.isInteger(qtyNumber) && qtyNumber > 0
  const changed = (sku && sku !== line.sku) || (qtyValid && qtyNumber !== line.qty)

  async function save(change: { sku?: string; qty?: number; remove?: boolean }) {
    setBusy(true)
    setError(null)
    try {
      await api.changeOrderLine(orderId, line.id, change)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <TableRow>
      <TableCell className="pl-6 align-top">
        “{line.written}”
        {line.matched_on && (
          <div className="text-xs text-muted-foreground">{HOW_MATCHED[line.matched_on] ?? line.matched_on}</div>
        )}
        {error && <p className="mt-1 text-xs text-destructive">{error.message}</p>}
      </TableCell>
      <TableCell className="align-top">
        <select
          aria-label={`Product for "${line.written}"`}
          value={sku}
          onChange={(event) => setSku(event.target.value)}
          className={`h-9 w-full max-w-xs rounded-md border bg-background px-2 text-sm ${sku ? '' : 'border-destructive'}`}
        >
          <option value="">Choose the product…</option>
          {options.map((product) => (
            <option key={product.sku} value={product.sku}>
              {product.name} ({product.sku})
            </option>
          ))}
        </select>
      </TableCell>
      <TableCell className="align-top">
        <Input
          aria-label={`Quantity for "${line.written}"`}
          value={qty}
          onChange={(event) => setQty(event.target.value)}
          inputMode="numeric"
          className="h-9 w-20"
        />
      </TableCell>
      <TableCell className="pr-6 align-top">
        <div className="flex gap-1">
          <Button
            size="sm"
            disabled={busy || !changed}
            onClick={() =>
              void save({
                ...(sku && sku !== line.sku ? { sku } : {}),
                ...(qtyValid && qtyNumber !== line.qty ? { qty: qtyNumber } : {}),
              })
            }
          >
            {busy ? <LoaderCircle className="animate-spin" /> : <Check />}
            Save
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            aria-label={`Remove "${line.written}"`}
            onClick={() => void save({ remove: true })}
          >
            <Trash2 />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}
