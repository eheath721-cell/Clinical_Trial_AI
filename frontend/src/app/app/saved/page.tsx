"use client";

import { Bookmark, MapPin, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClassificationBadge, StatusBadge } from "@/components/domain";
import { Button, buttonVariants, Card, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useSaved } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { formatDate, miles } from "@/lib/utils";

export default function SavedPage() {
  const { activeProfileId } = useSession();
  const { data, mutate } = useSaved(activeProfileId);
  const [compare, setCompare] = useState<string[]>([]);

  async function remove(nct: string) {
    await api.del(`/api/profiles/${activeProfileId}/saved/${nct}`);
    mutate();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-brand-600">Saved</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Studies you&apos;re considering</h1>
        </div>
        {compare.length >= 2 && <Link href={`/app/compare?ids=${compare.join(",")}`} className={buttonVariants()}>Compare {compare.length}</Link>}
      </div>
      {!data && <Skeleton className="h-40" />}
      {data?.length === 0 && (
        <EmptyState icon={<Bookmark />} title="Nothing saved yet" action={<Link href="/app/trials" className={buttonVariants()}>Browse matches</Link>}>
          Save studies from your matches to compare them and keep track.
        </EmptyState>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((s) => s.trial && (
          <Card key={s.nct_id} className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-center gap-2">
              {s.classification && <ClassificationBadge value={s.classification} />}
              <StatusBadge status={s.trial.status} label={s.trial.status_label} />
              <label className="ml-auto flex items-center gap-1.5 text-xs text-muted">
                <input type="checkbox" className="size-3.5 accent-brand-600" checked={compare.includes(s.nct_id)} onChange={() => setCompare((c) => (c.includes(s.nct_id) ? c.filter((x) => x !== s.nct_id) : [...c, s.nct_id].slice(0, 4)))} />
                Compare
              </label>
            </div>
            <Link href={`/app/trials/${s.nct_id}`} className="font-semibold leading-snug hover:text-brand-700">{s.trial.acronym ? `${s.trial.acronym} · ` : ""}{s.trial.title}</Link>
            <p className="text-sm text-muted">{s.trial.phase_label} · {s.trial.sponsor}</p>
            {s.nearest_site && <p className="flex items-center gap-1.5 text-sm"><MapPin className="size-4 text-muted" />{miles(s.nearest_site.distance_miles) ?? "Distance unknown"} · {[s.nearest_site.city, s.nearest_site.state, s.nearest_site.distance_miles === null ? s.nearest_site.country : null].filter(Boolean).join(", ")}</p>}
            <div className="mt-auto flex items-center justify-between pt-2 text-xs text-muted">
              <span>Saved {formatDate(s.saved_at)}</span>
              <div className="flex gap-1">
                <Link href={`/app/trials/${s.nct_id}`} className={buttonVariants({ variant: "secondary", size: "sm" })}>Details</Link>
                <Button variant="ghost" size="sm" onClick={() => remove(s.nct_id)} aria-label="Remove"><Trash2 /></Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
