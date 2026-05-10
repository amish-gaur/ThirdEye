"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Aurora } from "@/components/magic/Aurora";
import { ShimmerText } from "@/components/magic/ShimmerText";
import { startPairing } from "@/lib/api";
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
            body="Production auth - works the same on web and mobile. We never store passwords ourselves."
            cta="Continue"
            onContinue={() => setStep(1)}
          />
        )}

        {step === 1 && (
          <div>
            <h2 className="font-serif text-[26px] text-cream-50">
              Pair your first camera node
            </h2>
            <p className="mt-2 text-[14px] text-cream-50/70">
              On the device that will run inference (this laptop, an old phone),
              open SafeWatch and scan this QR. The node joins your home mesh - no
              router config, no port forwarding.
            </p>
            {!pair && (
              <button
                onClick={async () => setPair(await startPairing())}
                className="mt-4 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
              >
                Generate pairing code
              </button>
            )}
            {pair && (
              <div className="mt-5 grid grid-cols-[auto_1fr] items-center gap-6">
                <FauxQR text={pair.qr_payload} />
                <div>
                  <div className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-maroon-200/70">
                    Or type this code
                  </div>
                  <div className="mt-2 font-mono text-[34px] tracking-[0.32em] text-cream-50">
                    {pair.pair_code}
                  </div>
                  <button
                    onClick={() => setStep(2)}
                    className="mt-5 rounded-full bg-cream-50 px-5 py-2 text-[13px] font-medium text-maroon-900 hover:bg-cream-100"
                  >
                    Node paired - continue
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

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
