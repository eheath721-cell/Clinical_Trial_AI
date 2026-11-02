"use client";

import { AlertTriangle, Check, FileText, Pencil, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import useSWR from "swr";

import { Alert, Badge, Button, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { useDocuments } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { DocumentRow, ExtractedFact } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const DOC_TYPES = [["lab_report", "Lab report"], ["physician_note", "Visit / physician note"], ["medication_list", "Medication list"], ["pathology_report", "Pathology report"], ["genetic_report", "Genetic report"], ["other", "Other"]];

export default function DocumentsPage() {
  const { activeProfileId } = useSession();
  const { data: docs, mutate } = useDocuments(activeProfileId);
  const [docType, setDocType] = useState("lab_report");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (!activeProfileId) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("doc_type", docType);
      const doc = await api.upload<DocumentRow>(`/api/profiles/${activeProfileId}/documents`, form);
      await mutate();
      setOpenId(doc.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Documents</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Medical records</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">Upload lab reports, visit notes or medication lists. We find values, units, dates and diagnoses — then you review each one. Nothing is used for eligibility until you accept it.</p>
      </div>

      <Card
        className="flex flex-col items-center gap-3 border-dashed p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) upload(f);
        }}
      >
        <div className="rounded-full bg-brand-50 p-3 text-brand-600"><Upload className="size-6" /></div>
        <p className="font-medium">Drop a PDF here, or choose a file</p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Select className="w-auto" value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="Document type">
            {DOC_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          <input ref={input} type="file" accept="application/pdf,text/plain" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button onClick={() => input.current?.click()} loading={uploading}>Choose file</Button>
        </div>
        <p className="text-xs text-muted">PDF or text, up to 15 MB. Files are encrypted at rest. Scanned images aren&apos;t supported yet.</p>
        <p className="text-xs text-muted">Testing? Use the <a className="underline" href="/samples/synthetic_lipid_panel.pdf" download>synthetic lab report</a> or <a className="underline" href="/samples/synthetic_clinic_note.pdf" download>synthetic clinic note</a>.</p>
      </Card>

      {error && <Alert tone="danger">{error}</Alert>}

      {!docs && <Skeleton className="h-32" />}
      {docs?.length === 0 && <EmptyState icon={<FileText />} title="No documents yet">Uploading a recent lab report is the quickest way to strengthen your matches.</EmptyState>}

      <div className="flex flex-col gap-3">
        {docs?.map((d) => (
          <DocumentCard key={d.id} doc={d} profileId={activeProfileId!} open={openId === d.id} onToggle={() => setOpenId(openId === d.id ? null : d.id)} onChange={() => mutate()} />
        ))}
      </div>
    </div>
  );
}

function DocumentCard({ doc, profileId, open, onToggle, onChange }: { doc: DocumentRow; profileId: string; open: boolean; onToggle: () => void; onChange: () => void }) {
  const { data, mutate } = useSWR<DocumentRow>(open ? `/api/profiles/${profileId}/documents/${doc.id}` : null, fetcher);
  const notes = doc.extraction_methods.filter((m) => m.startsWith("note:")).map((m) => m.slice(5));

  async function del() {
    if (!confirm("Delete this document? Items you already accepted stay in your profile.")) return;
    await api.del(`/api/profiles/${profileId}/documents/${doc.id}`);
    onChange();
  }

  async function acceptAllClean() {
    if (!data?.facts) return;
    for (const f of data.facts.filter((x) => x.review_status === "pending" && x.warnings.length === 0)) {
      await api.post(`/api/profiles/${profileId}/extracted-facts/${f.id}/accept`);
    }
    await mutate();
    onChange();
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 p-4">
        <FileText className="size-5 text-brand-500" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{doc.filename}</p>
          <p className="text-xs text-muted">
            {DOC_TYPES.find((t) => t[0] === doc.doc_type)?.[1]} · Uploaded {formatDate(doc.uploaded_at)} · {doc.page_count ?? "?"} page(s)
          </p>
        </div>
        {doc.status === "no_text" && <Badge tone="uncertain">No selectable text</Badge>}
        {doc.status === "failed" && <Badge tone="ineligible">Couldn&apos;t read file</Badge>}
        {doc.pending_count > 0 ? <Badge tone="uncertain">{doc.pending_count} to review</Badge> : doc.fact_count > 0 ? <Badge tone="eligible"><Check /> Reviewed</Badge> : null}
        <Button variant="secondary" size="sm" onClick={onToggle}>{open ? "Close" : doc.pending_count ? "Review" : "View"}</Button>
        <a className="text-xs font-medium text-brand-600 hover:underline" href={`/api/profiles/${profileId}/documents/${doc.id}/file`} target="_blank" rel="noreferrer">Open</a>
        <button onClick={del} className="rounded-full p-1.5 text-muted hover:bg-canvas hover:text-ineligible-600" aria-label="Delete document"><Trash2 className="size-4" /></button>
      </div>
      {open && (
        <div className="border-t border-line bg-canvas/60 p-4">
          {notes.map((n) => <Alert key={n} tone="info" className="mb-3">{n}</Alert>)}
          {!data && <Skeleton className="h-24" />}
          {data?.facts?.length === 0 && <p className="text-sm text-muted">No clinical facts were found in this document. You can add information manually on your profile.</p>}
          {data?.facts && data.facts.some((f) => f.review_status === "pending" && f.warnings.length === 0) && (
            <div className="mb-3 flex justify-end"><Button size="sm" variant="secondary" onClick={acceptAllClean}><Check /> Accept all items without warnings</Button></div>
          )}
          <div className="flex flex-col gap-2">
            {data?.facts?.map((f) => <FactReview key={f.id} fact={f} profileId={profileId} onDone={() => { mutate(); onChange(); }} />)}
          </div>
        </div>
      )}
    </Card>
  );
}

function describe(f: ExtractedFact): { title: string; detail: string } {
  const p = f.payload as Record<string, string | number | null>;
  if (f.fact_type === "lab") return { title: `${p.display_name}: ${p.value_numeric ?? p.value_text} ${p.unit ?? "(no unit)"}`, detail: [p.collected_on ? `Collected ${formatDate(String(p.collected_on))}` : "No collection date found", p.reference_text && `Reference ${p.reference_text}`, p.flag && `Flag ${p.flag}`].filter(Boolean).join(" · ") };
  if (f.fact_type === "medication") return { title: `${p.name}`, detail: { current: "Currently taking", past: "Taken in the past", not_current: "Not currently taking", never: "Never taken" }[String(p.status)] ?? String(p.status) };
  if (f.fact_type === "biomarker") return { title: `${p.name}: ${p.result}`, detail: "Genetic / biomarker result" };
  return { title: `${p.name}`, detail: p.assertion === "absent" ? "Recorded as NOT present" : "Recorded as present" };
}

function FactReview({ fact, profileId, onDone }: { fact: ExtractedFact; profileId: string; onDone: () => void }) {
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const d = describe(fact);
  const p = fact.payload as Record<string, string | number | null>;

  async function accept() {
    setBusy(true);
    const body: Record<string, unknown> = {};
    if (edits.value) body.value_numeric = Number(edits.value);
    if (edits.unit) body.unit = edits.unit;
    if (edits.date) body.collected_on = edits.date;
    await api.post(`/api/profiles/${profileId}/extracted-facts/${fact.id}/accept`, Object.keys(body).length ? body : undefined);
    setBusy(false);
    onDone();
  }
  async function reject() {
    setBusy(true);
    await api.post(`/api/profiles/${profileId}/extracted-facts/${fact.id}/reject`);
    setBusy(false);
    onDone();
  }

  return (
    <div className={cn("rounded-xl border bg-surface p-3 text-sm", fact.review_status === "pending" ? "border-line-strong" : "border-line opacity-70")}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="font-medium">{d.title}</p>
          <p className="text-xs text-muted">{d.detail} · {fact.fact_type} · page {fact.source_page} · {fact.method === "llm" ? "AI extraction" : "rules-based extraction"}</p>
          {fact.source_excerpt && <p className="mt-1.5 rounded-lg bg-canvas px-2 py-1 font-mono text-[11px] text-ink-soft">&ldquo;{fact.source_excerpt}&rdquo;</p>}
          {fact.warnings.map((w) => <p key={w} className="mt-1 flex items-start gap-1 text-xs text-uncertain-700"><AlertTriangle className="mt-0.5 size-3 shrink-0" />{w}</p>)}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {fact.review_status === "pending" ? (
            <>
              {fact.fact_type === "lab" && <Button variant="ghost" size="sm" onClick={() => setEditing((e) => !e)}><Pencil /> Edit</Button>}
              <Button variant="secondary" size="sm" onClick={reject} disabled={busy}><X /> Reject</Button>
              <Button size="sm" onClick={accept} loading={busy}><Check /> Accept</Button>
            </>
          ) : (
            <Badge tone={fact.review_status === "accepted" ? "eligible" : "neutral"}>{fact.review_status === "accepted" ? "Accepted" : "Rejected"}</Badge>
          )}
        </div>
      </div>
      {editing && (
        <div className="mt-3 grid grid-cols-3 gap-2">
          <Input placeholder={String(p.value_numeric ?? "")} value={edits.value ?? ""} onChange={(e) => setEdits({ ...edits, value: e.target.value })} aria-label="Value" />
          <Input placeholder={String(p.unit ?? "unit")} value={edits.unit ?? ""} onChange={(e) => setEdits({ ...edits, unit: e.target.value })} aria-label="Unit" />
          <Input type="date" value={edits.date ?? String(p.collected_on ?? "")} onChange={(e) => setEdits({ ...edits, date: e.target.value })} aria-label="Date" />
        </div>
      )}
    </div>
  );
}
