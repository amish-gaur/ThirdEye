"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const items = [
  { href: "/", label: "Dashboard" },
  { href: "/live", label: "Live" },
  { href: "/timeline", label: "Timeline" },
  { href: "/ask", label: "Ask" },
  { href: "/edge", label: "Edge inference" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="sticky top-0 z-30 border-b border-maroon-300/10 bg-maroon-950/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1280px] items-center gap-8 px-7 py-3.5">
        <Link
          href="/"
          className="font-serif text-[22px] font-semibold tracking-tight text-cream-50"
        >
          SafeWatch
          <span className="ml-1 text-maroon-300">·</span>
        </Link>

        <div className="flex flex-1 items-center gap-1">
          {items.map((it) => {
            const active =
              it.href === "/" ? pathname === "/" : pathname.startsWith(it.href);
            return (
              <Link
                key={it.href}
                href={it.href}
                className={cn(
                  "px-3 py-1.5 text-[13px] rounded-full transition-colors",
                  active
                    ? "bg-cream-50 text-maroon-900"
                    : "text-cream-50/70 hover:text-cream-50 hover:bg-maroon-700/40"
                )}
              >
                {it.label}
              </Link>
            );
          })}
        </div>

        <span className="hidden sm:inline-flex items-center gap-1.5 rounded-full border border-maroon-300/15 bg-maroon-900/40 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-maroon-100">
          <span className="h-1.5 w-1.5 rounded-full bg-maroon-200 animate-pulse-soft" />
          local inference
        </span>

        <Link
          href="/onboarding"
          className="rounded-full border border-maroon-300/30 px-4 py-1.5 text-[13px] text-cream-50 hover:bg-maroon-300/10"
        >
          Set up
        </Link>
      </div>
    </nav>
  );
}
