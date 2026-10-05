// The one place that talks to the backend. Every response has a TypeScript type that
// mirrors the API's Pydantic schema (backend/app/api/schemas.py).
//
// The browser always calls /api/...: in development Vite forwards it to FastAPI, and in
// Docker nginx does. So there is one address and no CORS setup.

export type Severity = 'error' | 'warning' | 'info'

export interface Upload {
  id: number
  kind: string
  filename: string
  status: 'processed' | 'failed'
  as_of: string | null // count date, "2026-09-24"
  rows_read: number
  rows_loaded: number
  error: string | null
  created_at: string // ISO date and time
}

export interface PoNote {
  sku: string
  supplier_code: string | null
  qty: number
  ordered_on: string | null
  note: string
  source_row: number
}

/** What every upload endpoint answers; each kind of file adds a few fields. */
export interface UploadSummary {
  upload: Upload
  issues_by_severity: Record<Severity, number>
  issues_by_type: Record<string, number>
}

export interface StockUploadResult extends UploadSummary {
  po_notes: PoNote[]
}

export interface CustomersUploadResult extends UploadSummary {
  added: string[] // party codes added by this file
  updated: string[] // party codes whose details changed
}

export interface DuesUploadResult extends UploadSummary {
  bills_loaded: number
  total_balance: string
}

export interface SalesUploadResult extends UploadSummary {
  lines_loaded: number
  last_sale: string | null
}

export interface UploadList {
  items: Upload[]
}

export interface Customer {
  code: string
  shop_name: string
  contact_person: string | null
  phone: string | null // "+919895822412"
  area: string | null
  credit_limit: string
  credit_days: number
  on_hold: boolean
  hold_reason: string | null
  balance: string // unpaid total in the current dues file
  open_bills: number
  oldest_bill_date: string | null
}

export interface CustomerList {
  dues_upload_id: number | null
  dues_as_of: string | null
  items: Customer[]
}

export type ProposalKind = 'reorder' | 'payment_reminder' | 'hold_orders'
export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'superseded'

export interface OverdueBill {
  bill_no: string
  bill_date: string
  balance: string
  days_overdue: number
}

/** The calculated figures behind a proposal. Which ones are present depends on the kind. */
export interface ProposalNumbers {
  // reorder
  on_hand?: number
  on_order?: number
  avg_daily?: string
  lead_time_days?: number
  reorder_point?: string
  days_of_cover?: string | null
  qty?: number
  pack_size?: number
  unit?: string
  unit_cost?: string
  est_cost?: string
  needs_owner?: boolean
  supplier_code?: string
  supplier_name?: string
  // payment_reminder, hold_orders
  total_balance?: string
  credit_limit?: string
  credit_days?: number
  over_limit?: boolean
  max_days_overdue?: number
  overdue_bills?: OverdueBill[]
}

export interface Proposal {
  id: number
  kind: ProposalKind
  status: ProposalStatus
  subject: { type: 'product' | 'customer'; code: string; name: string }
  numbers: ProposalNumbers
  reason: string
  basis: Record<string, unknown>
  created_at: string
  decided_at: string | null
  decided_by: string | null
  decision_note: string | null
  purchase_order_id: number | null
  payment_reminder_id: number | null
  reminder_message: string | null
}

export interface ProposalList {
  items: Proposal[]
}

export interface RunChecksResult {
  created: number
  unchanged: number
  superseded: number
  already_decided: number
  pending: number
  not_checked: string[]
}

export interface Product {
  sku: string
  name: string
  aliases: string[]
  unit: string
  pack_size: number
  cost_price: string // money arrives as exact text, e.g. "1150.00"
  sell_price: string
  supplier: { code: string; name: string }
  qty_on_hand: number | null // null: the current count has no usable number
  on_order_qty: number
  remarks: string | null
  open_issue_count: number
}

export interface ProductList {
  stock_upload_id: number | null
  as_of: string | null
  items: Product[]
}

export interface Issue {
  id: number
  source_file: string
  source_row: number | null // null: about the whole file
  issue_type: string
  severity: Severity
  detail: string
  sku: string | null
  product_name: string | null
  customer_code: string | null
  customer_name: string | null
  raw: Record<string, unknown> | null
  resolved: boolean
}

export interface IssueList {
  upload: Upload | null
  items: Issue[]
}

/** An error answer from the API: {"error": {"code", "message", "request_id", "details"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null
  readonly details: unknown

  constructor(message: string, status: number, code: string, requestId: string | null, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

interface ErrorBody {
  error: { code: string; message: string; request_id?: string | null; details?: unknown }
}

function isErrorBody(body: unknown): body is ErrorBody {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = (body as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'message' in error
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('x-request-id')
  try {
    const body: unknown = await response.json()
    if (isErrorBody(body)) {
      const { code, message, request_id, details } = body.error
      return new ApiError(message, response.status, code, request_id ?? requestId, details)
    }
  } catch {
    // Not JSON (for example an HTML error page from a proxy); fall through.
  }
  return new ApiError(
    `The server answered ${response.status} ${response.statusText}.`,
    response.status,
    'http_error',
    requestId,
  )
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError('Could not reach the server. Is the API running?', 0, 'network_error', null)
  }
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

export type UploadKind = 'stock' | 'customers' | 'dues' | 'sales'

function upload<T>(kind: UploadKind, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  return request(`/uploads/${kind}`, { method: 'POST', body: form })
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export const api = {
  uploadStockRegister: (file: File) => upload<StockUploadResult>('stock', file),
  uploadCustomers: (file: File) => upload<CustomersUploadResult>('customers', file),
  uploadDues: (file: File) => upload<DuesUploadResult>('dues', file),
  uploadSales: (file: File) => upload<SalesUploadResult>('sales', file),
  uploads(): Promise<UploadList> {
    return request('/uploads')
  },
  products(): Promise<ProductList> {
    return request('/products')
  },
  customers(): Promise<CustomerList> {
    return request('/customers')
  },
  issues(uploadId?: number): Promise<IssueList> {
    return request(uploadId ? `/issues?upload_id=${uploadId}` : '/issues')
  },
  proposals(status: ProposalStatus): Promise<ProposalList> {
    return request(`/proposals?status=${status}`)
  },
  runChecks(): Promise<RunChecksResult> {
    return postJson('/proposals/run')
  },
  approve(id: number, note?: string): Promise<Proposal> {
    return postJson(`/proposals/${id}/approve`, { note: note || null })
  },
  reject(id: number, note?: string): Promise<Proposal> {
    return postJson(`/proposals/${id}/reject`, { note: note || null })
  },
}
