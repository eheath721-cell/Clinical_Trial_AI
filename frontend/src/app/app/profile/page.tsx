"use client";

import { Dna, FlaskConical, HeartPulse, Pill, Plus, Stethoscope, Trash2, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProvenanceBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, Dialog, DialogContent, EmptyState, Field, Input, Segmented, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useProfile, useVocab } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Profile } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function ProfilePage() {
  const { activeProfileId } = useSession();
  const { data: p, mutate } = useProfile(activeProfileId);
  const { data: vocab } = useVocab();
  const [dialog, setDialog] = useState<null | "conditions" | "labs" | "medications" | "procedures" | "biomarkers">(null);

  if (!activeProfileId) return <EmptyState title="No profile yet" action={<Link href="/app/onboarding"><Button>Create a profile</Button></Link>} />;
  if (!p || !vocab) return <Skeleton className="h-96" />;

  async function remove(collection: string, id: string) {
    const updated = await api.del<Profile>(`/api/profiles/${p!.id}/${collection}/${id}`);
    mutate(updated, false);
  }

  const assertionWord = { present: "Yes", absent: "No", unknown: "Unknown" } as const;
  const medWord = { current: "Taking now", past: "Taken in the past", not_current: "Not currently taking", never: "Never taken", unknown: "Unknown" } as const;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-brand-600">Health profile</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{p.display_name}</h1>
          <p className="mt-1 text-sm text-muted">Every item shows where it came from. Only confirmed items are used to assess eligibility.</p>
        </div>
        <Link href="/app/trials?refresh=1"><Button>Update my matches</Button></Link>
      </div>

      {p.is_synthetic && <Alert tone="warn" title="Synthetic profile">This profile contains synthetic test data, not a real patient.</Alert>}

      <Basics profile={p} onSaved={(np) => mutate(np, false)} />

      <Screener profile={p} vocab={vocab} onSaved={(np) => mutate(np, false)} />

      <Section icon={<FlaskConical />} title="Lab results" onAdd={() => setDialog("labs")} empty="No lab results yet. Add one or upload a lab report.">
        {p.labs.map((l) => (
          <Item key={l.id} onDelete={() => remove("labs", l.id)}
            title={<>{l.display_name}: <span className="font-semibold">{l.value_numeric ?? l.value_text} {l.unit}</span></>}
            meta={<>{l.collected_on ? `Collected ${formatDate(l.collected_on)}` : <span className="text-uncertain-700">Collection date not recorded</span>}{l.reference_text && ` · Reference ${l.reference_text}`}</>}
            badge={<ProvenanceBadge provenance={l.provenance} verification={l.verification} page={l.source_page} />} note={l.notes} />
        ))}
      </Section>

      <Section icon={<Stethoscope />} title="Diagnoses & conditions" onAdd={() => setDialog("conditions")} empty="Nothing recorded yet.">
        {p.conditions.map((c) => (
          <Item key={c.id} onDelete={() => remove("conditions", c.id)}
            title={<>{c.name}: <Badge tone={c.assertion === "present" ? "brand" : "neutral"}>{assertionWord[c.assertion]}</Badge></>}
            meta={c.onset_date ? `Since ${formatDate(c.onset_date)}` : undefined}
            badge={<ProvenanceBadge provenance={c.provenance} verification={c.verification} page={c.source_page} />} note={c.notes} />
        ))}
      </Section>

      <Section icon={<Pill />} title="Medications" onAdd={() => setDialog("medications")} empty="No medications recorded.">
        {p.medications.map((m) => (
          <Item key={m.id} onDelete={() => remove("medications", m.id)}
            title={<>{m.name}: <Badge>{medWord[m.status]}</Badge></>}
            meta={[m.dose, m.started_on && `Started ${formatDate(m.started_on)}`, m.stopped_on && `Stopped ${formatDate(m.stopped_on)}`].filter(Boolean).join(" · ") || undefined}
            badge={<ProvenanceBadge provenance={m.provenance} verification={m.verification} page={m.source_page} />} note={m.notes} />
        ))}
      </Section>

      <Section icon={<HeartPulse />} title="Procedures & medical history" onAdd={() => setDialog("procedures")} empty="No procedures recorded.">
        {p.procedures.map((x) => (
          <Item key={x.id} onDelete={() => remove("procedures", x.id)}
            title={<>{x.name}: <Badge>{assertionWord[x.assertion]}</Badge></>}
            meta={x.performed_on ? formatDate(x.performed_on) : undefined}
            badge={<ProvenanceBadge provenance={x.provenance} verification={x.verification} page={x.source_page} />} note={x.notes} />
        ))}
      </Section>

      <Section icon={<Dna />} title="Genetic & biomarker results" onAdd={() => setDialog("biomarkers")} empty="No genetic or biomarker results.">
        {p.biomarkers.map((b) => (
          <Item key={b.id} onDelete={() => remove("biomarkers", b.id)} title={<>{b.name}: <span className="font-semibold">{b.result}</span></>}
            meta={[b.interpretation, b.tested_on && formatDate(b.tested_on)].filter(Boolean).join(" · ") || undefined}
            badge={<ProvenanceBadge provenance={b.provenance} verification={b.verification} page={b.source_page} />} note={b.notes} />
        ))}
      </Section>

      <AddFactDialog kind={dialog} onClose={() => setDialog(null)} profileId={p.id} vocab={vocab} onSaved={(np) => { mutate(np, false); setDialog(null); }} />
    </div>
  );
}

