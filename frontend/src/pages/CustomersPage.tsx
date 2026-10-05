import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApi } from '@/hooks/useApi'
import { api, type Customer } from '@/lib/api'
import { formatDate, formatRupees, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

export function CustomersPage() {
  const { data, error, loading } = useApi(api.customers)
  const [query, setQuery] = useState('')
  const customers = useMemo(() => search(data?.items ?? [], query), [data, query])

  const all = data?.items ?? []
  const onHold = all.filter((c) => c.on_hold).length
  const overLimit = all.filter((c) => Number(c.balance) > Number(c.credit_limit)).length

  return (
    <>
      <PageHeader
        title="Customers"
        description={
          data?.dues_upload_id
            ? `Balances from the dues file of ${formatDate(data.dues_as_of)} (upload #${data.dues_upload_id})`
            : 'Credit terms and unpaid balances'
        }
      />

      {error && <ErrorAlert error={error} title="Couldn't load the customers" />}

      {data && all.length === 0 && (
        <Card className="mb-6 flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">No customers yet. Upload customers.xlsx first.</p>
          <Button asChild size="sm">
            <Link to="/upload">Upload</Link>
          </Button>
        </Card>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search code, shop, person, area or phone"
            aria-label="Search customers"
            className="pl-8"
          />
        </div>
        {all.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {plural(all.length, 'customer')} · {onHold} on hold · {overLimit} over their credit limit
          </p>
        )}
      </div>

      {loading && !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Code</TableHead>
                <TableHead>Shop</TableHead>
                <TableHead>Mobile</TableHead>
                <TableHead className="text-right">Credit</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
                <TableHead>Oldest bill</TableHead>
                <TableHead className="pr-4">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {customers.map((customer) => (
                <CustomerRow key={customer.code} customer={customer} />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </>
  )
}

function CustomerRow({ customer }: { customer: Customer }) {
  const over = Number(customer.balance) > Number(customer.credit_limit)
  return (
    <TableRow>
      <TableCell className="pl-4 font-mono text-xs">{customer.code}</TableCell>
      <TableCell className="whitespace-normal">
        <div className="font-medium">{customer.shop_name}</div>
        <div className="text-xs text-muted-foreground">
          {[customer.contact_person, customer.area].filter(Boolean).join(' · ')}
        </div>
      </TableCell>
      <TableCell className="text-xs tabular-nums">{customer.phone ?? '—'}</TableCell>
      <TableCell className="text-right text-xs tabular-nums">
        {formatRupees(customer.credit_limit)}
        <div className="text-muted-foreground">{customer.credit_days} days</div>
      </TableCell>
      <TableCell className={cn('text-right tabular-nums', over && 'font-semibold text-destructive')}>
        {Number(customer.balance) > 0 ? formatRupees(customer.balance) : '—'}
        {customer.open_bills > 0 && (
          <div className="text-xs font-normal text-muted-foreground">{plural(customer.open_bills, 'bill')}</div>
        )}
      </TableCell>
      <TableCell className="text-xs">{formatDate(customer.oldest_bill_date)}</TableCell>
      <TableCell className="pr-4">
        {customer.on_hold ? (
          <Badge variant="destructive" title={customer.hold_reason ?? undefined}>
            On hold
          </Badge>
        ) : (
          <Badge variant="outline">OK</Badge>
        )}
      </TableCell>
    </TableRow>
  )
}

function search(customers: Customer[], query: string): Customer[] {
  const q = query.trim().toLowerCase()
  if (!q) return customers
  return customers.filter((c) =>
    [c.code, c.shop_name, c.contact_person, c.area, c.phone].some((field) => field?.toLowerCase().includes(q)),
  )
}
