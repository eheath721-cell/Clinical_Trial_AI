"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bookmark, ChevronDown, ClipboardList, FileText, HeartPulse, LogOut, Plus, Search, Settings, Sparkles, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Logo, SyntheticBanner } from "@/components/domain";
import { Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/session";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/app/trials", label: "Matches", icon: <Sparkles /> },
  { href: "/app/profile", label: "Health profile", icon: <HeartPulse /> },
  { href: "/app/documents", label: "Documents", icon: <FileText /> },
  { href: "/app/saved", label: "Saved", icon: <Bookmark /> },
  { href: "/app/enrollment", label: "Enrollment", icon: <ClipboardList /> },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const s = useRequireAuth();
  const pathname = usePathname();
  const router = useRouter();
  const active = s.profiles?.find((p) => p.id === s.activeProfileId);

  async function logout() {
    await api.post("/api/auth/logout").catch(() => undefined);
    await s.refreshUser();
    router.replace("/");
  }

  if (!s.user) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="min-h-screen pb-20 md:pb-0">
      {s.config?.synthetic_data_only !== false && <SyntheticBanner />}
      <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="container-page flex h-16 items-center gap-4">
          <Link href="/app/trials" aria-label="Home"><Logo /></Link>
          <nav className="ml-4 hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                  pathname.startsWith(n.href) ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/app/search" className="hidden rounded-full p-2 text-muted hover:bg-surface hover:text-ink sm:inline-flex" aria-label="Search all trials">
              <Search className="size-4" />
            </Link>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-3 text-sm shadow-sm hover:border-line-strong">
                <span className="grid size-7 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
                  {(active?.display_name ?? "?").slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden max-w-[10rem] truncate font-medium sm:inline">{active?.display_name ?? "No profile"}</span>
                <ChevronDown className="size-4 text-muted" />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-[16rem] rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow-lift)]">
                  <DropdownMenu.Label className="px-2.5 py-1.5 text-xs font-medium text-muted">Profiles you manage</DropdownMenu.Label>
                  {s.profiles?.map((p) => (
                    <DropdownMenu.Item
                      key={p.id}
                      onSelect={() => s.setActiveProfileId(p.id)}
                      className={cn("flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-canvas", p.id === s.activeProfileId && "font-semibold")}
                    >
                      <UserRound className="size-4 text-muted" />
                      <span className="truncate">{p.display_name}</span>
                      {p.is_synthetic && <span className="ml-auto rounded-full bg-canvas px-1.5 text-[10px] font-medium text-muted">synthetic</span>}
                    </DropdownMenu.Item>
                  ))}
                  <DropdownMenu.Item onSelect={() => router.push("/app/onboarding?new=1")} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-brand-700 outline-none data-[highlighted]:bg-canvas">
                    <Plus className="size-4" /> Add someone you care for
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator className="my-1.5 h-px bg-line" />
                  <DropdownMenu.Item onSelect={() => router.push("/app/settings")} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-canvas">
                    <Settings className="size-4 text-muted" /> Privacy & settings
                  </DropdownMenu.Item>
                  <DropdownMenu.Item onSelect={logout} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-canvas">
                    <LogOut className="size-4 text-muted" /> Sign out
                  </DropdownMenu.Item>
                  <p className="px-2.5 pb-1 pt-2 text-[11px] text-muted">{s.user.email}</p>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
        </div>
      </header>

      <main className="container-page py-6 sm:py-8">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 backdrop-blur md:hidden" aria-label="Primary">
        <div className="grid grid-cols-5">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={cn("flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium [&_svg]:size-5", pathname.startsWith(n.href) ? "text-brand-600" : "text-muted")}>
              {n.icon}
              {n.label.split(" ")[0]}
            </Link>
          ))}
        </div>
      </nav>
    </div>
  );
}
