"use client";

import useSWR from "swr";

import { fetcher } from "./api";
import { useSession } from "./session";
import type { DocumentRow, Inquiry, MatchesResponse, Profile, SavedTrial, Task, Vocab } from "./types";

export function useActiveProfileId() {
  return useSession().activeProfileId;
}

export function useProfile(id?: string | null) {
  return useSWR<Profile>(id ? `/api/profiles/${id}` : null, fetcher);
}

export function useVocab() {
  return useSWR<Vocab>("/api/vocab", fetcher, { revalidateOnFocus: false });
}

export function useMatches(id: string | null, query: string) {
  return useSWR<MatchesResponse>(id ? `/api/profiles/${id}/matches${query ? `?${query}` : ""}` : null, fetcher, {
    keepPreviousData: true,
  });
}

export function useDocuments(id: string | null) {
  return useSWR<DocumentRow[]>(id ? `/api/profiles/${id}/documents` : null, fetcher);
}

export function useSaved(id: string | null) {
  return useSWR<SavedTrial[]>(id ? `/api/profiles/${id}/saved` : null, fetcher);
}

export function useInquiries(id: string | null) {
  return useSWR<Inquiry[]>(id ? `/api/profiles/${id}/inquiries` : null, fetcher);
}

export function useTasks(id: string | null) {
  return useSWR<Task[]>(id ? `/api/profiles/${id}/tasks` : null, fetcher);
}
