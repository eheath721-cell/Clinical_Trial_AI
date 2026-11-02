"use client";

import { CalendarClock, CheckCircle2, ClipboardList, Circle, MapPin, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, buttonVariants, Card, CardContent, CardHeader, CardTitle, EmptyState, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useInquiries, useTasks } from "@/lib/hooks";
import { INQUIRY_STATUS } from "@/lib/constants";
import { useSession } from "@/lib/session";
import { cn, formatDate } from "@/lib/utils";


export default function EnrollmentPage() {
  const { activeProfileId } = useSession();
  const { data: inquiries } = useInquiries(activeProfileId);
  const { data: tasks, mutate: mutateTasks } = useTasks(activeProfileId);
  const [newTask, setNewTask] = useState("");

  async function toggleTask(id: string, done: boolean) {
    await api.patch(`/api/profiles/${activeProfileId}/tasks/${id}`, { status: done ? "open" : "done" });
    mutateTasks();
  }
  async function addTask() {
    if (!newTask.trim()) return;
    await api.post(`/api/profiles/${activeProfileId}/tasks`, { title: newTask.trim() });
    setNewTask("");
    mutateTasks();
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Enrollment</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Your outreach to study teams</h1>
        <p className="mt-1 text-sm text-muted">Track inquiries, replies and next steps. TrialCompass never contacts anyone on your behalf.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="flex flex-col gap-3">
          {!inquiries && <Skeleton className="h-32" />}
          {inquiries?.length === 0 && (
            <EmptyState icon={<ClipboardList />} title="No inquiries yet" action={<Link href="/app/trials" className={buttonVariants()}>Find a study</Link>}>
              Open a study and choose &ldquo;Contact study team&rdquo; to prepare a message you can review and send yourself.
            </EmptyState>
          )}
          {inquiries?.map((i) => {
            const s = INQUIRY_STATUS[i.status] ?? { label: i.status, tone: "neutral" as const };
            return (
              <Link key={i.id} href={`/app/enrollment/${i.id}`}>
                <Card className="p-5 transition-shadow hover:shadow-[var(--shadow-lift)]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold leading-snug">{i.trial.acronym ? `${i.trial.acronym} · ` : ""}{i.trial.title}</p>
                      {i.location && <p className="mt-1 flex items-center gap-1 text-sm text-muted"><MapPin className="size-3.5" />{i.location.facility}, {[i.location.city, i.location.state].filter(Boolean).join(", ")}</p>}
                    </div>
                    <Badge tone={s.tone}>{s.label}</Badge>
                  </div>
                  <p className="mt-3 text-xs text-muted">
                    Updated {formatDate(i.updated_at)}{i.sent_at && ` · Sent ${formatDate(i.sent_at)}`}{i.last_response_at && ` · Last reply ${formatDate(i.last_response_at)}`}
                  </p>
                </Card>
              </Link>
            );
          })}
        </div>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><CalendarClock className="size-4 text-brand-500" /> Follow-up tasks</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {tasks?.length === 0 && <p className="text-sm text-muted">No tasks yet.</p>}
            {tasks?.map((t) => (
              <button key={t.id} onClick={() => toggleTask(t.id, t.status === "done")} className="flex items-start gap-2.5 rounded-lg p-2 text-left text-sm hover:bg-canvas">
                {t.status === "done" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-eligible-600" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted" />}
                <span className={cn("flex-1", t.status === "done" && "text-muted line-through")}>{t.title}</span>
                {t.due_on && <span className={cn("shrink-0 text-xs", t.overdue ? "font-medium text-ineligible-600" : "text-muted")}>{formatDate(t.due_on, { month: "short", day: "numeric" })}</span>}
              </button>
            ))}
            <div className="mt-2 flex gap-2">
              <Input placeholder="Add a task" value={newTask} onChange={(e) => setNewTask(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addTask()} />
              <Button variant="secondary" size="icon" onClick={addTask} aria-label="Add task"><Plus /></Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
