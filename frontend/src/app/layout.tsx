import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";

import { SessionProvider } from "@/lib/session";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "TrialCompass — find clinical trials you may qualify for", template: "%s · TrialCompass" },
  description:
    "Tell us about your health. We search the clinical research ecosystem, explain which trials you may qualify for and why, and help you contact research teams.",
};

export const viewport: Viewport = { themeColor: "#f7f6f2", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
