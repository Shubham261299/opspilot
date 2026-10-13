import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import type { PolicyCitation } from '@/lib/api'

/**
 * The company-policy rules a proposal follows, each with what it did with the rule. The rules are
 * chosen by code, never by search, so they are what the checks really applied. The rule's own
 * wording opens underneath once the policy has been uploaded.
 */
export function PolicyCitations({ citations }: { citations: PolicyCitation[] }) {
  if (citations.length === 0) return null
  return (
    <div className="rounded-md border bg-muted/30 p-3 text-sm" aria-label="Policy rules followed">
      <p className="mb-2 text-xs text-muted-foreground">Policy rules followed</p>
      <ul className="space-y-1.5">
        {citations.map((citation) => (
          <li key={citation.code}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <Badge variant="outline" asChild>
                <Link to={`/policy#rule-${citation.code}`} title="Open this rule on the Policy page">
                  Policy {citation.code}
                </Link>
              </Badge>
              <span>{citation.why}</span>
            </div>
            {citation.text && (
              <details className="mt-1 pl-1 text-xs text-muted-foreground">
                <summary className="cursor-pointer">The rule{citation.section_title && ` · ${citation.section_title}`}</summary>
                <p className="mt-1 border-l-2 pl-2">{citation.text}</p>
              </details>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
