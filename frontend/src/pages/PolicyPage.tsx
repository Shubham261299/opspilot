import { LoaderCircle, Search } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '@/components/ErrorAlert'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useApi } from '@/hooks/useApi'
import { useReloadOn } from '@/hooks/useLive'
import { useScrollToHash } from '@/hooks/useScrollToHash'
import { api, type PolicyRule, type PolicySearchResult } from '@/lib/api'
import { formatDateTime, plural } from '@/lib/format'
import { cn } from '@/lib/utils'

const EXAMPLES = [
  'When should new orders be put on hold?',
  'Who has to approve a very large purchase order?',
  'Can the same supplier invoice be paid twice?',
  'What if a customer asks for something we do not stock?',
]

export function PolicyPage() {
  const { data, error, loading, reload } = useApi(api.policy)
  useReloadOn(['upload.finished', 'reconnected'], reload)
  const rules = data?.items ?? []
  useScrollToHash(rules.length > 0)

  const [found, setFound] = useState<PolicySearchResult | null>(null)
  const hitCodes = new Set(found?.items.map((hit) => hit.code))

  return (
    <>
      <PageHeader
        title="Company policy"
        description="The numbered rules the checks follow. Search them in your own words: the closest rules by meaning come first."
      />
      {error && <ErrorAlert error={error} title="Couldn't load the policy" />}
      {loading && !data && <Skeleton className="h-40 w-full" />}
      {data && rules.length === 0 && (
        <Card className="flex-row items-center justify-between gap-4 px-6 py-4">
          <p className="text-sm">No policy yet. Upload company_policy.pdf on the Upload page.</p>
          <Button asChild size="sm">
            <Link to="/upload">Upload</Link>
          </Button>
        </Card>
      )}
      {rules.length > 0 && (
        <div className="space-y-6">
          <PolicySearch onFound={setFound} />
          {found && <SearchResults found={found} />}
          <Rules rules={rules} highlighted={hitCodes} />
          <p className="text-xs text-muted-foreground">
            {plural(rules.length, 'rule')} · embedded with {data?.embedding_model}
            {data?.uploaded_at && ` · uploaded ${formatDateTime(data.uploaded_at)}`}
          </p>
        </div>
      )}
    </>
  )
}

function PolicySearch({ onFound }: { onFound: (result: PolicySearchResult | null) => void }) {
  const [question, setQuestion] = useState('')
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function search(text: string) {
    const trimmed = text.trim()
    if (trimmed.length < 3 || searching) return
    setSearching(true)
    setError(null)
    try {
      onFound(await api.searchPolicy(trimmed))
    } catch (err) {
      onFound(null)
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setSearching(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void search(question)
  }

  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-base">Ask the policy</CardTitle>
        <CardDescription>
          Your question and each rule are turned into lists of numbers by an embedding model; the rules whose numbers
          point the same way are the closest in meaning.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form onSubmit={submit} className="flex gap-2">
          <Input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="e.g. When should new orders be put on hold?"
            aria-label="Question about the policy"
            maxLength={300}
          />
          <Button type="submit" disabled={searching || question.trim().length < 3}>
            {searching ? <LoaderCircle className="animate-spin" /> : <Search />}
            Search
          </Button>
        </form>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <Button
              key={example}
              type="button"
              variant="outline"
              size="sm"
              disabled={searching}
              onClick={() => {
                setQuestion(example)
                void search(example)
              }}
            >
              {example}
            </Button>
          ))}
        </div>
        {error && <ErrorAlert error={error} title="The search didn't work" />}
      </CardContent>
    </Card>
  )
}

function SearchResults({ found }: { found: PolicySearchResult }) {
  return (
    <Card className="gap-3 border-primary/40">
      <CardHeader>
        <CardTitle className="text-base">Closest rules to “{found.query}”</CardTitle>
        <CardDescription>
          Similarity ranks the rules; it is not the chance that a rule answers the question. The closest rule is not
          always the one you need, so read the next ones too.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3">
          {found.items.map((hit, index) => (
            <li key={hit.code} className="flex gap-3 text-sm">
              <span className="w-4 shrink-0 text-muted-foreground tabular-nums">{index + 1}.</span>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" asChild>
                    <a href={`#rule-${hit.code}`}>Policy {hit.code}</a>
                  </Badge>
                  <span className="text-xs text-muted-foreground">{hit.section_title}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">similarity {hit.score.toFixed(2)}</span>
                </div>
                <p>{hit.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function Rules({ rules, highlighted }: { rules: PolicyRule[]; highlighted: Set<string> }) {
  const sections = new Map<number, { title: string; rules: PolicyRule[] }>()
  for (const rule of rules) {
    const section = sections.get(rule.section_no) ?? { title: rule.section_title, rules: [] }
    section.rules.push(rule)
    sections.set(rule.section_no, section)
  }
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {[...sections.entries()].map(([number, section]) => (
        <Card key={number} className="gap-3">
          <CardHeader>
            <CardTitle className="text-base">
              {number}. {section.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {section.rules.map((rule) => (
                <li
                  key={rule.code}
                  id={`rule-${rule.code}`}
                  className={cn(
                    'flex scroll-mt-4 gap-3 rounded-md p-2 text-sm',
                    highlighted.has(rule.code) && 'bg-primary/10 ring-1 ring-primary/40',
                  )}
                >
                  <span className="w-8 shrink-0 font-mono text-xs text-muted-foreground">{rule.code}</span>
                  <p>{rule.text}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
