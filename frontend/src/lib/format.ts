// Display formatting (Indian conventions). These only change how values look, never
// the values themselves; all calculations happen in the backend.

const dateFormat = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
const rupeeFormat = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })

/** "2026-09-24" -> "24 Sept 2026". Built from its parts, so no timezone can shift the day. */
export function formatDate(isoDate: string | null): string {
  if (!isoDate) return '—'
  const [year, month, day] = isoDate.split('-').map(Number)
  return dateFormat.format(new Date(year, month - 1, day))
}

export function formatDateTime(isoDateTime: string): string {
  return dateTimeFormat.format(new Date(isoDateTime))
}

/** "1150.00" -> "₹1,150.00" (Indian digit grouping: ₹1,15,000.00). */
export function formatRupees(amount: string): string {
  return rupeeFormat.format(Number(amount))
}

/** plural(1, 'issue') -> "1 issue", plural(3, 'issue') -> "3 issues" */
export function plural(count: number, word: string, pluralWord = `${word}s`): string {
  return `${count} ${count === 1 ? word : pluralWord}`
}
