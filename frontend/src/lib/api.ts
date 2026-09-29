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

export interface StockUploadResult {
  upload: Upload
  issues_by_severity: Record<Severity, number>
  issues_by_type: Record<string, number>
  po_notes: PoNote[]
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

export const api = {
  uploadStockRegister(file: File): Promise<StockUploadResult> {
    const form = new FormData()
    form.append('file', file)
    return request('/uploads/stock', { method: 'POST', body: form })
  },
  products(): Promise<ProductList> {
    return request('/products')
  },
  issues(uploadId?: number): Promise<IssueList> {
    return request(uploadId ? `/issues?upload_id=${uploadId}` : '/issues')
  },
}
