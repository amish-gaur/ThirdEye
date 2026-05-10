"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Aurora } from "@/components/magic/Aurora";
import { ShimmerText } from "@/components/magic/ShimmerText";
import {
  addCamera,
  discoverCameras,
  startPairing,
  type CameraEntry,
  type DiscoveredCamera,
} from "@/lib/api";
import { useCameras } from "@/lib/liveStore";
import { cn } from "@/lib/utils";

const STEPS = ["Sign in", "Pair first node", "Contacts", "Consents", "Done"];

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [pair, setPair] = useState<{ pair_code: string; qr_payload: string } | null>(
    null
  );
  const router = useRouter();

  return (
    <div className="mx-auto max-w-[680px]">
      <section className="relative overflow-hidden rounded-[28px] border border-maroon-300/10 bg-maroon-900/20 px-8 pt-10 pb-8 mb-6 ring-glow">
        <Aurora />
        <div className="relative z-[2]">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
            Setup
          </div>
          <h1 className="mt-3 font-serif text-[44px] leading-[1.05] text-cream-50 text-balance">
            Stand up your home <ShimmerText>in five minutes</ShimmerText>.
          </h1>
        </div>
      </section>

      <Stepper step={step} />

      <div className="mt-6 card-glass ring-glow rounded-2xl p-7">
        {step === 0 && (
          <Stage
            title="Sign in with Clerk"
            body="Production auth: works the same on web and mobile. We never store passwords ourselves."
            cta="Continue"
            onContinue={() => setStep(1)}
          />
        )}

        {step === 1 && <PairNodeStep onContinue={() => setStep(2)} pair={pair} setPair={setPair} />}

        {step === 2 && (
          <Stage
            title="Who should we reach?"
            body="We'll ring this number first on Tier-3 alerts and fan out to family on Tier 4."
            cta="Continue"
            onContinue={() => setStep(3)}
          >
            <input
              placeholder="Your phone number"
              defaultValue="+1 555 0142"
              className="mt-4 w-full rounded-xl border border-maroon-300/20 bg-maroon-950/60 px-4 py-3 text-[15px] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
            />
            <input
              placeholder="Family or emergency contact"
              defaultValue="+1 555 8821"
              className="mt-2 w-full rounded-xl border border-maroon-300/20 bg-maroon-950/60 px-4 py-3 text-[15px] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
            />
          </Stage>
        )}

        {step === 3 && (
          <Stage
            title="A few consents"
            body="Recording laws vary by state. Tell us where this camera lives so the system stays on the right side of the line."
            cta="Continue"
            onContinue={() => setStep(4)}
          >
            <label className="mt-3 flex items-start gap-2 text-[14px] text-cream-50/85">
              <input type="checkbox" defaultChecked className="mt-1 accent-cream-50" />
              I'm permitted to record at this location.
            </label>
            <label className="mt-2 flex items-start gap-2 text-[14px] text-cream-50/85">
              <input type="checkbox" defaultChecked className="mt-1 accent-cream-50" />
              Run inference locally on this device. Frames don't leave my home network.
            </label>
          </Stage>
        )}

        {step === 4 && (
          <div>
            <h2 className="font-serif text-[28px] text-cream-50">You're set.</h2>
            <p className="mt-2 text-[14px] text-cream-50/70">
              Your camera mesh is live. Add more nodes anytime from Settings.
            </p>
            <button
              onClick={() => router.push("/")}
              className="mt-5 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
            >
              Open the dashboard
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Step 1 of the onboarding wizard. Three paths in priority order:
 *
 *   1. Discover LAN cameras via the action router's `/api/discover`
 *      (the brain runs zeroconf and returns whatever is advertising
 *      `_safewatch._tcp` — protocol identifier kept for compat). Pick
 *      one → POST `/api/cameras/add` to spawn
 *      a vision engine on the brain. This is the real production flow.
 *   2. Manual URL entry — for cameras the demo brain doesn't pick up
 *      automatically (e.g. a phone running the iOS streamer not yet on
 *      the same LAN, or a tunneled stream).
 *   3. The legacy QR pairing flow stays as a fallback for non-LAN
 *      pairing — it still talks to the MSW mock until that endpoint is
 *      backed by the real router.
 */
function PairNodeStep({
  onContinue,
  pair,
  setPair,
}: {
  onContinue: () => void;
  pair: { pair_code: string; qr_payload: string } | null;
  setPair: (p: { pair_code: string; qr_payload: string } | null) => void;
}) {
  const { cameras, refreshCameras } = useCameras();
  const [discovered, setDiscovered] = useState<DiscoveredCamera[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualUrl, setManualUrl] = useState("");
  const [manualName, setManualName] = useState("Front camera");

  const scan = async () => {
    setScanning(true);
    setError(null);
    try {
      const list = await discoverCameras(4);
      setDiscovered(list);
      if (list.length === 0) {
        setError("No cameras advertising on this LAN. Try the manual URL below.");
      }
    } finally {
      setScanning(false);
    }
  };

  // Run a discover automatically the first time the user lands on this step.
  useEffect(() => {
    if (discovered === null && !scanning) scan();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const register = async (name: string, url: string) => {
    setBusy(url);
    setError(null);
    try {
      const entry: CameraEntry | null = await addCamera(name, url);
      if (!entry) {
        setError(
          "Couldn't add that stream. Make sure the URL is on the LAN (HTTP/RTSP, private IP)."
        );
        return;
      }
      await refreshCameras();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <h2 className="font-serif text-[26px] text-cream-50">
        Pair your first camera
      </h2>
      <p className="mt-2 text-[14px] text-cream-50/70">
        ThirdEye ran a quick scan on your local network. Pick a camera below
        — adding one tells the brain to spawn a vision engine for it. You
        can always add more later from Settings.
      </p>

      <div className="mt-5 flex items-center gap-2">
        <button
          onClick={scan}
          disabled={scanning}
          className="rounded-full border border-maroon-300/30 px-4 py-1.5 text-[12.5px] text-cream-50 hover:bg-maroon-300/10 disabled:opacity-50"
        >
          {scanning ? "Scanning…" : "Scan LAN again"}
        </button>
        {cameras.length > 0 && (
          <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-cream-50/55">
            {cameras.length} registered
          </span>
        )}
      </div>

      {discovered && discovered.length > 0 && (
        <div className="mt-4 grid gap-2">
          {discovered.map((d) => {
            const already = cameras.some((c) => c.stream_url === d.stream_url);
            return (
              <div
                key={d.stream_url}
                className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-xl border border-maroon-300/15 bg-maroon-950/60 px-4 py-3"
              >
                <div>
                  <div className="text-[14px] text-cream-50">{d.name}</div>
                  <div className="font-mono text-[11px] text-cream-50/55">
                    {d.host}:{d.port} · {d.stream_url}
                  </div>
                </div>
                <button
                  disabled={busy !== null || already}
                  onClick={() => register(d.name, d.stream_url)}
                  className="rounded-full bg-cream-50 px-4 py-1.5 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100 disabled:opacity-50"
                >
                  {already ? "Added" : busy === d.stream_url ? "Adding…" : "Add"}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-5 rounded-xl border border-maroon-300/15 bg-maroon-950/40 px-4 py-4">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
          Or paste a stream URL
        </div>
        <div className="mt-2 grid grid-cols-[1fr_1.6fr_auto] gap-2">
          <input
            value={manualName}
            onChange={(e) => setManualName(e.target.value)}
            placeholder="Camera name"
            className="rounded-lg border border-maroon-300/20 bg-maroon-950/60 px-3 py-2 text-[13px] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
          />
          <input
            value={manualUrl}
            onChange={(e) => setManualUrl(e.target.value)}
            placeholder="http://192.168.1.42:8765/stream"
            className="rounded-lg border border-maroon-300/20 bg-maroon-950/60 px-3 py-2 font-mono text-[12px] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
          />
          <button
            disabled={!manualUrl || busy !== null}
            onClick={() => register(manualName || "Camera", manualUrl)}
            className="rounded-lg bg-cream-50 px-4 py-2 text-[12.5px] font-medium text-maroon-900 hover:bg-cream-100 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-maroon-200/40 bg-maroon-900/40 px-4 py-2 font-mono text-[11.5px] text-cream-50/80">
          {error}
        </div>
      )}

      {cameras.length > 0 && (
        <div className="mt-5">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
            Registered nodes
          </div>
          <ul className="mt-2 grid gap-1.5">
            {cameras.map((c) => (
              <li
                key={c.node_id}
                className="flex items-center justify-between rounded-md bg-maroon-300/5 px-3 py-1.5 font-mono text-[11.5px] text-cream-50/80"
              >
                <span>
                  {c.name} <span className="opacity-50">· {c.node_id}</span>
                </span>
                <span
                  className={
                    c.status === "running"
                      ? "text-cream-50"
                      : c.status === "warming"
                      ? "text-maroon-200"
                      : "text-cream-50/45"
                  }
                >
                  ● {c.status}
                </span>
              </li>
            ))}
          </ul>
          <button
            onClick={onContinue}
            className="mt-5 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
          >
            Continue
          </button>
        </div>
      )}

      {/* Legacy QR fallback — keeps working off the MSW mock until the
          backend exposes a real /api/pair endpoint. Hidden behind a
          disclosure so it doesn't compete with the LAN flow above. */}
      {cameras.length === 0 && (
        <details className="mt-6 text-[13px] text-cream-50/65">
          <summary className="cursor-pointer font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
            Pair off-LAN with a QR code instead
          </summary>
          <div className="mt-3">
            {!pair && (
              <button
                onClick={async () => setPair(await startPairing())}
                className="rounded-full border border-maroon-300/30 px-4 py-1.5 text-[12.5px] text-cream-50 hover:bg-maroon-300/10"
              >
                Generate pairing code
              </button>
            )}
            {pair && (
              <div className="mt-4 grid grid-cols-[auto_1fr] items-center gap-6">
                <FauxQR text={pair.qr_payload} />
                <div>
                  <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
                    Or type this code
                  </div>
                  <div className="mt-2 font-mono text-[34px] tracking-[0.32em] text-cream-50">
                    {pair.pair_code}
                  </div>
                  <button
                    onClick={onContinue}
                    className="mt-5 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
                  >
                    Node paired. Continue
                  </button>
                </div>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function Stepper({ step }: { step: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {STEPS.map((label, i) => (
        <div key={label} className="flex items-center gap-2">
          <div
            className={cn(
              "grid h-6 w-6 place-items-center rounded-full font-mono text-[11px] font-semibold",
              i <= step
                ? "bg-cream-50 text-maroon-900"
                : "bg-maroon-300/10 text-cream-50/40"
            )}
          >
            {i + 1}
          </div>
          <span
            className={cn(
              "text-[12px]",
              i === step ? "text-cream-50" : "text-cream-50/40"
            )}
          >
            {label}
          </span>
          {i < STEPS.length - 1 && <span className="text-cream-50/20">·</span>}
        </div>
      ))}
    </div>
  );
}

function Stage({
  title,
  body,
  cta,
  onContinue,
  children,
}: {
  title: string;
  body: string;
  cta: string;
  onContinue: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <h2 className="font-serif text-[26px] text-cream-50">{title}</h2>
      <p className="mt-2 text-[14px] text-cream-50/70">{body}</p>
      {children}
      <button
        onClick={onContinue}
        className="mt-5 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
      >
        {cta}
      </button>
    </div>
  );
}

function FauxQR({ text }: { text: string }) {
  const cells = 17;
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = (h * 33 + text.charCodeAt(i)) >>> 0;
  }
  const grid: boolean[] = [];
  let s = h;
  for (let i = 0; i < cells * cells; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    grid.push((s & 1) === 1);
  }
  return (
    <div
      className="grid rounded-xl border border-maroon-300/20 bg-cream-50 p-2"
      style={{
        width: 168,
        height: 168,
        gridTemplateColumns: `repeat(${cells}, 1fr)`,
        gap: 1,
      }}
    >
      {grid.map((on, i) => (
        <div
          key={i}
          style={{ background: on ? "#1F050A" : "transparent" }}
        />
      ))}
    </div>
  );
}
