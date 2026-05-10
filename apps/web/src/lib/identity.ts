"use client";

/**
 * Identity context for the web app.
 *
 * The phone enters name/email and POSTs `/api/identity`, which returns a
 * 6-digit code. The user types that code on the web `/login` page; the
 * web POSTs `/api/identity/by-code/{code}/claim` and stores the returned
 * `IdentitySession` in localStorage so subsequent visits stay logged in.
 *
 * `useIdentity()` is the read hook; `useIdentityActions()` exposes
 * `claim` / `signOut`. We deliberately don't auto-redirect from this
 * module — the `RootView`-equivalent in `MockProvider` decides whether
 * to show a login banner or full chrome based on the value here.
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { claimIdentity, type IdentitySession } from "./api";

const STORAGE_KEY = "safewatch.identity.v1";

interface IdentityValue {
  identity: IdentitySession | null;
  ready: boolean;
  claim: (code: string) => Promise<IdentitySession | null>;
  signOut: () => void;
}

const IdentityContext = createContext<IdentityValue | null>(null);

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<IdentitySession | null>(null);
  const [ready, setReady] = useState(false);

  // Hydrate from localStorage on mount. We accept any shape that has the
  // required fields — older versions of the schema get dropped silently.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as IdentitySession;
        if (parsed && parsed.session_id && parsed.name && parsed.email) {
          setIdentity(parsed);
        }
      }
    } catch {
      /* ignore quota / parse errors */
    } finally {
      setReady(true);
    }
  }, []);

  const claim = useCallback(async (code: string) => {
    const session = await claimIdentity(code);
    if (session && session.status === "claimed") {
      setIdentity(session);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
      } catch {
        /* localStorage may be unavailable in private mode — fine */
      }
      return session;
    }
    return null;
  }, []);

  const signOut = useCallback(() => {
    setIdentity(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<IdentityValue>(
    () => ({ identity, ready, claim, signOut }),
    [identity, ready, claim, signOut]
  );

  return createElement(IdentityContext.Provider, { value }, children);
}

export function useIdentity(): IdentityValue {
  const ctx = useContext(IdentityContext);
  if (!ctx) {
    return {
      identity: null,
      ready: true,
      claim: async () => null,
      signOut: () => {},
    };
  }
  return ctx;
}
