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
import { api, type Product } from '@/lib/api'
import { formatDate, formatRupees, plural } from '@/lib/format'

export function StockPage() {
  const { data, error, loading } = useApi(api.products)
  const [query, setQuery] = useState('')
  const products = useMemo(() => search(data?.items ?? [], query), [data, query])

  const all = data?.items ?? []
  const counted = data?.stock_upload_id != null
  const needRecount = all.filter((p) => p.qty_on_hand === null).length
  const onOrder = all.filter((p) => p.on_order_qty > 0).length

  return (
    <>
      <PageHeader
        title="Stock"
        description={
          counted
            ? `Godown count of ${formatDate(data?.as_of ?? null)} (upload #${data?.stock_upload_id})`
            : 'Current stock from the latest stock register upload'
        }
      />

      {error && <ErrorAlert error={error} title="Couldn't load the stock" />}

      {data && !counted && (
        <Card className="mb-6 flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">No stock count yet. Upload the stock register to fill in the quantities.</p>
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
            placeholder="Search code, name, alias or supplier"
            aria-label="Search products"
            className="pl-8"
          />
        </div>
        {data && (
          <p className="text-sm text-muted-foreground">
            {all.length - needRecount} of {plural(all.length, 'product')} counted
            {counted && needRecount > 0 && ` · ${needRecount} ${needRecount === 1 ? 'needs' : 'need'} a recount`}
            {onOrder > 0 && ` · ${onOrder} on order`}
          </p>
        )}
      </div>

      <Card className="py-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Code</TableHead>
              <TableHead>Product</TableHead>
              <TableHead>Supplier</TableHead>
              <TableHead className="text-right">On hand</TableHead>
              <TableHead className="text-right">On order</TableHead>
              <TableHead className="text-right">Cost / Sale</TableHead>
              <TableHead className="pr-4">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && <LoadingRows />}
            {data && products.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  No product matches “{query}”.
                </TableCell>
              </TableRow>
            )}
            {products.map((product) => (
              <TableRow key={product.sku}>
                <TableCell className="pl-4 font-mono text-xs">{product.sku}</TableCell>
                <TableCell className="whitespace-normal">
                  <div className="font-medium">{product.name}</div>
                  {product.remarks && <div className="text-xs text-muted-foreground">Remark: {product.remarks}</div>}
                </TableCell>
                <TableCell className="text-muted-foreground">{product.supplier.name}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {product.qty_on_hand ?? '—'} <span className="text-xs text-muted-foreground">{product.unit}</span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{product.on_order_qty || '—'}</TableCell>
                <TableCell className="text-right text-xs text-muted-foreground tabular-nums">
                  {formatRupees(product.cost_price)} / {formatRupees(product.sell_price)}
                </TableCell>
                <TableCell className="pr-4">
                  <StockStatus product={product} counted={counted} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  )
}

function StockStatus({ product, counted }: { product: Product; counted: boolean }) {
  if (!counted) return <span className="text-muted-foreground">Not counted</span>
  if (product.qty_on_hand === null) {
    return <Badge className="bg-destructive/10 text-destructive">Needs recount</Badge>
  }
  if (product.open_issue_count > 0) {
    return (
      <Badge asChild className="bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">
        <Link to="/issues">Check {plural(product.open_issue_count, 'issue')}</Link>
      </Badge>
    )
  }
  return <Badge variant="secondary">OK</Badge>
}

function LoadingRows() {
  return Array.from({ length: 8 }, (_, row) => (
    <TableRow key={row}>
      <TableCell colSpan={7} className="px-4">
        <Skeleton className="h-5 w-full" />
      </TableCell>
    </TableRow>
  ))
}

/** Every word must appear in the code, name, supplier or an alias ("gitti" finds wall plugs). */
function search(products: Product[], query: string): Product[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return products
  return products.filter((product) => {
    const text = [product.sku, product.name, product.supplier.name, product.supplier.code, ...product.aliases]
      .join(' ')
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
}
