"use client";

import { ArrowLeft, Bookmark, BookmarkCheck, CalendarDays, CircleDashed, ExternalLink, HelpCircle, Mail, MapPin, Phone, Send, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { ClassificationBadge, DataSourceNote, StatusBadge, StudyCategoryBadge } from "@/components/domain";
import { EligibilityTable } from "@/components/eligibility-table";
import { Alert, Button, buttonVariants, Card, CardContent, CardHeader, CardTitle, Dialog, DialogContent, Select, Skeleton, Stat, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Assessment, Inquiry, TrialDetail } from "@/lib/types";
import { cn, formatDate, miles } from "@/lib/utils";

interface DetailResponse {
  trial: TrialDetail;
  assessment: Assessment;
  saved: boolean;
}

const GAP_LABELS: Record<string, string> = {
  last_update_posted: "registry last-update date",
  site_coordinates: "site coordinates (distances estimated from ZIP codes)",
  contact_phone_email: "contact phone numbers and emails",
  overall_officials: "principal investigator names",
  keywords: "keywords",
  intervention_types: "intervention types",
};

export default function TrialDetailPage() {
  const { nct } = useParams<{ nct: string }>();
  const router = useRouter();
  const { activeProfileId, config } = useSession();
  const { data, error, mutate } = useSWR<DetailResponse>(activeProfileId ? `/api/profiles/${activeProfileId}/trials/${nct}/assessment` : null, fetcher);
  const [inquiryOpen, setInquiryOpen] = useState(false);
  const [siteForInquiry, setSiteForInquiry] = useState<string | undefined>();

  if (error) return <Alert tone="danger" title="Couldn't load this study">{error.message}</Alert>;
  if (!data || !activeProfileId) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
        <Skeleton className="h-96" />
      </div>
    );
  }
  const { trial: t, assessment: a } = data;

  async function toggleSave() {
    if (data!.saved) await api.del(`/api/profiles/${activeProfileId}/saved/${t.nct_id}`);
    else await api.post(`/api/profiles/${activeProfileId}/saved`, { nct_id: t.nct_id });
    mutate();
  }

  function startInquiry(locationId?: string) {
    setSiteForInquiry(locationId);
    setInquiryOpen(true);
  }

  return (
    <div className="flex flex-col gap-6">
      <button onClick={() => router.back()} className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Back to matches
      </button>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <ClassificationBadge value={a.classification} size="lg" />
            <StatusBadge status={t.status} label={t.status_label} />
            <StudyCategoryBadge category={t.study_category} />
          </div>
          <h1 className="mt-3 text-balance text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
            {t.acronym && <span className="text-brand-700">{t.acronym}: </span>}
            {t.title}
          </h1>
          <p className="mt-2 text-sm text-muted">
            {t.phase_label} · {t.sponsor} · <span className="font-mono">{t.nct_id}</span>
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="secondary" onClick={toggleSave}>
            {data.saved ? <BookmarkCheck className="text-brand-600" /> : <Bookmark />} {data.saved ? "Saved" : "Save"}
          </Button>
          <Button onClick={() => startInquiry()}>
            <Send /> Contact study team
          </Button>
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="grid lg:grid-cols-[1.4fr_1fr]">
          <div className="p-5 sm:p-6">
            <h2 className="font-semibold">What this means for {config ? "you" : "you"}</h2>
            <p className="mt-2 leading-relaxed text-ink-soft">{a.summary}</p>
            {a.key_reasons.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-sm">
                {a.key_reasons.map((r) => <li key={r} className="flex gap-2"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-brand-400" />{r}</li>)}
              </ul>
            )}
            {t.study_category?.code === "cv_outcomes" && (
              <Alert tone="info" className="mt-4" title="About cardiovascular outcomes trials">
                {t.study_category.explanation} Elevated Lp(a) alone is usually not enough — check the criteria below.
              </Alert>
            )}
            {a.caveats.map((c) => <p key={c} className="mt-3 text-xs text-muted">• {c}</p>)}
          </div>
          <div className="border-t border-line bg-canvas p-5 sm:p-6 lg:border-l lg:border-t-0">
            {a.missing_information.length > 0 ? (
              <>
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-uncertain-700"><CircleDashed className="size-4" /> Information that would help</h3>
                <ul className="mt-2 space-y-1 text-sm text-ink-soft">
                  {a.missing_information.slice(0, 6).map((m) => <li key={m}>• {m}</li>)}
                </ul>
                <Link href="/app/profile" className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "mt-3")}>Update my profile</Link>
              </>
            ) : (
              <p className="text-sm text-muted">Your profile addresses every clinical criterion the registry lists.</p>
            )}
            {a.questions.length > 0 && (
              <>
                <h3 className="mt-5 flex items-center gap-1.5 text-sm font-semibold"><HelpCircle className="size-4 text-brand-500" /> Questions to ask the study team</h3>
                <ul className="mt-2 space-y-1 text-sm text-ink-soft">
                  {a.questions.slice(0, 4).map((q) => <li key={q}>• {q}</li>)}
                </ul>
              </>
            )}
          </div>
        </div>
      </Card>

      <Tabs defaultValue="eligibility">
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="eligibility">Eligibility breakdown</TabsTrigger>
          <TabsTrigger value="locations">Locations ({t.locations.length})</TabsTrigger>
          <TabsTrigger value="about">About the study</TabsTrigger>
        </TabsList>

        <TabsContent value="eligibility" className="mt-5">
          <EligibilityTable rows={a.criteria ?? []} bestCohort={a.best_cohort} profileId={activeProfileId} />
          <p className="mt-4 text-xs text-muted">
            Assessed {formatDate(a.assessed_at)} with engine v{a.engine_version}. Rules-based evaluation; criteria that can&apos;t be interpreted reliably are marked &ldquo;Needs review&rdquo; rather than guessed.
          </p>
        </TabsContent>

        <TabsContent value="locations" className="mt-5">
          <Locations trial={t} onContact={startInquiry} />
        </TabsContent>

        <TabsContent value="about" className="mt-5">
          <About trial={t} />
        </TabsContent>
      </Tabs>

      <DataSourceNote source={config?.trial_source} />

      <StartInquiryDialog open={inquiryOpen} onOpenChange={setInquiryOpen} trial={t} profileId={activeProfileId} defaultLocation={siteForInquiry ?? a.nearest_site?.location_id ?? undefined} />
    </div>
  );
}

