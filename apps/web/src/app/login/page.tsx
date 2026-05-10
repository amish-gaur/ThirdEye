"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Aurora } from "@/components/magic/Aurora";
import { ReadyPillar } from "@/components/ReadyPillar";
import { ShimmerText } from "@/components/magic/ShimmerText";
import { useIdentity } from "@/lib/identity";
import { useWarmup } from "@/lib/liveStore";

const CODE_LENGTH = 6;

/**
 * Phone → web login screen.
 *
 *   1. The iPhone (during onboarding) POSTs `/api/identity {name, email}`
 *      and shows the user a 6-digit code.
 *   2. The user opens this page and types the code.
 *   3. We POST `/api/identity/by-code/{code}/claim`; on success the
 *      `IdentityProvider` stashes the session in localStorage and the
 *      next render shows them logged in.
 *
 * Whilst the user is reading the code off their phone, the action router
 * is already alive and the vision pipeline is loading models — by the
 * time they hit "Sign in" Qwen is typically warm. The sidebar reflects
 * that with a live `models · …` chip.
 */
export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { identity, claim } = useIdentity();
  const warmup = useWarmup();

  const [code, setCode] = useState((params.get("code") ?? "").toUpperCase());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (identity) {
      router.replace("/");
    }
  }, [identity, router]);

  // Auto-submit when the user types a full code (lets QR-pasted codes
  // sign in without a click).
  useEffect(() => {
    if (code.length === CODE_LENGTH && !busy) {
      submit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const submit = async () => {
    if (busy) return;
    const sanitized = code.trim().toUpperCase();
    if (sanitized.length !== CODE_LENGTH) {
      setError(`Code must be ${CODE_LENGTH} characters`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await claim(sanitized);
      if (!session) {
        setError(
          "That code didn't match — check your phone and try again. Codes expire after 10 minutes."
        );
        inputRef.current?.focus();
        return;
      }
      router.replace("/");
    } finally {
      setBusy(false);
    }
  };

  const warmLabel =
    warmup?.state === "ready"
      ? `models warm · ${warmup.elapsed_s.toFixed(1)}s`
      : warmup?.state === "warming"
      ? `models warming · ${warmup.elapsed_s.toFixed(1)}s`
      : "models · cold (start a camera to preload)";

  return (
    <div className="mx-auto max-w-[640px]">
      <section className="relative overflow-hidden rounded-[28px] border border-maroon-300/10 bg-maroon-900/20 px-8 pt-10 pb-8 mb-6 ring-glow">
        <Aurora />
        <div className="relative z-[2]">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
            Sign in
          </div>
          <h1 className="mt-3 font-serif text-[44px] leading-[1.05] text-cream-50 text-balance">
            Sign in <ShimmerText>with iPhone</ShimmerText>.
          </h1>
          <p className="mt-3 max-w-[52ch] text-[14.5px] text-cream-50/70">
            Open the ThirdEye app on your phone, finish onboarding, and type
            the 6-character code it shows you. Your phone vouches for the
            session — the web stays logged in until you sign out.
          </p>
          <div className="mt-5">
            <ReadyPillar variant="hero" />
          </div>
        </div>
      </section>

      <div className="card-glass ring-glow rounded-2xl p-7">
        <label className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
          Pairing code
        </label>
        <input
          ref={inputRef}
          autoFocus
          inputMode="text"
          autoComplete="one-time-code"
          maxLength={CODE_LENGTH}
          value={code}
          onChange={(e) =>
            setCode(e.target.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase())
          }
          placeholder="A B C 1 2 3"
          className="mt-2 w-full rounded-xl border border-maroon-300/20 bg-maroon-950/60 px-5 py-4 font-mono text-[34px] tracking-[0.32em] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
        />
        {error && (
          <div className="mt-3 rounded-md border border-maroon-200/40 bg-maroon-900/40 px-3 py-2 font-mono text-[11.5px] text-cream-50/85">
            {error}
          </div>
        )}
        <div className="mt-4 flex items-center justify-between">
          <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-cream-50/55">
            {warmLabel}
          </span>
          <button
            onClick={submit}
            disabled={busy || code.length !== CODE_LENGTH}
            className="rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </div>

      <details className="mt-6 text-[13px] text-cream-50/60">
        <summary className="cursor-pointer font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
          No phone handy?
        </summary>
        <p className="mt-2">
          You can still poke around without signing in — the dashboard,
          timeline, and onboarding pages all work read-only. Critical actions
          (acknowledging incidents, editing contacts) require a signed-in
          session so the audit log can attribute them to a person.
        </p>
      </details>
    </div>
  );
}
