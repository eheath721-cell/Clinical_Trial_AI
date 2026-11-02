"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import useSWR from "swr";

import { ClassificationBadge, StatusBadge } from "@/components/domain";
import { Card, EmptyState, Skeleton } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Assessment, TrialSummary } from "@/lib/types";
import { formatDate, miles } from "@/lib/utils";

function Compare() {
  const ids = useSearchParams().get("ids") ?? "";
  const { activeProfileId } = useSession();
  const { data } = useSWR<{ items: { trial: TrialSummary; assessment: Assessment }[] }>(activeProfileId && ids ? `/api/profiles/${activeProfileId}/compare?ids=${ids}` : null, fetcher);

  if (!ids) return <EmptyState title="Pick studies to compare">Select up to four studies from your matches or saved list.</EmptyState>;
  if (!data) return <Skeleton className="h-96" />;

  const rows: { label: string; render: (t: TrialSummary, a: Assessment) => React.ReactNode }[] = [
    { label: "Your fit", render: (_t, a) => <ClassificationBadge value={a.classification} /> },
    { label: "Recruitment", render: (t) => <StatusBadge status={t.status} label={t.status_label} /> },
    { label: "Study type", render: (t) => t.study_category?.label ?? "—" },
    { label: "Phase", render: (t) => t.phase_label },
    { label: "Treatment", render: (t) => t.interventions.join(", ") || "None (observational)" },
    { label: "Nearest site", render: (_t, a) => (a.nearest_site ? `${miles(a.nearest_site.distance_miles) ?? "Distance unknown"} · ${[a.nearest_site.city, a.nearest_site.state, a.nearest_site.distance_miles === null ? a.nearest_site.country : null].filter(Boolean).join(", ")}` : "No sites listed") },
    { label: "Ages", render: (t) => `${t.minimum_age ?? "no min"} – ${t.maximum_age ?? "no max"}` },
    { label: "Enrollment target", render: (t) => t.enrollment_target?.toLocaleString() ?? "—" },
    { label: "Primary completion", render: (t) => formatDate(t.primary_completion_date) },
    { label: "Why it may not fit", render: (_t, a) => (a.classification === "potentially_ineligible" ? a.key_reasons.slice(0, 2).join("; ") : "—") },
    { label: "Missing information", render: (_t, a) => a.missing_information.slice(0, 3).join("; ") || "—" },
    { label: "Sponsor", render: (t) => t.sponsor ?? "—" },
  ];

  return (
    <div className="flex flex-col gap-6">
      <Link href="/app/trials" className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> Back to matches</Link>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Compare studies</h1>
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line">
              <th className="w-40 p-4" />
              {data.items.map(({ trial: t }) => (
                <th key={t.nct_id} className="p-4 text-left align-top font-semibold">
                  <Link href={`/app/trials/${t.nct_id}`} className="hover:text-brand-700">{t.acronym ?? t.nct_id}</Link>
                  <p className="mt-1 line-clamp-3 text-xs font-normal text-muted">{t.title}</p>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-line last:border-0">
                <th className="p-4 text-left align-top text-xs font-medium uppercase tracking-wide text-muted">{r.label}</th>
                {data.items.map(({ trial, assessment }) => <td key={trial.nct_id} className="p-4 align-top text-ink-soft">{r.render(trial, assessment)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense>
      <Compare />
    </Suspense>
  );
}
