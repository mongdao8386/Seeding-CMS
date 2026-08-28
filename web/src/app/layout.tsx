import type { Metadata } from "next";
import Link from "next/link";
import { SignOut, TokenGate } from "@/components/token-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Seeding CMS",
  description: "Compose, schedule and publish content across account groups",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/compose", label: "Compose" },
  { href: "/media", label: "Media" },
  { href: "/hashtags", label: "Hashtags" },
  { href: "/schedule", label: "Schedule" },
  { href: "/accounts", label: "Accounts" },
  { href: "/takeovers", label: "Takeovers" },
  { href: "/analytics", label: "Survival" },
  { href: "/settings", label: "Hours" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header
          className="border-b"
          style={{ borderColor: "var(--rule)", background: "var(--surface)" }}
        >
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
            <Link href="/" className="mono text-sm font-semibold tracking-tight">
              seeding<span style={{ color: "var(--b)" }}>·</span>cms
            </Link>
            <nav className="flex flex-wrap gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded px-2.5 py-1 text-sm hover:opacity-70"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-4">
              <span className="label">localhost only</span>
              <SignOut />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">
          <TokenGate>{children}</TokenGate>
        </main>
      </body>
    </html>
  );
}