function Section({ icon, title, onAdd, empty, children }: { icon: React.ReactNode; title: string; onAdd: () => void; empty: string; children: React.ReactNode[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-brand-500">{icon}{title}</CardTitle>
        <Button variant="ghost" size="sm" onClick={onAdd}><Plus /> Add</Button>
      </CardHeader>
      <CardContent>
        {children.length ? <div className="divide-y divide-line rounded-xl border border-line">{children}</div> : <p className="text-sm text-muted">{empty}</p>}
      </CardContent>
    </Card>
  );
}

function Item({ title, meta, badge, note, onDelete }: { title: React.ReactNode; meta?: React.ReactNode; badge: React.ReactNode; note?: string | null; onDelete: () => void }) {
  return (
    <div className="flex flex-col gap-2 p-3.5 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p>{title}</p>
        {meta && <p className="mt-0.5 text-xs text-muted">{meta}</p>}
        {note && <p className="mt-0.5 text-xs italic text-muted">{note}</p>}
      </div>
      <div className="flex items-center gap-2">
        {badge}
        <button onClick={onDelete} className="rounded-full p-1.5 text-muted hover:bg-canvas hover:text-ineligible-600" aria-label="Delete"><Trash2 className="size-4" /></button>
      </div>
    </div>
  );
}

function Basics({ profile: p, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const [form, setForm] = useState({ date_of_birth: p.date_of_birth ?? "", sex: p.sex, postal_code: p.postal_code ?? "", travel_radius_miles: String(p.travel_radius_miles) });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  async function save() {
    setBusy(true);
    const np = await api.patch<Profile>(`/api/profiles/${p.id}`, { ...form, date_of_birth: form.date_of_birth || null, postal_code: form.postal_code || null, travel_radius_miles: Number(form.travel_radius_miles) });
    onSaved(np);
    setBusy(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><UserRound className="size-4 text-brand-500" />Basics</CardTitle></CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-4">
        <Field label="Date of birth" hint={p.age !== null ? `Age ${p.age}` : undefined}><Input type="date" value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} /></Field>
        <Field label="Sex"><Select value={form.sex} onChange={(e) => setForm({ ...form, sex: e.target.value as Profile["sex"] })}><option value="unknown">Prefer not to say</option><option value="female">Female</option><option value="male">Male</option><option value="intersex">Intersex</option></Select></Field>
        <Field label="ZIP code" hint={p.city ? `${p.city}, ${p.state}` : undefined}><Input value={form.postal_code} maxLength={5} onChange={(e) => setForm({ ...form, postal_code: e.target.value.replace(/\D/g, "") })} /></Field>
        <Field label="Travel radius"><Select value={form.travel_radius_miles} onChange={(e) => setForm({ ...form, travel_radius_miles: e.target.value })}>{["25", "50", "100", "250", "500", "1000"].map((r) => <option key={r} value={r}>{r} miles</option>)}</Select></Field>
        <div className="sm:col-span-4"><Button variant="secondary" size="sm" onClick={save} loading={busy}>{saved ? "Saved" : "Save basics"}</Button></div>
      </CardContent>
    </Card>
  );
}

type Tri = "present" | "absent" | "unknown";

function Screener({ profile: p, vocab, onSaved }: { profile: Profile; vocab: NonNullable<ReturnType<typeof useVocab>["data"]>; onSaved: (p: Profile) => void }) {
  const current = (concept: string): Tri => {
    const rows = [...p.conditions, ...p.procedures].filter((r) => r.concept === concept && r.verification === "confirmed");
    if (rows.some((r) => r.assertion === "present")) return "present";
    if (rows.some((r) => r.assertion === "absent")) return "absent";
    return "unknown";
  };
  const [answers, setAnswers] = useState<Record<string, Tri>>(() => Object.fromEntries(vocab.screener.map((q) => [q.concept, current(q.concept)])));
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  async function save() {
    setBusy(true);
    const changed = Object.fromEntries(Object.entries(answers).filter(([k, v]) => v !== current(k)));
    const np = await api.post<Profile>(`/api/profiles/${p.id}/screener`, { answers: changed });
    onSaved(np);
    setBusy(false);
    setOpen(false);
  }
  const unknown = vocab.screener.filter((q) => current(q.concept) === "unknown").length;
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Quick health questions</CardTitle>
          <p className="mt-1 text-sm text-muted">{unknown ? `${unknown} of ${vocab.screener.length} unanswered — answering them resolves many "missing information" items.` : "All answered."}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setOpen((o) => !o)}>{open ? "Close" : "Answer"}</Button>
      </CardHeader>
      {open && (
        <CardContent>
          <div className="divide-y divide-line rounded-xl border border-line">
            {vocab.screener.map((q) => (
              <div key={q.concept} className="flex flex-col gap-2 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                <span>{q.question ?? q.label}</span>
                <Segmented<Tri> size="sm" value={answers[q.concept]} onChange={(v) => setAnswers({ ...answers, [q.concept]: v })} options={[{ value: "present", label: "Yes" }, { value: "absent", label: "No" }, { value: "unknown", label: "Not sure" }]} />
              </div>
            ))}
          </div>
          <Button className="mt-3" onClick={save} loading={busy}>Save answers</Button>
        </CardContent>
      )}
    </Card>
  );
}

