"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { ReadyPillar } from "@/components/ReadyPillar";
import { useIdentity } from "@/lib/identity";

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
  const router = useRouter();
  const { identity, signOut } = useIdentity();
  const initials = identity
    ? identity.name
        .split(/\s+/)
        .map((p) => p[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : null;
  return (
    <nav className="sticky top-0 z-30 border-b border-maroon-300/10 bg-maroon-950/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1280px] items-center gap-8 px-7 py-3.5">
        <Link
          href="/"
          className="font-serif text-[22px] font-semibold tracking-tight text-cream-50"
        >
          ThirdEye
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

        <ReadyPillar variant="compact" />

        {identity ? (
          <div className="flex items-center gap-2">
            <span
              className="grid h-7 w-7 place-items-center rounded-full bg-cream-50 font-mono text-[11px] font-semibold text-maroon-900"
              title={`${identity.name} · ${identity.email}`}
            >
              {initials}
            </span>
            <span className="hidden md:inline-block max-w-[180px] truncate text-[12.5px] text-cream-50/85">
              {identity.name.split(/\s+/)[0]}
            </span>
            <button
              onClick={() => {
                signOut();
                router.push("/login");
              }}
              className="rounded-full border border-maroon-300/30 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-cream-50/70 hover:bg-maroon-300/10"
            >
              Sign out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="rounded-full border border-maroon-300/30 px-4 py-1.5 text-[13px] text-cream-50 hover:bg-maroon-300/10"
          >
            Sign in
          </Link>
        )}

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
