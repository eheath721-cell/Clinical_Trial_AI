"use client";

import { ChevronDown, ExternalLink, FileText, Quote } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { OutcomeBadge, ProvenanceBadge } from "@/components/domain";
import { Segmented } from "@/components/ui";
import type { CriterionRow, Evidence } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const ATTENTION = new Set(["not_satisfied", "unknown", "needs_review", "conflicting"]);

export function EligibilityTable({ rows, bestCohort, profileId }: { rows: CriterionRow[]; bestCohort: string | null; profileId: string }) {
  const [filter, setFilter] = useState<"all" | "attention">("all");
  const sections: { kind: "inclusion" | "exclusion"; title: string; hint: string }[] = [
    { kind: "inclusion", title: "Inclusion criteria", hint: "Requirements participants must meet." },
    { kind: "exclusion", title: "Exclusion criteria", hint: "Conditions that would prevent participation." },
  ];
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Each criterion is quoted from the registry and compared with your profile. Expand a row to see why and the sources used.</p>
        <Segmented
          size="sm"
          value={filter}
          onChange={setFilter}
          options={[{ value: "all", label: "All criteria" }, { value: "attention", label: "Needs attention" }]}
        />
      </div>
      {sections.map((s) => {
        const list = rows.filter((r) => r.kind === s.kind && (filter === "all" || ATTENTION.has(r.outcome) || r.is_group));
        if (!list.length) return null;
        return (
          <section key={s.kind}>
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="font-semibold">{s.title}</h3>
              <span className="text-xs text-muted">{s.hint}</span>
            </div>
            <div className="overflow-hidden rounded-2xl border border-line bg-surface">
              <div className="hidden grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] gap-4 border-b border-line bg-canvas px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted md:grid">
                <span>Criterion (from registry)</span>
                <span>Your information</span>
                <span className="w-32 text-right">Assessment</span>
              </div>
              {list.map((r) => (
                <Row key={r.position} row={r} bestCohort={bestCohort} profileId={profileId} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function Row({ row, bestCohort, profileId }: { row: CriterionRow; bestCohort: string | null; profileId: string }) {
  const [open, setOpen] = useState(false);
  const otherCohort = row.cohort && bestCohort && row.cohort !== bestCohort;
  const patientEvidence = row.evidence.filter((e) => e.kind === "patient_fact");
  const trialEvidence = row.evidence.find((e) => e.kind === "trial_criterion");
  return (
    <div className={cn("border-b border-line last:border-b-0", otherCohort && "opacity-55")}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="grid w-full grid-cols-1 gap-2 px-4 py-3 text-left text-sm hover:bg-canvas/60 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] md:gap-4"
        style={{ paddingLeft: `${1 + row.depth * 1.25}rem` }}
      >
        <span className="flex gap-2">
          <ChevronDown className={cn("mt-0.5 size-4 shrink-0 text-muted transition-transform", open && "rotate-180")} />
          <span>
            <span className={cn(row.is_group && "font-medium")}>{row.text}</span>
            {row.cohort && <span className="ml-2 rounded-full bg-canvas px-2 py-0.5 text-[11px] text-muted">Group: {row.cohort}</span>}
            {row.source === "registry_field" && <span className="ml-2 rounded-full bg-canvas px-2 py-0.5 text-[11px] text-muted">registry field</span>}
          </span>
        </span>
        <span className="pl-6 text-ink-soft md:pl-0">{row.is_group ? <span className="text-muted">See items below</span> : row.patient_information}</span>
        <span className="pl-6 md:w-32 md:pl-0 md:text-right">
          <OutcomeBadge outcome={row.outcome} kind={row.kind} />
        </span>
      </button>
      {open && (
        <div className="space-y-3 bg-canvas/50 px-4 pb-4 pt-1 text-sm" style={{ paddingLeft: `${2.5 + row.depth * 1.25}rem` }}>
          <p className="leading-relaxed text-ink-soft">{row.explanation}</p>
          {otherCohort && <p className="text-xs text-muted">This item applies to a different study group than the one that best matches your profile.</p>}
          <div className="grid gap-2 md:grid-cols-2">
            {trialEvidence && (
              <SourceCard title="Trial criterion" icon={<Quote className="size-3.5" />}>
                <p className="line-clamp-4 italic text-ink-soft">&ldquo;{trialEvidence.text}&rdquo;</p>
                <a href={trialEvidence.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
                  ClinicalTrials.gov {trialEvidence.nct_id} <ExternalLink className="size-3" />
                </a>
              </SourceCard>
            )}
            {patientEvidence.map((e, i) => (
              <PatientSource key={i} e={e} profileId={profileId} />
            ))}
            {!patientEvidence.length && !row.is_group && row.category !== "administrative" && row.category !== "investigator" && (
              <SourceCard title="Your information" icon={<FileText className="size-3.5" />}>
                <p className="text-muted">Nothing in your profile addresses this yet.</p>
                {row.missing.length > 0 && <p className="mt-1 text-xs text-muted">Missing: {row.missing.join("; ")}</p>}
                <Link href="/app/profile" className="mt-1 inline-flex text-xs font-medium text-brand-600 hover:underline">Add to my profile</Link>
              </SourceCard>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SourceCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{icon} {title}</p>
      {children}
    </div>
  );
}

function PatientSource({ e, profileId }: { e: Evidence; profileId: string }) {
  return (
    <SourceCard title="Your information" icon={<FileText className="size-3.5" />}>
      <p className="font-medium">{e.label}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <ProvenanceBadge provenance={e.provenance} verification={e.verification} page={e.source_page} />
        {e.recorded_on && <span className="text-xs text-muted">Dated {formatDate(e.recorded_on)}</span>}
      </div>
      {e.source_excerpt && <p className="mt-1.5 line-clamp-3 rounded-lg bg-canvas px-2 py-1 font-mono text-[11px] text-ink-soft">{e.source_excerpt}</p>}
      {e.document_id && (
        <a href={`/api/profiles/${profileId}/documents/${e.document_id}/file`} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
          Open source document <ExternalLink className="size-3" />
        </a>
      )}
    </SourceCard>
  );
}
