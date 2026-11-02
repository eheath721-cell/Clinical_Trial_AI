"use client";

import { ArrowRight, GitCompareArrows, Info, RefreshCw, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { CLASSIFICATION, DataSourceNote } from "@/components/domain";
import { TrialCard } from "@/components/trial-card";
import { Alert, Button, buttonVariants, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useMatches, useProfile } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Classification, RefreshSummary } from "@/lib/types";
import { cn, pluralize } from "@/lib/utils";

const PHASES = [["PHASE1", "Phase 1"], ["PHASE2", "Phase 2"], ["PHASE3", "Phase 3"], ["PHASE4", "Phase 4"], ["NA", "N/A (observational)"]];
const STATUSES = [["RECRUITING", "Recruiting"], ["NOT_YET_RECRUITING", "Not yet recruiting"], ["ENROLLING_BY_INVITATION", "By invitation"], ["ACTIVE_NOT_RECRUITING", "Active, not recruiting"]];
const CATEGORIES = [["biomarker", "Biomarker-lowering"], ["cv_outcomes", "Cardiovascular outcomes"], ["imaging", "Imaging"], ["early_safety", "Early-phase safety"], ["observational", "Observational / registry"], ["other", "Other"]];

function Dashboard() {
  const router = useRouter();
  const params = useSearchParams();
  const { activeProfileId } = useSession();
  const { data: profile } = useProfile(activeProfileId);
  const [classes, setClasses] = useState<Classification[]>([]);
  const [phase, setPhase] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [distance, setDistance] = useState("");
  const [intervention, setIntervention] = useState("");
  const [sort, setSort] = useState("relevance");
  const [compare, setCompare] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [summary, setSummary] = useState<RefreshSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const autoRan = useRef<string | null>(null);

  const query = useMemo(() => {
    const q = new URLSearchParams();
    classes.forEach((c) => q.append("classification", c));
    if (phase) q.append("phase", phase);
    if (status) q.append("status", status);
    if (category) q.append("category", category);
    if (distance) q.set("max_distance", distance);
    if (intervention) q.set("intervention", intervention);
    q.set("sort", sort);
    return q.toString();
  }, [classes, phase, status, category, distance, intervention, sort]);

  const { data, isLoading, mutate } = useMatches(activeProfileId, query);
  const { data: all, mutate: mutateAll } = useMatches(activeProfileId, "include_inactive=true");

  async function refresh() {
    if (!activeProfileId) return;
    setRefreshing(true);
    setError(null);
    try {
      const s = await api.post<RefreshSummary>(`/api/profiles/${activeProfileId}/matches/refresh`);
      setSummary(s);
      await Promise.all([mutate(), mutateAll()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!activeProfileId || !all || autoRan.current === activeProfileId) return;
    if (params.get("refresh") === "1" || all.total === 0) {
      autoRan.current = activeProfileId;
      refresh().then(() => router.replace("/app/trials"));
    } else {
      autoRan.current = activeProfileId;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProfileId, all]);

  async function toggleSave(nct: string, saved: boolean) {
    if (!activeProfileId) return;
    if (saved) await api.del(`/api/profiles/${activeProfileId}/saved/${nct}`);
    else await api.post(`/api/profiles/${activeProfileId}/saved`, { nct_id: nct });
    mutate();
  }

  const inactiveHidden = (all?.total ?? 0) - (all?.items.filter((i) => ["RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"].includes(i.trial.status)).length ?? 0);
  const counts = data?.facets.classification ?? {};

  if (!activeProfileId) {
    return (
      <EmptyState title="Create a health profile to see matches" action={<Link href="/app/onboarding" className={buttonVariants()}>Get started</Link>}>
        Matches are personalized to a profile — yours or someone you care for.
      </EmptyState>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-brand-600">{profile?.display_name ?? "Your"} trial matches</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
            {data ? pluralize(data.total, "study", "studies") + " to review" : "Finding studies…"}
          </h1>
          <p className="mt-1 text-sm text-muted">
            Ranked by topic match, how well your information fits the criteria, recruitment status and distance{profile?.city ? ` from ${profile.city}, ${profile.state}` : ""}.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/app/profile" className={buttonVariants({ variant: "secondary" })}>Improve my profile</Link>
          <Button variant="secondary" onClick={refresh} loading={refreshing}>
            {!refreshing && <RefreshCw />} Search again
          </Button>
        </div>
      </div>

      <DataSourceNote source={data?.source} />
      {error && <Alert tone="danger" title="Couldn't search the registry">{error}</Alert>}

      <div className="grid grid-cols-3 gap-3">
        {(Object.keys(CLASSIFICATION) as Classification[]).map((c) => {
          const v = CLASSIFICATION[c];
          const on = classes.includes(c);
          return (
            <button
              key={c}
              onClick={() => setClasses(on ? classes.filter((x) => x !== c) : [...classes, c])}
              className={cn(
                "rounded-2xl border bg-surface p-3 text-left transition-all sm:p-4",
                on ? "border-brand-400 ring-2 ring-brand-100" : "border-line hover:border-line-strong",
              )}
              aria-pressed={on}
            >
              <span className={cn("flex items-center gap-1.5 text-xs font-medium sm:text-sm [&_svg]:size-4", v.tone === "eligible" && "text-eligible-700", v.tone === "uncertain" && "text-uncertain-700", v.tone === "ineligible" && "text-ineligible-700")}>
                {v.icon}
                <span className="truncate sm:hidden">{v.short}</span>
                <span className="hidden truncate sm:inline">{v.label}</span>
              </span>
              <span className="mt-1 block text-2xl font-semibold">{counts[c] ?? 0}</span>
            </button>
          );
        })}
      </div>

      <Card className="p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <Input className="pl-9" placeholder="Filter by treatment (e.g. olpasiran)" value={intervention} onChange={(e) => setIntervention(e.target.value)} />
          </div>
          <Select className="w-auto" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="relevance">Most relevant</option>
            <option value="eligibility">Best eligibility fit</option>
            <option value="distance">Nearest</option>
            <option value="start_date">Newest start date</option>
          </Select>
          <Button variant="ghost" size="sm" onClick={() => setShowFilters((x) => !x)} aria-expanded={showFilters}>
            <SlidersHorizontal /> Filters
          </Button>
        </div>
        {showFilters && (
          <div className="mt-3 grid gap-2 border-t border-line pt-3 sm:grid-cols-4">
            <Select value={distance} onChange={(e) => setDistance(e.target.value)} aria-label="Distance">
              <option value="">Any distance</option>
              {["50", "100", "250", "500", "1000"].map((d) => <option key={d} value={d}>Within {d} mi</option>)}
            </Select>
            <Select value={phase} onChange={(e) => setPhase(e.target.value)} aria-label="Phase">
              <option value="">All phases</option>
              {PHASES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Recruitment status">
              <option value="">Open or upcoming</option>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Study type">
              <option value="">All study types</option>
              {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
          </div>
        )}
      </Card>

      {summary && <SearchExplainer summary={summary} />}

      {(isLoading || (refreshing && !data?.items.length)) && (
        <div className="grid gap-4">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-64" />)}
        </div>
      )}

      {data && data.items.length === 0 && !refreshing && (
        <EmptyState icon={<Search />} title="No studies match these filters">
          Try widening the distance or clearing filters. You can also add more to your health profile and search again.
        </EmptyState>
      )}

      <div className="grid gap-4">
        {data?.items.map((item) => (
          <TrialCard
            key={item.trial.nct_id}
            item={item}
            onToggleSave={() => toggleSave(item.trial.nct_id, item.saved)}
            compareSelected={compare.includes(item.trial.nct_id)}
            onToggleCompare={() =>
              setCompare((c) => (c.includes(item.trial.nct_id) ? c.filter((x) => x !== item.trial.nct_id) : c.length >= 4 ? c : [...c, item.trial.nct_id]))
            }
          />
        ))}
      </div>

      {inactiveHidden > 0 && !status && (
        <p className="text-center text-sm text-muted">
          {pluralize(inactiveHidden, "related study", "related studies")} {inactiveHidden === 1 ? "is" : "are"} active but not recruiting.{" "}
          <button className="font-medium text-brand-600 hover:underline" onClick={() => { setStatus("ACTIVE_NOT_RECRUITING"); setShowFilters(true); }}>Show</button>
        </p>
      )}

      {compare.length > 0 && (
        <div className="fixed inset-x-0 bottom-20 z-30 flex justify-center px-4 md:bottom-6">
          <div className="flex items-center gap-3 rounded-full border border-line bg-ink px-4 py-2 text-sm text-white shadow-[var(--shadow-lift)]">
            <GitCompareArrows className="size-4" /> {compare.length} selected
            <button className="text-white/70 hover:text-white" onClick={() => setCompare([])}>Clear</button>
            <Link href={`/app/compare?ids=${compare.join(",")}`} className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 font-medium text-ink">
              Compare <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function SearchExplainer({ summary }: { summary: RefreshSummary }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="p-4 text-sm">
      <button className="flex w-full items-center gap-2 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Info className="size-4 text-brand-500" />
        <span>
          Searched {summary.data_source === "live" ? "ClinicalTrials.gov" : "the registry snapshot"} for{" "}
          <strong className="font-medium">{summary.plan.concepts.filter((c) => c.weight === "direct").map((c) => c.label.toLowerCase()).join(", ") || "your conditions"}</strong>
          {summary.plan.related_terms.length > 0 && <> plus related terms</>} · {pluralize(summary.assessed, "study", "studies")} assessed.
        </span>
        <span className="ml-auto text-xs font-medium text-brand-600">{open ? "Hide" : "How we searched"}</span>
      </button>
      {open && (
        <div className="mt-3 grid gap-3 border-t border-line pt-3 text-xs text-ink-soft sm:grid-cols-3">
          <div>
            <p className="font-semibold text-ink">Direct terms</p>
            <p className="mt-1">{summary.plan.direct_terms.join(" · ") || "—"}</p>
          </div>
          <div>
            <p className="font-semibold text-ink">Investigational treatments</p>
            <p className="mt-1">{summary.plan.drug_terms.join(" · ") || "—"}</p>
          </div>
          <div>
            <p className="font-semibold text-ink">Related conditions (within {summary.plan.radius_miles ?? "any"} mi)</p>
            <p className="mt-1">{summary.plan.related_terms.join(" · ") || "—"}</p>
          </div>
          <p className="text-muted sm:col-span-3">
            Ranking: topic match (direct 50, treatment 40, related 20) + eligibility fit (potentially eligible 25, uncertain 12) + recruitment (recruiting 10, not yet 5) + proximity (up to 15 within your travel radius; −10 when no site has a known distance from you). Related conditions only widen the search — they are never treated as a diagnosis.
          </p>
          {summary.pending_review_count > 0 && (
            <p className="text-uncertain-700 sm:col-span-3">
              {pluralize(summary.pending_review_count, "item")} extracted from your documents {summary.pending_review_count === 1 ? "is" : "are"} awaiting review and {summary.pending_review_count === 1 ? "was" : "were"} not used. <Link className="underline" href="/app/documents">Review now</Link>
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

export default function TrialsPage() {
  return (
    <Suspense>
      <Dashboard />
    </Suspense>
  );
}
