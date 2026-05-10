import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { motion } from "motion/react";
import { ShieldCheck } from "lucide-react";
import {
  claimIdentity,
  fetchHealth,
  fetchWarmup,
  type BackendHealth,
  type IdentitySession,
  type WarmupStatus,
} from "./api";

const STORAGE_KEY = "thirdeye.identity.v1";

type IdentityValue = {
  identity: IdentitySession | null;
  ready: boolean;
  claim: (code: string) => Promise<IdentitySession | null>;
  signOut: () => void;
};

const IdentityContext = createContext<IdentityValue | null>(null);

/**
 * Phone hands the user a 6-character code; the web `LoginGate` accepts it
 * and POSTs `/api/identity/by-code/{code}/claim`. Claim response is stashed
 * in localStorage so a refresh or redeploy keeps the session alive until
 * `signOut()` (or the router restarts and the in-memory store empties).
 */
export function IdentityProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<IdentitySession | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as IdentitySession;
        if (parsed?.session_id && parsed.name && parsed.email) setIdentity(parsed);
      }
    } catch {
      /* private mode / quota — fine */
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
        /* ignore */
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

  return (
    <IdentityContext.Provider value={value}>{children}</IdentityContext.Provider>
  );
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

/**
 * Backend health + warmup polled and shared. We don't open SSE here —
 * the dashboard's `useIncidentStream` already does, and adding a second
 * subscription would double-count incidents.
 */
type BackendValue = {
  health: BackendHealth | null;
  state: "connecting" | "live" | "offline";
  warmup: WarmupStatus | null;
};

const BackendContext = createContext<BackendValue | null>(null);

export function BackendProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [state, setState] = useState<BackendValue["state"]>("connecting");
  const [warmup, setWarmup] = useState<WarmupStatus | null>(null);
  const warmupTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const h = await fetchHealth();
      if (cancelled) return;
      if (h && h.status === "ok") {
        setHealth(h);
        setState("live");
      } else {
        setState("offline");
      }
    };
    tick();
    const id = window.setInterval(tick, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const w = await fetchWarmup();
      if (cancelled) return;
      setWarmup(w);
      const delay = w?.state === "ready" ? 10_000 : 2_000;
      warmupTimer.current = window.setTimeout(tick, delay);
    };
    tick();
    return () => {
      cancelled = true;
      if (warmupTimer.current !== undefined) window.clearTimeout(warmupTimer.current);
    };
  }, []);

  const value = useMemo<BackendValue>(
    () => ({ health, state, warmup }),
    [health, state, warmup]
  );

  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}

export function useBackend(): BackendValue {
  const ctx = useContext(BackendContext);
  if (!ctx) {
    return { health: null, state: "connecting", warmup: null };
  }
  return ctx;
}

const C = {
  cream: "#f4ead8",
  ink: "#1a0306",
  red: "#c8222d",
  orange: "#e85a3c",
  gold: "#f4c97a",
  wine: "#7a2230",
  deep: "#3a1014",
};

const CODE_LENGTH = 6;

