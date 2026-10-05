import type { Issue, Severity } from '@/lib/api'

export const SEVERITIES: Severity[] = ['error', 'warning', 'info']

export const SEVERITY_MEANING: Record<Severity, string> = {
  error: 'not loaded',
  warning: 'loaded, but check it',
  info: 'handled automatically',
}

// Plain-English names for the issue types the backend reports (app/intake/issues.py).
const ISSUE_TYPE_LABELS: Record<string, string> = {
  unknown_item: 'Unknown item',
  code_name_mismatch: 'Item code and name disagree',
  negative_qty: 'Negative quantity',
  invalid_qty: 'Unusable quantity',
  unknown_unit: 'Unknown unit',
  unit_mismatch: 'Unit differs from the product master',
  blank_code: 'Blank item code',
  duplicate_row: 'Duplicate row',
  blank_rate: 'Blank rate',
  invalid_rate: 'Rate is not a number',
  rate_mismatch: 'Rate differs from the product master',
  blank_unit: 'Blank unit',
  unknown_supplier: 'Unknown supplier',
  supplier_mismatch: 'Supplier differs from the product master',
  unclear_po_remark: 'Unclear order remark',
  missing_from_register: 'Missing from the count',
  count_date_missing: 'No count date',
  skipped_row: 'Skipped rows (titles, headings, totals)',
  units_normalised: 'Unit spellings normalised',
  qty_as_text: 'Quantity typed as text',
  name_format: 'Name formatting',
  supplier_short_name: 'Supplier short name',
  open_po_note: 'Open purchase order in remarks',
  other_sheet: 'Other sheets not imported',
  duplicate_customer: 'Likely duplicate customer',
  missing_customer_code: 'No party code',
  missing_shop_name: 'No shop name',
  invalid_credit_terms: 'Missing or invalid credit terms',
  unknown_customer: 'Unknown customer',
  invalid_bill: 'Unreadable bill',
  invalid_sale: 'Unreadable sale',
  invalid_phone: 'Invalid mobile number',
  balance_mismatch: "Balance doesn't add up",
  future_bill_date: 'Bill dated in the future',
  amount_mismatch: "Amount doesn't add up",
  phones_normalised: 'Mobile number formats normalised',
  party_by_name: 'Parties written by shop name',
  dates_as_text: 'Dates typed as text',
  blank_received: 'Blank received amounts',
  paid_bill: 'Fully paid bills skipped',
}

export function issueTypeLabel(issueType: string): string {
  return ISSUE_TYPE_LABELS[issueType] ?? issueType.replaceAll('_', ' ')
}

export interface IssueGroup {
  issueType: string
  label: string
  severity: Severity
  issues: Issue[]
}

/** Group issues by type: errors first, then warnings, then info; file order inside a group. */
export function groupIssues(issues: Issue[]): IssueGroup[] {
  const groups = new Map<string, IssueGroup>()
  for (const issue of issues) {
    const group = groups.get(issue.issue_type)
    if (group) {
      group.issues.push(issue)
    } else {
      groups.set(issue.issue_type, {
        issueType: issue.issue_type,
        label: issueTypeLabel(issue.issue_type),
        severity: issue.severity,
        issues: [issue],
      })
    }
  }
  return [...groups.values()].sort(
    (a, b) => SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity) || a.label.localeCompare(b.label),
  )
}
