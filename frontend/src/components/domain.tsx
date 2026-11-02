"use client";

import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Database,
  FileText,
  FlaskConical,
  HelpCircle,
  MinusCircle,
  ShieldAlert,
  UserRound,
  Users,
  XCircle,
} from "lucide-react";

import { Badge, Tip } from "@/components/ui";
import type { Classification, Outcome, SourceStatus } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

export const CLASSIFICATION: Record<Classification, { label: string; short: string; tone: "eligible" | "uncertain" | "ineligible"; icon: React.ReactNode; definition: string }> = {
  potentially_eligible: {
    label: "Potentially eligible",
    short: "May qualify",
    tone: "eligible",
    icon: <CheckCircle2 />,
    definition: "No known conflicts, and the information you've provided supports the key requirements. Only the study team can confirm eligibility.",
  },
  uncertain: {
    label: "Eligibility uncertain",
    short: "Uncertain",
    tone: "uncertain",
    icon: <CircleHelp />,
    definition: "Important requirements can't be evaluated yet because information is missing or the criterion is ambiguous.",
  },
  potentially_ineligible: {
    label: "Potentially ineligible",
    short: "May not qualify",
    tone: "ineligible",
    icon: <XCircle />,
    definition: "At least one requirement appears to conflict with your information. If your information is incomplete or has changed, update your profile.",
  },
};

export function ClassificationBadge({ value, size = "md" }: { value: Classification; size?: "md" | "lg" }) {
  const c = CLASSIFICATION[value];
  return (
    <Tip content={c.definition}>
      <span tabIndex={0} className="inline-flex">
        <Badge tone={c.tone} className={cn(size === "lg" && "px-3 py-1 text-sm [&_svg]:size-4")}>
          {c.icon}
          {c.label}
        </Badge>
      </span>
    </Tip>
  );
}

export function outcomeView(outcome: Outcome, kind: "inclusion" | "exclusion") {
  const map: Record<Outcome, { label: string; tone: "eligible" | "uncertain" | "ineligible" | "neutral" | "brand"; icon: React.ReactNode }> = {
    satisfied: { label: kind === "inclusion" ? "Meets" : "Doesn't apply", tone: "eligible", icon: <CheckCircle2 /> },
    not_satisfied: { label: kind === "inclusion" ? "Doesn't meet" : "May apply", tone: "ineligible", icon: <XCircle /> },
    unknown: { label: "Missing info", tone: "uncertain", icon: <CircleDashed /> },
    needs_review: { label: "Needs review", tone: "uncertain", icon: <HelpCircle /> },
    conflicting: { label: "Conflicting info", tone: "ineligible", icon: <AlertTriangle /> },
    not_applicable: { label: "Not applicable", tone: "neutral", icon: <MinusCircle /> },
    confirm_with_team: { label: "Study team confirms", tone: "neutral", icon: <Users /> },
  };
  return map[outcome];
}

export function OutcomeBadge({ outcome, kind }: { outcome: Outcome; kind: "inclusion" | "exclusion" }) {
  const v = outcomeView(outcome, kind);
  return (
    <Badge tone={v.tone} className="whitespace-nowrap">
      {v.icon}
      {v.label}
    </Badge>
  );
}

export function ProvenanceBadge({ provenance, verification, page }: { provenance?: string; verification?: string; page?: number | null }) {
  if (verification === "pending_review") {
    return (
      <Badge tone="uncertain">
        <ShieldAlert /> Awaiting your review
      </Badge>
    );
  }
  switch (provenance) {
    case "document_extracted":
      return (
        <Badge tone="brand">
          <FileText /> From document{page ? `, p.${page}` : ""}
        </Badge>
      );
    case "clinician_confirmed":
      return (
        <Badge tone="eligible">
          <BadgeCheck /> Clinician confirmed
        </Badge>
      );
    case "unknown":
      return <Badge>Source unknown</Badge>;
    default:
      return (
        <Badge>
          <UserRound /> You reported
        </Badge>
      );
  }
}

export function StudyCategoryBadge({ category }: { category: { code: string; label: string; explanation: string } | null }) {
  if (!category) return null;
  return (
    <Tip content={<span>{category.explanation} <span className="opacity-70">(Based on the registry&apos;s primary outcome.)</span></span>}>
      <span tabIndex={0} className="inline-flex">
        <Badge tone="neutral">
          <FlaskConical /> {category.label}
        </Badge>
      </span>
    </Tip>
  );
}

const STATUS_TONE: Record<string, "eligible" | "uncertain" | "neutral" | "ineligible"> = {
  RECRUITING: "eligible",
  NOT_YET_RECRUITING: "uncertain",
  ENROLLING_BY_INVITATION: "uncertain",
  ACTIVE_NOT_RECRUITING: "neutral",
};

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <Badge tone={STATUS_TONE[status] ?? "ineligible"}>
      <span className={cn("size-1.5 rounded-full", status === "RECRUITING" ? "bg-eligible-600" : "bg-current opacity-60")} />
      {label}
    </Badge>
  );
}

export function DataSourceNote({ source, className }: { source?: SourceStatus; className?: string }) {
  if (!source) return null;
  const snapshot = source.active === "snapshot";
  return (
    <div className={cn("flex items-start gap-2 rounded-xl border px-3 py-2 text-xs", snapshot ? "border-uncertain-600/25 bg-uncertain-50 text-uncertain-700" : "border-line bg-surface text-muted", className)}>
      <Database className="mt-0.5 size-3.5 shrink-0" />
      <span>
        {snapshot ? (
          <>
            <strong className="font-semibold">Offline registry snapshot.</strong> Real ClinicalTrials.gov records retrieved {formatDate(source.snapshot_retrieved_at)}. Recruitment status may have changed — always confirm on ClinicalTrials.gov.
          </>
        ) : (
          <>Live data from the ClinicalTrials.gov API.</>
        )}
      </span>
    </div>
  );
}

export function SyntheticBanner() {
  return (
    <div className="bg-ink text-[13px] text-white/90">
      <div className="container-page flex items-center justify-center gap-2 py-1.5 text-center">
        <ShieldAlert className="size-3.5 shrink-0 text-accent-500" />
        <span>
          Demonstration environment — <strong className="font-semibold text-white">use synthetic data only.</strong> Do not enter real health information.
        </span>
      </div>
    </div>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight text-ink", className)}>
      <span className="grid size-7 place-items-center rounded-lg bg-brand-600 text-white">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="8.5" />
          <path d="m15.5 8.5-2 5-5 2 2-5z" fill="currentColor" stroke="none" />
        </svg>
      </span>
      TrialCompass
    </span>
  );
}