/**
 * Full-screen login gate. Renders when the user isn't signed in yet;
 * accepts the 6-char code from the iPhone and claims the session.
 *
 * We intentionally don't render the rest of the app behind it — until the
 * web has an identity, audit-logged actions don't have a person to attribute
 * to. (View-only screens can be made public later by hoisting this gate.)
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { identity, ready, claim } = useIdentity();
  const { state, warmup } = useBackend();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (code.length === CODE_LENGTH && !busy) submit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const submit = async () => {
    if (busy) return;
    const c = code.trim().toUpperCase();
    if (c.length !== CODE_LENGTH) {
      setError(`Code must be ${CODE_LENGTH} characters`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await claim(c);
      if (!session) {
        setError("That code didn't match. Codes expire after 10 minutes.");
        setCode("");
      }
    } finally {
      setBusy(false);
    }
  };

  if (!ready) return null;
  if (identity) return <>{children}</>;

  const warmLabel =
    warmup?.state === "ready"
      ? `models warm · ${warmup.elapsed_s.toFixed(1)}s`
      : warmup?.state === "warming"
      ? `warming · ${warmup.elapsed_s.toFixed(1)}s`
      : "models cold";

  return (
    <div
      className="min-h-screen w-full grid place-items-center px-6"
      style={{ background: C.cream, color: C.ink }}
    >
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-[520px]"
      >
        <div
          className="relative px-7 py-8 rounded-[18px]"
          style={{ background: C.cream, border: `4px solid ${C.ink}`, boxShadow: `0 8px 0 ${C.ink}` }}
        >
          <div
            className="text-[10px] tracking-[0.4em] mb-3 flex items-center gap-2"
            style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
          >
            <ShieldCheck size={12} /> SIGN IN · WITH IPHONE
          </div>
          <h1
            style={{
              fontFamily: "Playfair Display, serif",
              fontWeight: 700,
              fontSize: "44px",
              lineHeight: 1.05,
              color: C.ink,
            }}
          >
            Pair your <span style={{ color: C.red, fontStyle: "italic" }}>phone.</span>
          </h1>
          <p className="mt-3 text-[14px] leading-[1.7]" style={{ color: C.deep }}>
            Open ThirdEye on your iPhone, finish onboarding, then type the 6-character
            code below. Your phone vouches for the session — the web stays signed in
            until you sign out.
          </p>

          <input
            autoFocus
            value={code}
            maxLength={CODE_LENGTH}
            onChange={(e) =>
              setCode(e.target.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase())
            }
            placeholder="A B C 1 2 3"
            className="mt-6 w-full px-5 py-4 outline-none"
            style={{
              fontFamily: "DM Mono, monospace",
              letterSpacing: "0.32em",
              fontSize: 30,
              fontWeight: 700,
              color: C.ink,
              background: C.gold,
              border: `4px solid ${C.ink}`,
              borderRadius: 14,
              textAlign: "center",
            }}
          />

          {error && (
            <div
              className="mt-3 px-3 py-2 text-[11px] tracking-[0.18em]"
              style={{
                fontFamily: "DM Mono, monospace",
                color: C.red,
                background: "rgba(200,34,45,0.08)",
                border: `2px solid ${C.red}`,
                borderRadius: 10,
              }}
            >
              {error.toUpperCase()}
            </div>
          )}

          <div className="mt-5 flex items-center justify-between">
            <div className="flex flex-col gap-1">
              <span
                className="text-[10px] tracking-[0.22em] flex items-center gap-2"
                style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background:
                      state === "live" ? "#3a8e54" : state === "connecting" ? C.gold : C.red,
                    border: `1.5px solid ${C.ink}`,
                  }}
                />
                BACKEND · {state.toUpperCase()}
              </span>
              <span
                className="text-[10px] tracking-[0.22em]"
                style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.85 }}
              >
                {warmLabel.toUpperCase()}
              </span>
            </div>
            <motion.button
              whileTap={{ scale: 0.96 }}
              disabled={busy || code.length !== CODE_LENGTH}
              onClick={submit}
              className="px-5 py-2.5 rounded-full text-[12px] tracking-[0.2em] disabled:opacity-50"
              style={{
                fontFamily: "DM Mono, monospace",
                background: C.red,
                color: C.cream,
                border: `3px solid ${C.ink}`,
                boxShadow: `0 4px 0 ${C.ink}`,
              }}
            >
              {busy ? "SIGNING IN…" : "SIGN IN"}
            </motion.button>
          </div>
        </div>

        <div
          className="mt-4 px-1 text-[10px] tracking-[0.22em]"
          style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.7 }}
        >
          NEW HERE? OPEN THE PHONE APP — IT WILL WALK YOU THROUGH NAME, EMAIL, FACE, PIN.
        </div>
      </motion.div>
    </div>
  );
}
