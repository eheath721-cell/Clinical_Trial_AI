"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Profile } from "@/lib/types";

function SignupForm() {
  const router = useRouter();
  const params = useSearchParams();
  const demo = params.get("demo") === "lpa";
  const { refreshUser, refreshProfiles, setActiveProfileId } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consents, setConsents] = useState({ terms: false, privacy: false, health: false, ai: false });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/auth/register", {
        email,
        password,
        accept_terms: consents.terms,
        accept_privacy: consents.privacy,
        accept_health_data: consents.health,
        accept_ai_processing: consents.ai,
      });
      await refreshUser();
      if (demo) {
        const p = await api.post<Profile>("/api/demo-profiles/lpa");
        await refreshProfiles();
        setActiveProfileId(p.id);
        router.push("/app/trials?refresh=1");
      } else {
        router.push("/app/onboarding");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const box = (key: keyof typeof consents, label: React.ReactNode) => (
    <label className="flex items-start gap-2.5 text-sm text-ink-soft">
      <input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={consents[key]} onChange={(e) => setConsents({ ...consents, [key]: e.target.checked })} />
      <span>{label}</span>
    </label>
  );

  return (
    <Card className="w-full max-w-md p-6 sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
      <p className="mt-1 text-sm text-muted">
        {demo ? "We'll set up a synthetic patient with elevated Lp(a) so you can explore the full experience." : "It takes about five minutes to set up your health profile."}
      </p>
      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" hint="At least 10 characters.">
          <Input type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <div className="flex flex-col gap-2.5 rounded-xl border border-line bg-canvas p-4">
          {box("terms", "I agree to the Terms of Use. TrialCompass is a research discovery tool, not medical advice.")}
          {box("privacy", "I have read the Privacy Notice.")}
          {box("health", "I consent to TrialCompass storing the health information I provide to match me with trials. I can delete it at any time.")}
          {box("ai", <>Optional: allow AI-assisted document extraction (only used where a vendor agreement permits it; <em>never</em> required).</>)}
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
        <Button type="submit" size="lg" loading={loading} disabled={!consents.terms || !consents.privacy || !consents.health}>
          {demo ? "Create account & load demo" : "Create account"}
        </Button>
        <p className="text-center text-sm text-muted">
          Already have an account? <Link className="font-medium text-brand-600 hover:underline" href="/login">Sign in</Link>
        </p>
      </form>
    </Card>
  );
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
