"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { fetcher } from "./api";
import type { ProfileSummary, PublicConfig, User } from "./types";

interface SessionValue {
  user: User | null | undefined;
  profiles: ProfileSummary[] | undefined;
  activeProfileId: string | null;
  setActiveProfileId: (id: string) => void;
  config: PublicConfig | undefined;
  refreshProfiles: () => Promise<unknown>;
  refreshUser: () => Promise<unknown>;
}

const SessionContext = React.createContext<SessionValue | null>(null);
const KEY = "tc.activeProfile";

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { data: sessionData, mutate: refreshUser } = useSWR<{ user: User | null }>("/api/auth/session", fetcher, {
    shouldRetryOnError: false,
  });
  const user = sessionData === undefined ? undefined : sessionData.user;
  const authed = !!user;
  const { data: profiles, mutate: refreshProfiles } = useSWR<ProfileSummary[]>(authed ? "/api/profiles" : null, fetcher);
  const { data: config } = useSWR<PublicConfig>("/api/config", fetcher);
  const [activeProfileId, setActive] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!profiles) return;
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(KEY);
    } catch {
      /* storage unavailable */
    }
    const valid = profiles.find((p) => p.id === stored)?.id ?? profiles[0]?.id ?? null;
    setActive(valid);
  }, [profiles]);

  const setActiveProfileId = React.useCallback((id: string) => {
    setActive(id);
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const value: SessionValue = {
    user,
    profiles,
    activeProfileId,
    setActiveProfileId,
    config,
    refreshProfiles,
    refreshUser,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = React.useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}

/** Redirects to /login when signed out. Returns the session once known. */
export function useRequireAuth() {
  const s = useSession();
  const router = useRouter();
  React.useEffect(() => {
    if (s.user === null) router.replace("/login");
  }, [s.user, router]);
  return s;
}
