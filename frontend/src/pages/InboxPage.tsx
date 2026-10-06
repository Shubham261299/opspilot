import { Check, CircleCheck, Info, LoaderCircle, RefreshCw, Sparkles, X } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useApi } from '@/hooks/useApi'
import { api, type Proposal, type ProposalKind, type RunChecksResult } from '@/lib/api'
import { formatDate, formatDateTime, formatRupees, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

const KINDS: { kind: ProposalKind; title: string; approveLabel: string }[] = [
  { kind: 'confirm_order', title: 'Customer orders (WhatsApp)', approveLabel: 'Confirm order' },
  { kind: 'reorder', title: 'Reorders', approveLabel: 'Approve purchase order' },
  { kind: 'hold_orders', title: 'Hold new orders', approveLabel: 'Approve hold' },
  { kind: 'payment_reminder', title: 'Payment reminders', approveLabel: 'Approve reminder' },
]

type Tab = 'pending' | 'history'

export function InboxPage() {
  const [tab, setTab] = useState<Tab>('pending')
  return (
    <>
      <PageHeader
        title="Approval Inbox"
        description="OpsPilot proposes; you decide. Nothing is ordered, held or sent until you approve it."
      />
      <div className="mb-6 inline-flex rounded-lg border bg-background p-1" role="tablist">
        {(['pending', 'history'] as const).map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              'rounded-md px-4 py-1.5 text-sm font-medium text-muted-foreground',
              tab === value && 'bg-muted text-foreground',
            )}
          >
            {value === 'pending' ? 'Waiting for you' : 'History'}
          </button>
        ))}
      </div>
      {tab === 'pending' ? <PendingTab /> : <HistoryTab />}
    </>
  )
}

// Pending ------------------------------------------------------------------------------

const loadPending = () => api.proposals('pending')