function Locations({ trial: t, onContact }: { trial: TrialDetail; onContact: (id: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const list = showAll ? t.locations : t.locations.slice(0, 12);
  if (!t.locations.length) {
    return <Alert tone="info" title="No sites listed yet">The registry doesn&apos;t list participating locations for this study yet. Check back, or ask the sponsor via the central contact.</Alert>;
  }
  return (
    <div className="flex flex-col gap-3">
      <Alert tone="warn">
        Site statuses come from the registry and can lag behind reality. A site listed as &ldquo;Recruiting&rdquo; may not be enrolling new participants right now — confirm with the site.
      </Alert>
      {t.central_contacts.length > 0 && (
        <Card className="p-4 text-sm">
          <p className="font-semibold">Central contact</p>
          {t.central_contacts.map((c, i) => <ContactLine key={i} c={c} />)}
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {list.map((l) => (
          <Card key={l.id} className="flex flex-col gap-2 p-4 text-sm">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{l.facility ?? "Facility not named"}</p>
                <p className="text-muted">{[l.city, l.state, l.country].filter(Boolean).join(", ")}</p>
              </div>
              {l.distance_miles !== null && <span className="shrink-0 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-700">{miles(l.distance_miles)}</span>}
            </div>
            <p className="text-xs text-muted">Registry status: <span className="font-medium text-ink-soft">{l.status_label}</span>{l.geo_source === "postal_centroid" && " · distance approximate"}</p>
            {l.contacts.length > 0 ? l.contacts.map((c, i) => <ContactLine key={i} c={c} />) : <p className="text-xs text-muted">No site contact listed in the registry record.</p>}
            <Button variant="secondary" size="sm" className="mt-1 w-fit" onClick={() => onContact(l.id)}>Draft inquiry to this site</Button>
          </Card>
        ))}
      </div>
      {t.locations.length > 12 && !showAll && (
        <Button variant="ghost" onClick={() => setShowAll(true)}>Show all {t.locations.length} locations</Button>
      )}
    </div>
  );
}

function ContactLine({ c }: { c: { name: string | null; role: string | null; phone: string | null; email: string | null } }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-soft">
      {c.name && <span className="inline-flex items-center gap-1"><Users className="size-3.5" />{c.name}</span>}
      {c.phone && <a href={`tel:${c.phone}`} className="inline-flex items-center gap-1 text-brand-600"><Phone className="size-3.5" />{c.phone}</a>}
      {c.email && <a href={`mailto:${c.email}`} className="inline-flex items-center gap-1 text-brand-600"><Mail className="size-3.5" />{c.email}</a>}
      {!c.phone && !c.email && <span className="text-muted">Phone/email not included in this record</span>}
    </div>
  );
}

function About({ trial: t }: { trial: TrialDetail }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card>
        <CardHeader><CardTitle>Purpose</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm leading-relaxed text-ink-soft">
          <p className="whitespace-pre-line">{t.brief_summary ?? "No summary provided."}</p>
          {t.primary_outcomes.length > 0 && (
            <div>
              <p className="font-semibold text-ink">What the study measures (primary outcomes)</p>
              <ul className="mt-1 space-y-1">{t.primary_outcomes.map((o) => <li key={o.measure}>• {o.measure}{o.time_frame && <span className="text-muted"> — {o.time_frame}</span>}</li>)}</ul>
            </div>
          )}
          {t.detailed_description && (
            <details>
              <summary className="cursor-pointer font-medium text-ink">Detailed description</summary>
              <p className="mt-2 whitespace-pre-line">{t.detailed_description}</p>
            </details>
          )}
          <details>
            <summary className="cursor-pointer font-medium text-ink">Full eligibility text (as registered)</summary>
            <pre className="mt-2 whitespace-pre-wrap font-sans text-xs">{t.eligibility_text}</pre>
          </details>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Key facts</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <Stat label="Phase" value={t.phase_label} />
          <Stat label="Study type" value={(t.study_type ?? "—").toLowerCase()} />
          <Stat label="Enrollment target" value={t.enrollment_target?.toLocaleString() ?? "—"} />
          <Stat label="Ages" value={`${t.minimum_age ?? "No min"} – ${t.maximum_age ?? "no max"}`} />
          <Stat label="Sex" value={(t.sex ?? "ALL").toLowerCase()} />
          <Stat label="Healthy volunteers" value={t.healthy_volunteers === null ? "—" : t.healthy_volunteers ? "Accepted" : "No"} />
          <Stat label="Start" value={formatDate(t.start_date)} />
          <Stat label="Primary completion" value={formatDate(t.primary_completion_date)} />
          <div className="col-span-2">
            <Stat label="Treatments" value={t.interventions.join(", ") || "None (observational)"} />
          </div>
          {t.overall_officials.length > 0 && (
            <div className="col-span-2"><Stat label="Principal investigator" value={t.overall_officials.map((o) => [o.name, o.affiliation].filter(Boolean).join(", ")).join("; ")} /></div>
          )}
          <div className="col-span-2 space-y-1 border-t border-line pt-3 text-xs text-muted">
            <p className="flex items-center gap-1"><CalendarDays className="size-3.5" />{t.data_source === "live" ? `Registry last updated ${formatDate(t.last_update_posted)}` : `Snapshot retrieved ${formatDate(t.retrieved_at)}`}</p>
            {t.field_gaps.length > 0 && <p>Not available in this record: {t.field_gaps.map((g) => GAP_LABELS[g] ?? g).join(", ")}.</p>}
            <a href={t.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline">View on ClinicalTrials.gov <ExternalLink className="size-3" /></a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StartInquiryDialog({ open, onOpenChange, trial, profileId, defaultLocation }: { open: boolean; onOpenChange: (o: boolean) => void; trial: TrialDetail; profileId: string; defaultLocation?: string }) {
  const router = useRouter();
  const { data: options } = useSWR<{ key: string; label: string; default: boolean }[]>(open ? `/api/profiles/${profileId}/inquiries/share-options` : null, fetcher);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [location, setLocation] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = selected ?? options?.filter((o) => o.default).map((o) => o.key) ?? [];
  const loc = location ?? defaultLocation ?? "";
  const sites = useMemo(() => trial.locations.filter((l) => l.status !== "TERMINATED" && l.status !== "WITHDRAWN").slice(0, 50), [trial]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const inq = await api.post<Inquiry>(`/api/profiles/${profileId}/inquiries`, { nct_id: trial.nct_id, location_id: loc || null, shared_fields: chosen });
      router.push(`/app/enrollment/${inq.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create the draft");
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Draft an inquiry" description="We'll prepare a message for you to review. Nothing is sent until you send it yourself.">
        <div className="flex flex-col gap-4 text-sm">
          <div>
            <p className="mb-1.5 font-medium">Which site?</p>
            <Select value={loc} onChange={(e) => setLocation(e.target.value)}>
              <option value="">Any site / central contact</option>
              {sites.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.distance_miles !== null ? `${miles(l.distance_miles)} · ` : ""}{l.facility ?? "Site"}, {[l.city, l.state].filter(Boolean).join(", ")} ({l.status_label})
                </option>
              ))}
            </Select>
          </div>
          <div>
            <p className="mb-1.5 font-medium">What would you like to include?</p>
            <p className="mb-2 text-xs text-muted">Share only what&apos;s needed. You can edit the message afterwards.</p>
            <div className="flex flex-col gap-1.5 rounded-xl border border-line p-3">
              {options?.length === 0 && <p className="text-muted">Your profile has no details to share yet.</p>}
              {options?.map((o) => (
                <label key={o.key} className="flex items-center gap-2">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={chosen.includes(o.key)} onChange={(e) => setSelected(e.target.checked ? [...chosen, o.key] : chosen.filter((k) => k !== o.key))} />
                  {o.label}
                </label>
              ))}
            </div>
          </div>
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button onClick={create} loading={busy}><MapPin /> Prepare draft</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
