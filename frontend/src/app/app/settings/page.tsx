"use client";

import { Download, ShieldCheck, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { Alert, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { formatDate } from "@/lib/utils";

export default function SettingsPage() {
  const router = useRouter();
  const s = useSession();
  const { data: audit } = useSWR<{ at: string; action: string; resource_type: string | null; outcome: string }[]>("/api/account/audit", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const active = s.profiles?.find((p) => p.id === s.activeProfileId);

  async function exportData() {
    setBusy("export");
    const data = await api.get("/api/account/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "trialcompass-export.json";
    a.click();
    setBusy(null);
  }
  async function toggleAi() {
    await api.post("/api/account/consents", { consent_type: "ai_processing", granted: !s.user?.consents.ai_processing });
    s.refreshUser();
  }
  async function deleteProfile() {
    if (!active || !confirm(`Permanently delete "${active.display_name}" and all of its health information, documents and inquiries?`)) return;
    setBusy("profile");
    await api.del(`/api/profiles/${active.id}`);
    await s.refreshProfiles();
    setBusy(null);
    router.push("/app");
  }
  async function deleteAccount() {
    if (!confirm("Permanently delete your account and ALL profiles, documents and records? This cannot be undone.")) return;
    setBusy("account");
    await api.del("/api/account");
    await s.refreshUser();
    router.replace("/");
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Privacy & settings</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Your data, your control</h1>
      </div>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-brand-500" /> How we handle your information</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-ink-soft">
          <p>• Health information is used only to find and explain trials for you. We do not sell it, and nothing is shared with a study team unless you send it yourself.</p>
          <p>• Uploaded files are encrypted at rest. Our application logs never contain health values.</p>
          <p>• Every access to your profile is recorded in an audit log you can see below.</p>
          <p>• This environment is a demonstration and is not yet approved for real patient data.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>AI-assisted document extraction</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm sm:flex-row sm:items-center sm:justify-between">
          <p className="text-ink-soft">
            {s.user?.consents.ai_processing ? "On" : "Off"}. When on, and only where a vendor agreement permits it, document text may be sent to an AI service to improve extraction. Rules-based extraction always runs on our servers. {s.config?.llm_available ? "" : "(AI extraction is not configured in this environment.)"}
          </p>
          <Button variant="secondary" size="sm" onClick={toggleAi}>{s.user?.consents.ai_processing ? "Turn off" : "Turn on"}</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Export or delete</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Button variant="secondary" className="w-fit" onClick={exportData} loading={busy === "export"}><Download /> Download all my data (JSON)</Button>
          {active && <Button variant="danger" className="w-fit" onClick={deleteProfile} loading={busy === "profile"}><Trash2 /> Delete profile &ldquo;{active.display_name}&rdquo;</Button>}
          <Button variant="danger" className="w-fit" onClick={deleteAccount} loading={busy === "account"}><Trash2 /> Delete my account</Button>
          <Alert tone="warn">Deletion is permanent and removes health information, documents (including encrypted files), assessments and inquiries.</Alert>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Recent account activity</CardTitle></CardHeader>
        <CardContent>
          <div className="max-h-80 divide-y divide-line overflow-y-auto rounded-xl border border-line text-sm">
            {audit?.slice(0, 50).map((e, i) => (
              <div key={i} className="flex justify-between gap-3 px-3 py-2">
                <span>{e.action.replaceAll(".", " · ").replaceAll("_", " ")}{e.outcome !== "success" && <span className="text-ineligible-600"> ({e.outcome})</span>}</span>
                <span className="shrink-0 text-xs text-muted">{formatDate(e.at, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
