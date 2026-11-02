"use client";

import { Bookmark, BookmarkCheck, ChevronRight, CircleDashed, MapPin, Pill, ShieldAlert, Sparkles, Stethoscope } from "lucide-react";
import Link from "next/link";

import { ClassificationBadge, StatusBadge, StudyCategoryBadge } from "@/components/domain";
import { Card, Tip } from "@/components/ui";
import type { MatchItem } from "@/lib/types";
import { cn, formatDate, miles } from "@/lib/utils";

export function TrialCard({
  item,
  onToggleSave,
  compareSelected,
  onToggleCompare,
}: {
  item: MatchItem;
  onToggleSave: () => void;
  compareSelected: boolean;
  onToggleCompare: () => void;
}) {
  const { trial: t, assessment: a } = item;
  const site = a.nearest_site;
  const direct = a.match_reasons.filter((r) => r.strength === "direct");
  const related = a.match_reasons.filter((r) => r.strength === "related");
  const reasons = (direct.length ? direct : related).slice(0, 2);

  return (
    <Card className="group overflow-hidden transition-shadow hover:shadow-[var(--shadow-lift)]">
      <div className="p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <ClassificationBadge value={a.classification} />
          <StatusBadge status={t.status} label={t.status_label} />
          <StudyCategoryBadge category={t.study_category} />
          <span className="ml-auto flex items-center gap-1">
            <label className="flex cursor-pointer items-center gap-1.5 rounded-full px-2 py-1 text-xs text-muted hover:bg-canvas">
              <input type="checkbox" className="size-3.5 accent-brand-600" checked={compareSelected} onChange={onToggleCompare} aria-label={`Compare ${t.nct_id}`} />
              Compare
            </label>
            <button onClick={onToggleSave} className="rounded-full p-1.5 text-muted hover:bg-canvas hover:text-brand-600" aria-label={item.saved ? "Remove from saved" : "Save trial"}>
              {item.saved ? <BookmarkCheck className="size-4 text-brand-600" /> : <Bookmark className="size-4" />}
            </button>
          </span>
        </div>

        <Link href={`/app/trials/${t.nct_id}`} className="mt-3 block">
          <h3 className="text-[17px] font-semibold leading-snug tracking-tight group-hover:text-brand-700">
            {t.acronym && <span className="text-brand-700">{t.acronym} · </span>}
            {t.title}
          </h3>
        </Link>
        <p className="mt-1 text-sm text-muted">
          {t.phase_label} · {t.sponsor ?? "Sponsor not listed"} · <span className="font-mono text-xs">{t.nct_id}</span>
        </p>

        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div className="flex gap-2">
            <Pill className="mt-0.5 size-4 shrink-0 text-muted" />
            <span><span className="text-muted">Investigating </span>{t.interventions.length ? t.interventions.slice(0, 2).join(", ") : "No intervention (observational)"}</span>
          </div>
          <div className="flex gap-2">
            <Stethoscope className="mt-0.5 size-4 shrink-0 text-muted" />
            <span className="line-clamp-2">{t.conditions.slice(0, 3).join(" · ")}</span>
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <MapPin className="mt-0.5 size-4 shrink-0 text-muted" />
            {site && site.distance_miles === null ? (
              <span>
                <strong className="font-semibold">{[site.city, site.country].filter(Boolean).join(", ")}</strong>
                <span className="text-muted"> · No sites with a known distance from you{t.location_count > 1 ? ` (${t.location_count} sites listed)` : ""}</span>
              </span>
            ) : site ? (
              <span>
                <strong className="font-semibold">{miles(site.distance_miles)}</strong> · {site.facility ? `${site.facility}, ` : ""}{[site.city, site.state].filter(Boolean).join(", ")}
                <span className="text-muted"> · Registry lists site as {site.site_status ? site.site_status.replaceAll("_", " ").toLowerCase() : "status not listed"}</span>
                {site.geo_source === "postal_centroid" && (
                  <Tip content="Distance estimated from the site's ZIP code because the registry record didn't include coordinates.">
                    <span tabIndex={0} className="ml-1 cursor-help text-xs text-muted underline decoration-dotted">approx.</span>
                  </Tip>
                )}
              </span>
            ) : (
              <span className="text-muted">{t.location_count ? "No site with a known distance (sites may be outside the U.S.)" : "No sites listed yet"}</span>
            )}
          </div>
        </div>

        {reasons.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {reasons.map((r) => (
              <Tip key={r.label} content={<span>{r.patient_basis} Registry text matched: &ldquo;{r.matched_text}&rdquo;</span>}>
                <span tabIndex={0} className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
                  <Sparkles className="size-3" /> {r.label}
                </span>
              </Tip>
            ))}
          </div>
        )}

        <div className="mt-4 rounded-xl bg-canvas p-3.5 text-sm">
          <p className="text-ink-soft">{a.key_reasons[0] ?? a.summary}</p>
          {(a.missing_information.length > 0 || a.potential_exclusions.length > 0) && (
            <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
              {a.missing_information.length > 0 && (
                <div>
                  <p className="flex items-center gap-1 text-xs font-semibold text-uncertain-700"><CircleDashed className="size-3.5" /> Missing information</p>
                  <ul className="mt-1 space-y-0.5 text-xs text-muted">
                    {a.missing_information.slice(0, 3).map((m) => <li key={m} className="line-clamp-1">• {m}</li>)}
                    {a.missing_information.length > 3 && <li>+ {a.missing_information.length - 3} more</li>}
                  </ul>
                </div>
              )}
              {a.potential_exclusions.length > 0 && (
                <div>
                  <p className="flex items-center gap-1 text-xs font-semibold text-ink-soft"><ShieldAlert className="size-3.5" /> Exclusions to confirm</p>
                  <ul className="mt-1 space-y-0.5 text-xs text-muted">
                    {a.potential_exclusions.slice(0, 2).map((m) => <li key={m} className="line-clamp-1">• {m}</li>)}
                    {a.potential_exclusions.length > 2 && <li>+ {a.potential_exclusions.length - 2} more</li>}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-line px-5 py-3 text-xs text-muted sm:px-6">
        <span>
          {t.data_source === "live" ? `Registry last updated ${formatDate(t.last_update_posted)}` : `Snapshot retrieved ${formatDate(t.retrieved_at)} · registry update date not captured`}
        </span>
        <Link href={`/app/trials/${t.nct_id}`} className={cn("inline-flex items-center gap-0.5 font-medium text-brand-600 hover:text-brand-700")}>
          Eligibility breakdown <ChevronRight className="size-4" />
        </Link>
      </div>
    </Card>
  );
}
