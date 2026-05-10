"use client";
import { useEffect, useState } from "react";
import { LiveProvider } from "@/lib/liveStore";
import { IdentityProvider } from "@/lib/identity";

/**
 * Provider that boots MSW for the legacy mock-only endpoints (pairing
 * QR codes, the contacts editor, the Ask page demo) while letting real
 * fetches to the action router pass straight through. MSW intercepts
 * relative `/api/*` URLs only; absolute-URL hits from `lib/api.ts`
 * (`http://localhost:8001/api/cameras` etc.) bypass the worker.
 *
 * `LiveProvider` always mounts — it owns the `/health`, `/api/cameras`,
 * and `/events/stream` connections shared across pages.
 */
export function MockProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (typeof window === "undefined") return;

    (async () => {
      try {
        const { worker } = await import("@/mocks/browser");
        await worker.start({
          onUnhandledRequest: "bypass",
          serviceWorker: { url: "/mockServiceWorker.js" },
        });
      } catch {
        // MSW failure shouldn't block the app — worst case the legacy
        // mock-only pages render empty until those endpoints are real.
      }
      if (!cancelled) setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center font-mono text-[12px] uppercase tracking-[0.2em] text-maroon-200">
        booting local mocks…
      </div>
    );
  }
  return (
    <IdentityProvider>
      <LiveProvider>{children}</LiveProvider>
    </IdentityProvider>
  );
}
