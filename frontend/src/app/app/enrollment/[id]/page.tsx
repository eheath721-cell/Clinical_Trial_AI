"use client";

import { ArrowLeft, Check, CheckCircle2, Circle, Copy, ExternalLink, Mail, Phone, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select, Skeleton, Textarea } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { INQUIRY_STATUS } from "@/lib/constants";
import { useSession } from "@/lib/session";
import type { Inquiry } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const FLOW = ["draft", "ready", "sent_by_user", "response_received", "prescreen_scheduled", "screening", "enrolled"];

export default function InquiryPage() {
  const { id } = useParams<{ id: string }>();
  const { activeProfileId } = useSession();
  const key = activeProfileId ? `/api/profiles/${activeProfileId}/inquiries/${id}` : null;
  const { data: inq, mutate } = useSWR<Inquiry>(key, fetcher);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [nextStatus, setNextStatus] = useState("");

  useEffect(() => {
    if (inq) {
      setSubject(inq.email_subject ?? "");
      setBody(inq.email_body ?? "");
    }
  }, [inq?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!inq) return <Skeleton className="h-96" />;

  const dirty = subject !== (inq.email_subject ?? "") || body !== (inq.email_body ?? "");
  const st = INQUIRY_STATUS[inq.status] ?? { label: inq.status, tone: "neutral" as const };
  const mailto = inq.contact?.email ? `mailto:${inq.contact.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}` : null;

  async function save() {
    setSaving(true);
    await api.patch(`/api/profiles/${activeProfileId}/inquiries/${inq!.id}`, { email_subject: subject, email_body: body });
    await mutate();
    setSaving(false);
  }
  async function copy() {
    await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  async function record(status: string) {
    await api.post(`/api/profiles/${activeProfileId}/inquiries/${inq!.id}/events`, { status, note: note || null });
    setNote("");
    setNextStatus("");
    mutate();
  }
  async function toggleDoc(k: string) {
    const list = inq!.document_checklist.map((d) => (d.key === k ? { ...d, have: !d.have } : d));
    await api.patch(`/api/profiles/${activeProfileId}/inquiries/${inq!.id}`, { document_checklist: list });
    mutate();
  }

  const stepIndex = FLOW.indexOf(inq.status);

  return (
    <div className="flex flex-col gap-6">
      <Link href="/app/enrollment" className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> All inquiries</Link>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Badge tone={st.tone}>{st.label}</Badge>
          <h1 className="mt-2 text-xl font-semibold leading-snug tracking-tight sm:text-2xl">{inq.trial.acronym ? `${inq.trial.acronym} · ` : ""}{inq.trial.title}</h1>
          <Link href={`/app/trials/${inq.nct_id}`} className="text-sm font-medium text-brand-600 hover:underline">View eligibility breakdown</Link>
        </div>
      </div>

      <ol className="flex gap-1 overflow-x-auto" aria-label="Progress">
        {FLOW.map((s, i) => (
          <li key={s} className="min-w-[6.5rem] flex-1">
            <div className={cn("h-1.5 rounded-full", i <= stepIndex ? "bg-brand-500" : "bg-line")} />
            <span className={cn("mt-1 block text-[11px]", i === stepIndex ? "font-semibold text-ink" : "text-muted")}>{INQUIRY_STATUS[s].label}</span>
          </li>
        ))}
      </ol>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Your message</CardTitle>
              <p className="text-sm text-muted">Review and edit before sending. We never send messages or share health information for you.</p>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Input value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
              <Textarea rows={18} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Message body" className="font-[450] leading-relaxed" />
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={save} loading={saving} disabled={!dirty}>{dirty ? "Save changes" : "Saved"}</Button>
                <Button variant="secondary" onClick={copy}>{copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy message"}</Button>
                {mailto && <a href={mailto} className="inline-flex"><Button><Mail /> Open in my email app</Button></a>}
              </div>
              <Alert tone="info" icon={<ShieldCheck />}>
                After you send it from your own email or phone, record it below so we can remind you to follow up.
              </Alert>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Record what happened</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                {inq.status !== "sent_by_user" && stepIndex < 2 && <Button onClick={() => record("sent_by_user")}>I sent it</Button>}
                <Select className="w-auto" value={nextStatus} onChange={(e) => setNextStatus(e.target.value)} aria-label="Update status">
                  <option value="">Update status…</option>
                  {Object.entries(INQUIRY_STATUS).filter(([k]) => k !== "draft").map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </Select>
                {nextStatus && <Button variant="secondary" onClick={() => record(nextStatus)}>Save status</Button>}
              </div>
              <Input placeholder="Optional note (e.g. coordinator asked for my lab report)" value={note} onChange={(e) => setNote(e.target.value)} />
              <ol className="mt-2 space-y-3 border-l border-line pl-4">
                {[...inq.events].reverse().map((e, i) => (
                  <li key={i} className="relative text-sm">
                    <span className="absolute -left-[21px] top-1.5 size-2.5 rounded-full border-2 border-surface bg-brand-400" />
                    <p className="font-medium">{INQUIRY_STATUS[e.type]?.label ?? e.type.replaceAll("_", " ")}</p>
                    {e.note && <p className="text-ink-soft">{e.note}</p>}
                    <p className="text-xs text-muted">{formatDate(e.at, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}</p>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader><CardTitle>Contact</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {inq.location && (
                <div>
                  <p className="font-medium">{inq.location.facility}</p>
                  <p className="text-muted">{[inq.location.city, inq.location.state, inq.location.country].filter(Boolean).join(", ")}</p>
                  <p className="mt-1 text-xs text-muted">This site is {inq.location.status_text}. That doesn&apos;t guarantee it is accepting new participants.</p>
                </div>
              )}
              {inq.contact && (
                <div className="space-y-1 rounded-xl bg-canvas p-3">
                  {inq.contact.name && <p className="flex items-center gap-1.5"><Users className="size-3.5 text-muted" />{inq.contact.name}</p>}
                  {inq.contact.phone && <a className="flex items-center gap-1.5 text-brand-600" href={`tel:${inq.contact.phone}`}><Phone className="size-3.5" />{inq.contact.phone}</a>}
                  {inq.contact.email && <a className="flex items-center gap-1.5 text-brand-600" href={`mailto:${inq.contact.email}`}><Mail className="size-3.5" />{inq.contact.email}</a>}
                  {!inq.contact.phone && !inq.contact.email && <p className="text-xs text-muted">No phone or email is included in this registry record.</p>}
                  <p className="text-xs text-muted">{inq.contact.source}</p>
                </div>
              )}
              <a href={inq.trial.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">Contacts & locations on ClinicalTrials.gov <ExternalLink className="size-3" /></a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Questions to ask</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-1.5 text-sm text-ink-soft">{inq.questions.map((q) => <li key={q}>• {q}</li>)}</ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Documents to have ready</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-1">
              {inq.document_checklist.map((d) => (
                <button key={d.key} onClick={() => toggleDoc(d.key)} className="flex items-start gap-2.5 rounded-lg p-2 text-left text-sm hover:bg-canvas">
                  {d.have ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-eligible-600" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted" />}
                  <span><span className={cn(d.have && "text-muted line-through")}>{d.label}</span><span className="block text-xs text-muted">{d.reason}</span></span>
                </button>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