function AddFactDialog({ kind, onClose, profileId, vocab, onSaved }: { kind: null | string; onClose: () => void; profileId: string; vocab: NonNullable<ReturnType<typeof useVocab>["data"]>; onSaved: (p: Profile) => void }) {
  const [f, setF] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const analyte = vocab.analytes.find((a) => a.code === (f.analyte ?? vocab.analytes[0].code))!;
  const titles: Record<string, string> = { labs: "Add a lab result", conditions: "Add a diagnosis or condition", medications: "Add a medication", procedures: "Add a procedure", biomarkers: "Add a genetic or biomarker result" };

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let body: Record<string, unknown> = {};
      if (kind === "labs") body = { analyte: analyte.code, value_numeric: f.value ? Number(f.value) : null, unit: f.unit ?? analyte.units[0], collected_on: f.date || null, reference_text: f.ref || null };
      if (kind === "conditions") body = { concept: f.concept || null, name: f.concept ? null : f.name, assertion: f.assertion ?? "present", onset_date: f.date || null };
      if (kind === "procedures") body = { concept: f.concept || null, name: f.concept ? null : f.name, assertion: f.assertion ?? "present", performed_on: f.date || null };
      if (kind === "medications") body = { concept: f.concept || null, name: f.name || null, status: f.status ?? "current", dose: f.dose || null, started_on: f.date || null };
      if (kind === "biomarkers") body = { name: f.name, result: f.result, interpretation: f.interp || null, tested_on: f.date || null };
      const np = await api.post<Profile>(`/api/profiles/${profileId}/${kind}`, body);
      setF({});
      onSaved(np);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!kind} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={kind ? titles[kind] : ""} description="Saved as patient-reported. You can delete it at any time.">
        <div className="flex flex-col gap-3">
          {kind === "labs" && (
            <>
              <Field label="Test"><Select value={analyte.code} onChange={(e) => setF({ ...f, analyte: e.target.value, unit: "" })}>{vocab.analytes.map((a) => <option key={a.code} value={a.code}>{a.label}</option>)}</Select></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Result"><Input inputMode="decimal" value={f.value ?? ""} onChange={(e) => setF({ ...f, value: e.target.value })} /></Field>
                <Field label="Unit"><Select value={f.unit || analyte.units[0]} onChange={(e) => setF({ ...f, unit: e.target.value })}>{analyte.units.map((u) => <option key={u}>{u}</option>)}</Select></Field>
              </div>
              {!analyte.convertible && analyte.note && <p className="text-xs text-muted">{analyte.note}</p>}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Date collected"><Input type="date" value={f.date ?? ""} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
                <Field label="Reference range (optional)"><Input placeholder="e.g. <75" value={f.ref ?? ""} onChange={(e) => setF({ ...f, ref: e.target.value })} /></Field>
              </div>
            </>
          )}
          {(kind === "conditions" || kind === "procedures") && (
            <>
              <Field label={kind === "conditions" ? "Condition" : "Procedure"}>
                <Select value={f.concept ?? ""} onChange={(e) => setF({ ...f, concept: e.target.value })}>
                  <option value="">Other (type below)</option>
                  {(kind === "conditions" ? vocab.conditions : vocab.procedures).map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                </Select>
              </Field>
              {!f.concept && <Field label="Name"><Input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>}
              <Field label="Do you have / have you had this?"><Segmented value={(f.assertion as Tri) ?? "present"} onChange={(v) => setF({ ...f, assertion: v })} options={[{ value: "present", label: "Yes" }, { value: "absent", label: "No" }]} /></Field>
              <Field label="Date (optional)" hint="Many criteria depend on when something happened."><Input type="date" value={f.date ?? ""} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
            </>
          )}
          {kind === "medications" && (
            <>
              <Field label="Medication or class">
                <Select value={f.concept ?? ""} onChange={(e) => setF({ ...f, concept: e.target.value })}>
                  <option value="">Other (type below)</option>
                  {vocab.medications.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                </Select>
              </Field>
              <Field label="Name (e.g. atorvastatin)"><Input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Status"><Select value={f.status ?? "current"} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="current">Taking now</option><option value="past">Took in the past</option><option value="not_current">Not currently</option><option value="never">Never</option></Select></Field>
                <Field label="Dose (optional)"><Input value={f.dose ?? ""} onChange={(e) => setF({ ...f, dose: e.target.value })} /></Field>
              </div>
              <Field label="Start date (optional)"><Input type="date" value={f.date ?? ""} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
            </>
          )}
          {kind === "biomarkers" && (
            <>
              <Field label="Test or gene (e.g. LPA variant, LDLR)"><Input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
              <Field label="Result"><Input value={f.result ?? ""} onChange={(e) => setF({ ...f, result: e.target.value })} /></Field>
              <Field label="Interpretation (optional)"><Input value={f.interp ?? ""} onChange={(e) => setF({ ...f, interp: e.target.value })} /></Field>
              <Field label="Date (optional)"><Input type="date" value={f.date ?? ""} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
            </>
          )}
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={save} loading={busy}>Save</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
