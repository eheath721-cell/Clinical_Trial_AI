"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function AppIndex() {
  const { profiles, activeProfileId } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (!profiles) return;
    const active = profiles.find((p) => p.id === activeProfileId) ?? profiles[0];
    if (!active || !active.onboarding_completed) router.replace("/app/onboarding");
    else router.replace("/app/trials");
  }, [profiles, activeProfileId, router]);
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <Spinner />
    </div>
  );
}
