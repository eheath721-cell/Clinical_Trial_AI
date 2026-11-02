"use client";

import { ArrowLeft, ArrowRight, Check, FlaskConical, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { Alert, Button, Card, Field, Input, Segmented, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useProfile, useVocab } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Profile } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = ["About", "Basics", "Health history", "Lab results", "Records"];
type Tri = "present" | "absent" | "unknown";

function Onboarding() {
  const router = useRouter();
  const params = useSearchParams();
  const isNew = params.get("new") === "1";
  const s = useSession();
  const [profileId, setProfileId] = useState<string | null>(null);
  const { data: profile, mutate } = useProfile(profileId);
  const { data: vocab } = useVocab();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // step 0
  const [name, setName] = useState("");
  const [relationship, setRelationship] = useState("self");
  // step 1
  const [dob, setDob] = useState("");
  const [sex, setSex] = useState("unknown");
  const [zip, setZip] = useState("");
  const [radius, setRadius] = useState("250");
  // step 2
  const [answers, setAnswers] = useState<Record<string, Tri>>({});
  const [lipid, setLipid] = useState<string>("unknown");
  const [lpaTherapy, setLpaTherapy] = useState<string>("unknown");
  // step 3
  const [lpa, setLpa] = useState({ value: "", unit: "nmol/L", date: "" });
  const [ldl, setLdl] = useState({ value: "", unit: "mg/dL", date: "" });

  useEffect(() => {
    if (!isNew && s.profiles && s.activeProfileId && !profileId) {
      const p = s.profiles.find((x) => x.id === s.activeProfileId);
      if (p && !p.onboarding_completed) {
        setProfileId(p.id);
        setName(p.display_name);
        setStep(1);
      }
    }
  }, [isNew, s.profiles, s.activeProfileId, profileId]);

  useEffect(() => {
    if (!profile) return;
    if (profile.date_of_birth) setDob(profile.date_of_birth);
    if (profile.postal_code) setZip(profile.postal_code);
    setSex(profile.sex);
    setRadius(String(profile.travel_radius_miles));
  }, [profile]);

  const screenerDone = useMemo(() => vocab?.screener.filter((q) => answers[q.concept]).length ?? 0, [answers, vocab]);

  async function run(fn: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const next = () => setStep((x) => Math.min(x + 1, STEPS.length - 1));

  async function saveAbout() {
    await run(async () => {
      const p = await api.post<Profile>("/api/profiles", { display_name: name || "Me", relationship, is_synthetic: true });
      setProfileId(p.id);
      await s.refreshProfiles();
      s.setActiveProfileId(p.id);
      next();
    });
  }

  async function loadDemo() {
    await run(async () => {
      const p = await api.post<Profile>("/api/demo-profiles/lpa");
      await s.refreshProfiles();
      s.setActiveProfileId(p.id);
      router.push("/app/trials?refresh=1");
    });
  }

  async function saveBasics() {
    await run(async () => {
      await api.patch(`/api/profiles/${profileId}`, {
        date_of_birth: dob || null,
        sex,
        postal_code: zip || null,
        travel_radius_miles: Number(radius),
      });
      await mutate();
      next();
    });
  }

  async function saveHistory() {
    await run(async () => {
      await api.post(`/api/profiles/${profileId}/screener`, { answers, lipid_lowering: lipid, lpa_therapy: lpaTherapy });
      next();
    });
  }

  async function saveLabs() {
    await run(async () => {
      if (lpa.value) {
        await api.post(`/api/profiles/${profileId}/labs`, { analyte: "lpa", value_numeric: Number(lpa.value), unit: lpa.unit, collected_on: lpa.date || null });
      }
      if (ldl.value) {
        await api.post(`/api/profiles/${profileId}/labs`, { analyte: "ldl_c", value_numeric: Number(ldl.value), unit: ldl.unit, collected_on: ldl.date || null });
      }
      next();
    });
  }

  async function finish() {
    await run(async () => {
      await api.patch(`/api/profiles/${profileId}`, { onboarding_completed: true });
      await s.refreshProfiles();
      router.push("/app/trials?refresh=1");
    });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6">
        <p className="text-sm font-medium text-brand-600">Set up a health profile</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{["Who is this profile for?", "The basics", "Health history", "Key lab results", "Medical records (optional)"][step]}</h1>
        <ol className="mt-5 flex gap-1.5" aria-label="Progress">
          {STEPS.map((label, i) => (
            <li key={label} className="flex-1">
              <div className={cn("h-1.5 rounded-full", i <= step ? "bg-brand-500" : "bg-line")} />
              <span className={cn("mt-1.5 hidden text-xs sm:block", i === step ? "font-medium text-ink" : "text-muted")}>{label}</span>
            </li>
          ))}
        </ol>
      </div>

      <Card className="p-5 sm:p-7">
        {step === 0 && (
          <div className="flex flex-col gap-5">
            <Field label="Profile name" hint="A first name or nickname is enough. Avoid full names.">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sam" />
            </Field>
            <Field label="This profile is for">
              <Select value={relationship} onChange={(e) => setRelationship(e.target.value)}>
                <option value="self">Me</option>
                <option value="child">My child</option>
                <option value="parent">My parent</option>
                <option value="spouse_partner">My spouse or partner</option>
                <option value="other">Someone else I care for</option>
              </Select>
            </Field>
            <Alert tone="warn" title="Synthetic data only">This environment is for demonstration. Please don&apos;t enter real health information.</Alert>
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
              <Button variant="secondary" onClick={loadDemo} loading={busy}>
                <FlaskConical /> Use the synthetic Lp(a) patient
              </Button>
              <Button onClick={saveAbout} loading={busy}>Continue <ArrowRight /></Button>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="flex flex-col gap-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Date of birth" hint="Used to check study age limits.">
                <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} max={new Date().toISOString().slice(0, 10)} />
              </Field>
              <Field label="Sex" hint="Only used for studies that enroll a specific sex.">
                <Select value={sex} onChange={(e) => setSex(e.target.value)}>
                  <option value="unknown">Prefer not to say</option>
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                  <option value="intersex">Intersex</option>
                </Select>
              </Field>
              <Field label="ZIP code" hint="Used to calculate distance to study sites. Stays on our servers.">
                <Input inputMode="numeric" maxLength={5} value={zip} onChange={(e) => setZip(e.target.value.replace(/\D/g, ""))} placeholder="79401" />
              </Field>
              <Field label="How far could you travel?">
                <Select value={radius} onChange={(e) => setRadius(e.target.value)}>
                  {["25", "50", "100", "250", "500", "1000"].map((r) => (
                    <option key={r} value={r}>{r} miles</option>
                  ))}
                </Select>
              </Field>
            </div>
            <Nav onBack={() => setStep(0)} onNext={saveBasics} busy={busy} />
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted">
              Answer what you know. <strong className="font-medium text-ink">&ldquo;Not sure&rdquo; is a perfectly good answer</strong> — we&apos;ll show it as missing information rather than guess.
            </p>
            <div className="divide-y divide-line rounded-xl border border-line">
              {vocab?.screener.map((q) => (
                <div key={q.concept} className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between">
                  <span className="text-sm">{q.question ?? q.label}</span>
                  <Segmented<Tri>
                    size="sm"
                    ariaLabel={q.label}
                    value={answers[q.concept] ?? null}
                    onChange={(v) => setAnswers({ ...answers, [q.concept]: v })}
                    options={[{ value: "present", label: "Yes" }, { value: "absent", label: "No" }, { value: "unknown", label: "Not sure" }]}
                  />
                </div>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Cholesterol-lowering medication (e.g. a statin)">
                <Select value={lipid} onChange={(e) => setLipid(e.target.value)}>
                  <option value="unknown">Not sure</option>
                  <option value="current">I take one now</option>
                  <option value="not_current">Not currently</option>
                  <option value="past">I took one in the past</option>
                  <option value="never">I have never taken one</option>
                </Select>
              </Field>
              <Field label="Ever received an investigational Lp(a) therapy?">
                <Select value={lpaTherapy} onChange={(e) => setLpaTherapy(e.target.value)}>
                  <option value="unknown">Not sure</option>
                  <option value="never">No, never</option>
                  <option value="past">Yes, in the past</option>
                  <option value="current">Yes, currently</option>
                </Select>
              </Field>
            </div>
            <p className="text-xs text-muted">{screenerDone} of {vocab?.screener.length ?? 0} answered. You can add diagnoses, medications and procedures in detail later.</p>
            <Nav onBack={() => setStep(1)} onNext={saveHistory} busy={busy} />
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-5">
            <LabEntry title="Lipoprotein(a) — Lp(a)" units={["nmol/L", "mg/dL"]} state={lpa} setState={setLpa}
              note="Enter the unit exactly as it appears on your report. Lp(a) in nmol/L and mg/dL can't be reliably converted, so we never convert between them." />
            <LabEntry title="LDL cholesterol (optional)" units={["mg/dL", "mmol/L"]} state={ldl} setState={setLdl} />
            <p className="text-xs text-muted">Have a lab report PDF instead? Skip this and upload it in the next step — you&apos;ll review every extracted value.</p>
            <Nav onBack={() => setStep(2)} onNext={saveLabs} busy={busy} nextLabel={lpa.value || ldl.value ? "Save & continue" : "Skip"} />
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-col gap-5">
            <div className="rounded-xl border border-dashed border-line-strong bg-canvas p-6 text-center">
              <Upload className="mx-auto size-6 text-brand-500" />
              <p className="mt-2 font-medium">Upload lab reports, visit notes or medication lists</p>
              <p className="mt-1 text-sm text-muted">We extract values, units and dates — then you confirm each one before it&apos;s used.</p>
              <Link href="/app/documents" className="mt-4 inline-flex text-sm font-medium text-brand-600 hover:underline">Go to Documents →</Link>
              <p className="mt-3 text-xs text-muted">
                Need test files? Download a <a className="underline" href="/samples/synthetic_lipid_panel.pdf" download>synthetic lab report</a> or <a className="underline" href="/samples/synthetic_clinic_note.pdf" download>synthetic clinic note</a>.
              </p>
            </div>
            <Nav onBack={() => setStep(3)} onNext={finish} busy={busy} nextLabel="Find my trials" nextIcon={<Check />} />
          </div>
        )}

        {error && <Alert tone="danger" className="mt-4">{error}</Alert>}
      </Card>
    </div>
  );
}

function Nav({ onBack, onNext, busy, nextLabel = "Continue", nextIcon = <ArrowRight /> }: { onBack: () => void; onNext: () => void; busy: boolean; nextLabel?: string; nextIcon?: React.ReactNode }) {
  return (
    <div className="mt-2 flex justify-between">
      <Button variant="ghost" onClick={onBack}><ArrowLeft /> Back</Button>
      <Button onClick={onNext} loading={busy}>{nextLabel} {nextIcon}</Button>
    </div>
  );
}

function LabEntry({ title, units, state, setState, note }: { title: string; units: string[]; state: { value: string; unit: string; date: string }; setState: (s: { value: string; unit: string; date: string }) => void; note?: string }) {
  return (
    <fieldset className="rounded-xl border border-line p-4">
      <legend className="px-1 text-sm font-semibold">{title}</legend>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <Field label="Result">
          <Input inputMode="decimal" value={state.value} onChange={(e) => setState({ ...state, value: e.target.value.replace(/[^0-9.]/g, "") })} placeholder="e.g. 185" />
        </Field>
        <Field label="Unit">
          <Select value={state.unit} onChange={(e) => setState({ ...state, unit: e.target.value })}>
            {units.map((u) => <option key={u}>{u}</option>)}
          </Select>
        </Field>
        <Field label="Date collected" className="col-span-2 sm:col-span-1">
          <Input type="date" value={state.date} onChange={(e) => setState({ ...state, date: e.target.value })} />
        </Field>
      </div>
      {note && <p className="mt-3 text-xs text-muted">{note}</p>}
    </fieldset>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense>
      <Onboarding />
    </Suspense>
  );
}
