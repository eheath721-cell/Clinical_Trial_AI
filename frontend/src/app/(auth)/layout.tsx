import Link from "next/link";

import { Logo, SyntheticBanner } from "@/components/domain";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <SyntheticBanner />
      <header className="container-page py-5">
        <Link href="/" aria-label="Home"><Logo /></Link>
      </header>
      <main className="container-page flex flex-1 items-start justify-center pb-16 pt-6 sm:pt-12">{children}</main>
    </div>
  );
}
