"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { StatusBadge, StudyCategoryBadge } from "@/components/domain";
import { Alert, Button, Card, EmptyState, Input } from "@/components/ui";
import { api } from "@/lib/api";
import type { TrialSummary } from "@/lib/types";

interface SearchResult {
  query: string;
  recognized_concepts: string[];
  expanded_terms: string[];
  drug_terms: string[];
  data_source: string;
  results: TrialSummary[];
}

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setRes(await api.get<SearchResult>(`/api/trials/search?q=${encodeURIComponent(q)}&include_inactive=${inactive}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Explore</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Search all studies</h1>
        <p className="mt-1 text-sm text-muted">Search in your own words — we add the medical terms researchers use. Open a study to see how it fits your profile.</p>
      </div>
      <form onSubmit={run} className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input className="h-12 pl-9 text-base" placeholder='Try "high Lp(a)", "heart attack" or "olpasiran"' value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Button size="lg" loading={busy}>Search</Button>
      </form>
      <label className="flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" className="size-4 accent-brand-600" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Include studies that are no longer recruiting
      </label>
      {error && <Alert tone="danger">{error}</Alert>}
      {res && (
        <Card className="p-4 text-sm">
          <p>
            {res.recognized_concepts.length ? <>Recognized <strong className="font-medium">{res.recognized_concepts.join(", ")}</strong>. </> : null}
            Also searched: <span className="text-ink-soft">{res.expanded_terms.slice(1).join(" · ") || "—"}</span>
            {res.drug_terms.length > 0 && <> and treatments <span className="text-ink-soft">{res.drug_terms.join(" · ")}</span></>}.
          </p>
        </Card>
      )}
      {res?.results.length === 0 && <EmptyState title="No studies found">Try a broader term.</EmptyState>}
      <div className="grid gap-3">
        {res?.results.map((t) => (
          <Link key={t.nct_id} href={`/app/trials/${t.nct_id}`}>
            <Card className="p-5 transition-shadow hover:shadow-[var(--shadow-lift)]">
              <div className="flex flex-wrap gap-2">
                <StatusBadge status={t.status} label={t.status_label} />
                <StudyCategoryBadge category={t.study_category} />
              </div>
              <p className="mt-2 font-semibold leading-snug">{t.acronym ? `${t.acronym} · ` : ""}{t.title}</p>
              <p className="mt-1 text-sm text-muted">{t.phase_label} · {t.sponsor} · {t.conditions.slice(0, 3).join(", ")}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