function PendingTab() {
  const { data, error, loading, reload } = useApi(loadPending)
  const [running, setRunning] = useState(false)
  const [run, setRun] = useState<RunChecksResult | null>(null)
  const [runError, setRunError] = useState<Error | null>(null)
  const [lastDecision, setLastDecision] = useState<Proposal | null>(null)

  async function runChecks() {
    setRunning(true)
    setRunError(null)
    try {
      setRun(await api.runChecks())
      reload()
    } catch (err) {
      setRunError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setRunning(false)
    }
  }

  const onDecided = useCallback(
    (proposal: Proposal) => {
      setLastDecision(proposal)
      reload()
    },
    [reload],
  )

  const items = useMemo(() => data?.items ?? [], [data])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void runChecks()} disabled={running}>
          {running ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
          Run checks
        </Button>
        <p className="text-sm text-muted-foreground">
          Applies the reorder and credit rules to the latest uploads.
        </p>
      </div>

      {runError && <ErrorAlert error={runError} title="Checks didn't run" />}
      {run && <RunSummary run={run} />}
      {lastDecision && <DecisionDone proposal={lastDecision} />}
      {error && <ErrorAlert error={error} title="Couldn't load the inbox" />}
      {loading && !data && <Skeleton className="h-40 w-full" />}

      {data && items.length === 0 && (
        <Card className="px-6 py-8 text-center text-sm text-muted-foreground">
          Nothing is waiting for a decision. Upload the files, then press <strong>Run checks</strong>.
        </Card>
      )}

      {KINDS.map(({ kind, title, approveLabel }) => {
        const group = items.filter((p) => p.kind === kind)
        if (group.length === 0) return null
        return (
          <section key={kind} className="space-y-3">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              {title}
              <Badge variant="outline" className="tabular-nums">
                {group.length}
              </Badge>
            </h2>
            <div className="grid gap-4 lg:grid-cols-2">
              {group.map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  approveLabel={approveLabel}
                  onDecided={onDecided}
                  onStale={reload}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function RunSummary({ run }: { run: RunChecksResult }) {
  return (
    <Alert>
      <Info />
      <AlertTitle>
        Checks done: {plural(run.pending, 'proposal')} waiting for you
      </AlertTitle>
      <AlertDescription>
        <p>
          {run.created} new · {run.unchanged} unchanged · {run.superseded} replaced by newer data
          {run.already_decided > 0 && ` · ${run.already_decided} not asked again (already decided)`}
        </p>
        {run.not_checked.map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
      </AlertDescription>
    </Alert>
  )
}

function DecisionDone({ proposal }: { proposal: Proposal }) {
  const what =
    proposal.status === 'rejected'
      ? 'Rejected. Nothing was changed.'
      : proposal.kind === 'confirm_order'
        ? 'Confirmed: the order is ready to dispatch.'
        : proposal.purchase_order_id
        ? `Approved: purchase order #${proposal.purchase_order_id} created.`
        : proposal.payment_reminder_id
          ? 'Approved: the reminder is ready to send.'
          : `Approved: new orders from ${proposal.subject.name} are on hold.`
  return (
    <Alert>
      <CircleCheck />
      <AlertTitle>
        {proposal.subject.code} {proposal.subject.name}
      </AlertTitle>
      <AlertDescription>{what} Recorded in the audit log.</AlertDescription>
    </Alert>
  )
}

interface ProposalCardProps {
  proposal: Proposal
  approveLabel: string
  onDecided: (proposal: Proposal) => void
  onStale: () => void
}

function ProposalCard({ proposal, approveLabel, onDecided, onStale }: ProposalCardProps) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<Error | null>(null)

  async function decide(action: 'approve' | 'reject') {
    setBusy(action)
    setError(null)
    try {
      onDecided(await (action === 'approve' ? api.approve : api.reject)(proposal.id, note))
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
      setBusy(null)
      onStale() // e.g. someone else decided it first: refresh the list
    }
  }

  const n = proposal.numbers
  const notReady = proposal.kind === 'confirm_order' && !n.ready
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <span className="font-mono text-sm">{proposal.subject.code}</span>
          {proposal.subject.name}
          {n.needs_owner && (
            <Badge className="bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">
              Owner approval
            </Badge>
          )}
        </CardTitle>
        <Explanation proposal={proposal} />
      </CardHeader>
      <CardContent className="space-y-3">
        {proposal.kind === 'reorder' && <ReorderNumbers proposal={proposal} />}
        {(proposal.kind === 'payment_reminder' || proposal.kind === 'hold_orders') && (
          <CreditNumbers proposal={proposal} />
        )}
        {proposal.kind === 'confirm_order' && <OrderLines proposal={proposal} />}
        {proposal.draft_message && (
          <div className="rounded-md border bg-muted/30 p-3 text-sm">
            <p className="mb-1 text-xs text-muted-foreground">Message to the customer, sent when approved:</p>
            <p>{proposal.draft_message}</p>
          </div>
        )}
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3">
        {error && <ErrorAlert error={error} title="Not saved" />}
        {notReady && (
          <p className="text-sm text-muted-foreground">
            Some lines need a product before the order can be confirmed.{' '}
            <Link to={`/orders#order-${proposal.order_id}`} className="underline">
              Fix them on the Orders page
            </Link>
            , or reject it.
          </p>
        )}
        <Input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Note (optional), e.g. why you reject it"
          aria-label={`Note for ${proposal.subject.code}`}
          maxLength={500}
        />
        <div className="flex gap-2">
          <Button onClick={() => void decide('approve')} disabled={busy !== null || notReady} className="flex-1">
            {busy === 'approve' ? <LoaderCircle className="animate-spin" /> : <Check />}
            {approveLabel}
          </Button>
          <Button variant="outline" onClick={() => void decide('reject')} disabled={busy !== null}>
            {busy === 'reject' ? <LoaderCircle className="animate-spin" /> : <X />}
            Reject
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}

/** The language model's wording when it passed the checks; the code's calculation is always there. */
function Explanation({ proposal }: { proposal: Proposal }) {
  if (proposal.explained_by !== 'llm' || !proposal.explanation) {
    return (
      <CardDescription>
        {proposal.reason}
        {proposal.explained_by === null && (
          <span className="mt-1 flex items-center gap-1 text-xs">
            <LoaderCircle className="size-3 animate-spin" aria-hidden /> The language model is writing an
            explanation…
          </span>
        )}
      </CardDescription>
    )
  }
  return (
    <div className="space-y-1 text-sm">
      <p>{proposal.explanation}</p>
      <p className="flex items-center gap-1 text-xs text-muted-foreground">
        <Sparkles className="size-3" aria-hidden /> Written by AI · every number checked against the calculation
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">The calculation</summary>
        <p className="mt-1">{proposal.reason}</p>
      </details>
    </div>
  )
}

function OrderLines({ proposal }: { proposal: Proposal }) {
  const n = proposal.numbers
  return (
    <div className="space-y-2 text-sm">
      <ul className="divide-y rounded-md border">
        {(n.lines ?? []).map((line) => (
          <li key={line.line_id} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
            <span>
              <span className="tabular-nums font-medium">{line.qty}</span>{' '}
              {line.sku ? (
                <>
                  {line.name} <span className="font-mono text-xs text-muted-foreground">{line.sku}</span>
                </>
              ) : (
                <span className="text-destructive">“{line.written}”: no product yet</span>
              )}
            </span>
            <span className="text-xs text-muted-foreground">
              {line.matched_on === 'model' ? 'matched by AI, check it' : line.sku ? `“${line.written}”` : ''}
            </span>
          </li>
        ))}
      </ul>
      {n.est_value && (
        <p className="text-muted-foreground">About {formatRupees(n.est_value)} at list prices.</p>
      )}
      {n.customer_on_hold && (
        <Badge variant="destructive">Customer on hold: dispatch needs the owner (policy 2.4)</Badge>
      )}
      {(n.unclear ?? []).map((question) => (
        <p key={question} className="text-amber-900 dark:text-amber-200">
          Ask the customer: {question}
        </p>
      ))}
    </div>
  )
}

function ReorderNumbers({ proposal }: { proposal: Proposal }) {
  const n = proposal.numbers
  return (
    <dl className="grid grid-cols-3 gap-2 text-sm">
      <Figure label="On hand + on order" value={`${n.on_hand} + ${n.on_order}`} />
      <Figure label="Sold a day" value={n.avg_daily} />
      <Figure label="Reorder point" value={n.reorder_point} />
      <Figure label="Order" value={`${n.qty} ${n.unit}${n.qty === 1 ? '' : 's'}`} strong />
      <Figure label="Estimated cost" value={n.est_cost ? formatRupees(n.est_cost) : '—'} strong />
      <Figure label="Supplier" value={n.supplier_name} />
    </dl>
  )
}

function CreditNumbers({ proposal }: { proposal: Proposal }) {
  const n = proposal.numbers
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <Figure label="Outstanding" value={n.total_balance ? formatRupees(n.total_balance) : '—'} strong />
        <Figure label="Credit limit" value={n.credit_limit ? formatRupees(n.credit_limit) : '—'} />
        <Figure label="Most overdue" value={`${n.max_days_overdue ?? 0} days`} strong />
      </dl>
      {n.overdue_bills && n.overdue_bills.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {n.overdue_bills.map((bill) => (
            <li key={bill.bill_no}>
              {bill.bill_no} of {formatDate(bill.bill_date)}: {formatRupees(bill.balance)},{' '}
              {plural(bill.days_overdue, 'day')} overdue
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Figure({ label, value, strong }: { label: string; value: string | number | undefined; strong?: boolean }) {
  return (
    <div className="rounded-md bg-muted/40 p-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular-nums', strong && 'font-semibold')}>{value ?? '—'}</dd>
    </div>
  )
}

// History ------------------------------------------------------------------------------

const loadHistory = async (): Promise<Proposal[]> => {
  const [approved, rejected] = await Promise.all([api.proposals('approved'), api.proposals('rejected')])
  return [...approved.items, ...rejected.items].sort((a, b) =>
    (b.decided_at ?? '').localeCompare(a.decided_at ?? ''),
  )
}

function HistoryTab() {
  const { data, error, loading } = useApi(loadHistory)
  if (error) return <ErrorAlert error={error} title="Couldn't load the history" />
  if (loading && !data) return <Skeleton className="h-40 w-full" />
  if (!data || data.length === 0) {
    return (
      <Card className="px-6 py-8 text-center text-sm text-muted-foreground">
        No decisions yet. They appear here, newest first, once you approve or reject a proposal.
      </Card>
    )
  }
  return (
    <div className="space-y-3">
      {data.map((proposal) => (
        <Card key={proposal.id} className="gap-2 py-4">
          <CardHeader className="px-4">
            <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
              <Badge
                className={
                  proposal.status === 'approved'
                    ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200'
                    : 'bg-muted text-foreground'
                }
              >
                {proposal.status === 'approved' ? 'Approved' : 'Rejected'}
              </Badge>
              {KINDS.find((k) => k.kind === proposal.kind)?.title}
              <span className="font-mono text-xs">{proposal.subject.code}</span>
              {proposal.subject.name}
              <span className="ml-auto text-xs font-normal text-muted-foreground">
                {proposal.decided_at && formatDateTime(proposal.decided_at)} by {proposal.decided_by}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 px-4 text-sm">
            {proposal.decision_note && <p>Note: “{proposal.decision_note}”</p>}
            {proposal.purchase_order_id && (
              <p>
                Purchase order #{proposal.purchase_order_id}: {proposal.numbers.qty} {proposal.numbers.unit}s from{' '}
                {proposal.numbers.supplier_name}
                {proposal.numbers.est_cost && `, ${formatRupees(proposal.numbers.est_cost)}`}
              </p>
            )}
            {proposal.reminder_message && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">Reminder ready to send</summary>
                <p className="mt-1 rounded-md bg-muted/40 p-2">{proposal.reminder_message}</p>
              </details>
            )}
            {proposal.kind === 'hold_orders' && proposal.status === 'approved' && (
              <p>
                New orders are on hold. <Link to="/customers">See customers</Link>
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
