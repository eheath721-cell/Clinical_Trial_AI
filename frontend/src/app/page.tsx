import { ArrowRight, CheckCircle2, CircleDashed, FileSearch, Lock, MapPin, MessagesSquare, Scale, Search, XCircle } from "lucide-react";
import Link from "next/link";

import { Logo, SyntheticBanner } from "@/components/domain";
import { buttonVariants } from "@/components/ui/variants";
import { cn } from "@/lib/utils";

const steps = [
  { icon: <FileSearch />, title: "Share what you know", body: "Enter your diagnoses, labs and medications, or upload a lab report. You confirm everything we extract." },
  { icon: <Search />, title: "We search beyond keywords", body: "Your terms are mapped to how researchers index studies, so “high Lp(a)” also finds lipoprotein(a), ASCVD and investigational-drug trials." },
  { icon: <Scale />, title: "See why — criterion by criterion", body: "Every requirement is checked against your information, with the source cited. Missing information is shown as missing, never guessed." },
  { icon: <MessagesSquare />, title: "Reach the right study team", body: "Find the nearest sites, get a draft inquiry you control, and track replies and follow-ups." },
];

const exampleRows = [
  { c: "Lp(a) ≥ 175 nmol/L", p: "185 nmol/L (your lab report)", o: "Meets", tone: "eligible" },
  { c: "Prior heart attack, stroke or artery procedure", p: "No heart attack reported; stroke not recorded", o: "Missing info", tone: "uncertain" },
  { c: "Currently taking a statin", p: "Not currently taking", o: "Doesn't meet", tone: "ineligible" },
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <SyntheticBanner />
      <header className="container-page flex items-center justify-between py-5">
        <Logo />
        <nav className="flex items-center gap-2">
          <Link href="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>Sign in</Link>
          <Link href="/signup" className={buttonVariants({ size: "sm" })}>Get started</Link>
        </nav>
      </header>

      <main>
        <section className="container-page grid items-center gap-12 pb-16 pt-8 lg:grid-cols-[1.1fr_1fr] lg:pt-16">
          <div>
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-brand-100 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
              Built on the ClinicalTrials.gov registry · Independent of sponsors
            </p>
            <h1 className="text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-[3.4rem]">
              Find clinical trials you may qualify for — and understand exactly why.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-soft">
              Tell us about your health. We search the research ecosystem, check each trial&apos;s eligibility criteria against your information, show where you can participate, and help you contact the study team.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/signup" className={buttonVariants({ size: "lg" })}>
                Find my trials <ArrowRight />
              </Link>
              <Link href="/signup?demo=lpa" className={buttonVariants({ variant: "secondary", size: "lg" })}>
                Try the Lp(a) demo
              </Link>
            </div>
            <p className="mt-4 text-sm text-muted">Free while in development · No health data is sold or shared without your action.</p>
          </div>

          <div className="relative">
            <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-brand-100 via-canvas to-accent-500/10" />
            <div className="rounded-2xl border border-line bg-surface p-5 shadow-[var(--shadow-lift)] sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted">Example assessment · synthetic patient</p>
                  <h2 className="mt-1 font-semibold leading-snug">Phase 3 Lp(a)-lowering cardiovascular outcomes trial</h2>
                </div>
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-uncertain-600/25 bg-uncertain-50 px-2.5 py-0.5 text-xs font-medium text-uncertain-700">
                  <CircleDashed className="size-3.5" /> Uncertain
                </span>
              </div>
              <div className="mt-4 divide-y divide-line rounded-xl border border-line">
                {exampleRows.map((r) => (
                  <div key={r.c} className="grid grid-cols-[1fr_auto] gap-3 p-3 text-sm">
                    <div>
                      <p className="font-medium">{r.c}</p>
                      <p className="text-muted">{r.p}</p>
                    </div>
                    <span
                      className={cn(
                        "inline-flex h-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                        r.tone === "eligible" && "bg-eligible-50 text-eligible-700",
                        r.tone === "uncertain" && "bg-uncertain-50 text-uncertain-700",
                        r.tone === "ineligible" && "bg-ineligible-50 text-ineligible-700",
                      )}
                    >
                      {r.tone === "eligible" ? <CheckCircle2 className="size-3.5" /> : r.tone === "ineligible" ? <XCircle className="size-3.5" /> : <CircleDashed className="size-3.5" />}
                      {r.o}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex items-center gap-2 text-sm text-ink-soft">
                <MapPin className="size-4 text-brand-500" /> Nearest listed site: 118 mi · Registry status: Recruiting
              </div>
              <p className="mt-3 text-xs text-muted">Final eligibility is always determined by the study team.</p>
            </div>
          </div>
        </section>

        <section className="border-y border-line bg-surface">
          <div className="container-page grid gap-8 py-14 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((s, i) => (
              <div key={s.title}>
                <div className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-xl bg-brand-50 text-brand-600 [&_svg]:size-5">{s.icon}</span>
                  <span className="text-xs font-semibold text-muted">STEP {i + 1}</span>
                </div>
                <h3 className="mt-4 font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="container-page grid gap-6 py-16 md:grid-cols-3">
          {[
            { t: "Transparent, not a black box", b: "No unexplained scores. Each trial shows which criteria appear met, which may conflict, and which need more information — with the source of every statement." },
            { t: "Honest about uncertainty", b: "We never tell you that you are eligible or ineligible. We say what the registry states, what your records show, and what only the study team can decide." },
            { t: "You stay in control", b: "We draft messages; you decide what to share and send it yourself. Delete your data at any time." },
          ].map((x) => (
            <div key={x.t} className="rounded-2xl border border-line bg-surface p-6">
              <h3 className="font-semibold">{x.t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{x.b}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="container-page flex flex-col gap-3 py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
          <span className="inline-flex items-center gap-1.5"><Lock className="size-3.5" /> TrialCompass is a research discovery and navigation tool. It does not provide medical advice or treatment recommendations.</span>
          <span>Trial data: U.S. National Library of Medicine, ClinicalTrials.gov</span>
        </div>
      </footer>
    </div>
  );
}
