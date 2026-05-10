import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  Bell,
  Eye,
  MessageSquareText,
  Radio,
  Settings,
  ShieldCheck,
  Cpu,
} from "lucide-react";
import { SecurityEye } from "./components/SecurityEye";
import { EyeText } from "./components/EyeText";
import { RobberLoader } from "./components/RobberLoader";
import { IncidentRow, type Tier } from "./components/IncidentRow";
import { RobberWaiting } from "./components/RobberWaiting";
import { AmbientBg } from "./components/AmbientBg";
import { CornerCamera } from "./components/CornerCamera";
import { WaterTower } from "./components/WaterTower";
import { CameraTile } from "./components/CameraTile";
import { ThirdEyeLogo } from "./components/ThirdEyeLogo";
import {
  BACKEND_URL,
  addCamera,
  discoverCameras,
  fetchCameras,
  formatTime,
  statusFromEntry,
  suspectFrameUrl,
  tierFromName,
  type CameraEntry,
  type DiscoveredCamera,
  type StreamMessage,
} from "./lib/api";
import {
  BackendProvider,
  IdentityProvider,
  LoginGate,
  useBackend,
  useIdentity,
} from "./lib/identity";

type IncidentRowData = {
  tier: Tier;
  title: string;
  node: string;
  time: string;
  imgUrl: string | null;
};

function useIncidentStream(): IncidentRowData[] {
  const [items, setItems] = useState<IncidentRowData[]>([]);
  useEffect(() => {
    const es = new EventSource(`${BACKEND_URL}/events/stream`);
    es.onmessage = (msg) => {
      try {
        const parsed: StreamMessage = JSON.parse(msg.data);
        const ev = parsed.event ?? {};
        if (parsed.result?.duplicate) return;
        const row: IncidentRowData = {
          // Router may downgrade tier (confidence floor, behavior ceiling) - trust its label.
          tier: tierFromName(parsed.result?.tier_label ?? ev.tier_name),
          title: ev.one_line_summary ?? ev.suspect_description ?? "(no summary)",
          node: `${ev.node_id ?? "NODE-?"}${ev.scene ? ` · ${ev.scene.toUpperCase()}` : ""}`,
          time: formatTime(ev.timestamp),
          // Suspect JPEG written by action_router on THEFT_CONFIRMED (tier 3/4).
          imgUrl: suspectFrameUrl(ev),
        };
        setItems((prev) => [row, ...prev].slice(0, 50));
      } catch {
        // ignore malformed frames
      }
    };
    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do.
    };
    return () => es.close();
  }, []);
  return items;
}

function useCameras(): CameraEntry[] {
  const [cams, setCams] = useState<CameraEntry[]>([]);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const list = await fetchCameras();
      if (alive) setCams(list);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return cams;
}

function NodeRow({
  id,
  loc,
  status,
  delay = 0,
}: {
  id: string;
  loc: string;
  status: "live" | "idle" | "alert";
  delay?: number;
}) {
  const dot = status === "alert" ? "#c8222d" : status === "live" ? "#e85a3c" : "#7a6a55";
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.3 }}
      className="flex items-center justify-between px-3 py-2 rounded-lg"
      style={{ background: "#f4ead8", border: "3px solid #1a0306" }}
    >
      <div className="flex items-center gap-3">
        <motion.span
          className="w-2.5 h-2.5 rounded-full"
          style={{ background: dot, border: "2px solid #1a0306" }}
          animate={{ opacity: [1, 0.3, 1] }}
          transition={{ duration: 1.4, repeat: Infinity }}
        />
        <span
          className="text-[11px] tracking-[0.2em]"
          style={{ fontFamily: "DM Mono, monospace", color: "#1a0306" }}
        >
          {id} · {loc}
        </span>
      </div>
      <span
        className="text-[9px] tracking-[0.2em] px-2 py-0.5"
        style={{
          fontFamily: "DM Mono, monospace",
          background: status === "alert" ? "#c8222d" : "#1a0306",
          color: "#f4ead8",
        }}
      >
        {status.toUpperCase()}
      </span>
    </motion.div>
  );
}

const NAV = [
  { id: "dashboard", label: "Dashboard", icon: Activity },
  { id: "live", label: "Live", icon: Radio },
  { id: "timeline", label: "Timeline", icon: Bell },
  { id: "ask", label: "Ask", icon: MessageSquareText },
  { id: "edge", label: "Edge", icon: Cpu },
  { id: "settings", label: "Settings", icon: Settings },
];


// Incredibles palette
const C = {
  cream: "#f4ead8",
  ink: "#1a0306",
  red: "#c8222d",
  orange: "#e85a3c",
  gold: "#f4c97a",
  wine: "#7a2230",
  deep: "#3a1014",
};

export default function App() {
  return (
    <IdentityProvider>
      <BackendProvider>
        <LoginGate>
          <AppInner />
        </LoginGate>
      </BackendProvider>
    </IdentityProvider>
  );
}

function AppInner() {
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("dashboard");

  return (
    <div
      className="size-full min-h-screen relative overflow-hidden"
      style={{
        background: C.cream,
        color: C.ink,
        fontFamily: "Inter, sans-serif",
      }}
    >
      <AmbientBg />
      {/* big retro shapes - flat, with offset shadow blocks */}
      <div
        className="absolute pointer-events-none"
        style={{
          top: -130,
          right: -90,
          width: 360,
          height: 360,
          borderRadius: "50%",
          background: C.ink,
          opacity: 0.12,
          transform: "translate(10px,12px)",
        }}
      />
      <div
        className="absolute pointer-events-none"
        style={{
          top: -130,
          right: -90,
          width: 360,
          height: 360,
          borderRadius: "50%",
          background: C.gold,
          border: `4px solid ${C.ink}`,
        }}
      />
      <div
        className="absolute pointer-events-none"
        style={{
          bottom: -180,
          left: -140,
          width: 440,
          height: 440,
          borderRadius: "50%",
          background: C.orange,
          opacity: 0.5,
          border: `4px solid ${C.ink}`,
        }}
      />

      <AnimatePresence>
        {loading && <RobberLoader onDone={() => setLoading(false)} />}
      </AnimatePresence>

      <div className="relative z-10 max-w-[1320px] mx-auto px-8 py-6">
        <TopBar tab={tab} setTab={setTab} />
        <main className="mt-10 relative">
          {tab !== "dashboard" && <CornerCamera />}
          {tab === "dashboard" && <Dashboard />}
          {tab === "live" && <LiveView />}
          {tab === "timeline" && <Timeline />}
          {tab === "ask" && <AskView />}
          {tab === "edge" && <EdgeView />}
          {tab === "settings" && <SettingsView />}
        </main>
        <Footer />
      </div>
    </div>
  );
}

function Card({
  children,
  className = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={className}
      style={{
        background: C.cream,
        border: `4px solid ${C.ink}`,
        borderRadius: 18,
        boxShadow: `0 8px 0 ${C.ink}`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function TopBar({ tab, setTab }: { tab: string; setTab: (s: string) => void }) {
  return (
    <header className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <ThirdEyeLogo size={42} bg={C.cream} style={{ color: C.ink, flexShrink: 0 }} />
        <div>
          <div
            style={{
              fontFamily: "Playfair Display, serif",
              fontWeight: 900,
              fontSize: "26px",
              lineHeight: 1,
              letterSpacing: "-0.01em",
              color: C.ink,
            }}
          >
            Third <span style={{ color: C.red, fontStyle: "italic" }}>Eye</span>
          </div>
          <div
            className="text-[11px] tracking-[0.25em] mt-1"
            style={{ fontFamily: "DM Mono, monospace", color: C.wine }}
          >
            v0.4.2 · operator console
          </div>
        </div>
      </div>
      <nav
        className="flex items-center gap-1 p-1.5"
        style={{
          background: C.cream,
          border: `4px solid ${C.ink}`,
          borderRadius: 999,
          boxShadow: `0 4px 0 ${C.ink}`,
        }}
      >
        {NAV.map(({ id, label, icon: Icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="relative px-4 py-1.5 rounded-full flex items-center gap-2 text-[12px] tracking-[0.15em]"
              style={{
                fontFamily: "DM Mono, monospace",
                color: active ? C.cream : C.ink,
              }}
            >
              {active && (
                <motion.span
                  layoutId="nav-pill"
                  className="absolute inset-0 rounded-full"
                  style={{
                    background: C.red,
                    border: `3px solid ${C.ink}`,
                  }}
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <Icon size={13} className="relative z-10" />
              <span className="relative z-10 uppercase">{label}</span>
            </button>
          );
        })}
      </nav>
      <div className="flex items-center gap-3">
        <StatusPill />
        <IdentityBadge />
      </div>
    </header>
  );
}

function StatusPill() {
  const { state, warmup } = useBackend();
  const cameras = useCameras();
  const running = cameras.filter((c) => c.status === "running").length;
  const warming = cameras.filter((c) => c.status === "warming").length;

  // Pick the most-load-bearing label so a small pill conveys the right state.
  const label =
    state === "offline"
      ? "BACKEND OFFLINE"
      : warming > 0 && running === 0
      ? `WARMING · ${warmup?.elapsed_s.toFixed(0) ?? 0}S`
      : warmup?.state === "ready"
      ? `READY · ${running}/${cameras.length || 0} LIVE`
      : state === "live"
      ? "BACKEND READY"
      : "CONNECTING…";

  const bg =
    state === "offline" ? C.red : warmup?.state === "ready" ? "#3a8e54" : C.gold;
  const fg = state === "offline" || warmup?.state === "ready" ? C.cream : C.ink;

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 rounded-full"
      style={{
        background: bg,
        border: `3px solid ${C.ink}`,
        boxShadow: `0 3px 0 ${C.ink}`,
      }}
    >
      <motion.span
        className="w-2 h-2 rounded-full"
        style={{ background: fg, border: `1.5px solid ${C.ink}` }}
        animate={state === "live" ? { opacity: [1, 0.4, 1] } : { opacity: 1 }}
        transition={{ duration: 1.6, repeat: Infinity }}
      />
      <span
        className="text-[11px] tracking-[0.2em]"
        style={{ fontFamily: "DM Mono, monospace", color: fg }}
      >
        {label}
      </span>
    </div>
  );
}

function IdentityBadge() {
  const { identity, signOut } = useIdentity();
  if (!identity) return null;
  const initials = identity.name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <div className="flex items-center gap-2">
      <div
        className="grid place-items-center w-8 h-8 rounded-full"
        style={{
          background: C.gold,
          color: C.ink,
          border: `3px solid ${C.ink}`,
          fontFamily: "DM Mono, monospace",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0,
        }}
        title={`${identity.name} · ${identity.email}`}
      >
        {initials}
      </div>
      <button
        onClick={signOut}
        className="hidden md:inline-flex px-3 py-1.5 rounded-full text-[10px] tracking-[0.18em]"
        style={{
          fontFamily: "DM Mono, monospace",
          background: C.cream,
          color: C.ink,
          border: `2px solid ${C.ink}`,
        }}
      >
        SIGN OUT
      </button>
    </div>
  );
}

function Dashboard() {
  const incidents = useIncidentStream();
  const cameras = useCameras();
  const counts = incidents.reduce(
    (acc, i) => {
      acc[i.tier] = (acc[i.tier] ?? 0) + 1;
      return acc;
    },
    {} as Record<Tier, number>,
  );
  return (
    <div className="grid grid-cols-12 gap-8">
      <section className="col-span-7 relative">
        <div
          className="text-[10px] tracking-[0.4em] mb-6 flex items-center gap-2"
          style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
        >
          <ShieldCheck size={12} /> OPERATOR CONSOLE · ALL SYSTEMS LOCAL
        </div>
        <h1
          style={{
            fontFamily: "Playfair Display, serif",
            fontWeight: 700,
            fontSize: "60px",
            lineHeight: 1.05,
            letterSpacing: "-0.01em",
            color: C.ink,
          }}
        >
          <EyeText>Everything</EyeText>
          <br />
          <EyeText>calm at </EyeText>
          <span style={{ color: C.red, fontStyle: "italic" }}>home.</span>
        </h1>
        <p
          className="mt-6 max-w-[460px] text-[15px] leading-[1.7]"
          style={{ color: C.deep }}
        >
          Severity-aware sensors. Frames stay on-device. We escalate only when
          the world stops being calm: ambient, notice, alert, emergency.
        </p>

        <div className="mt-8 flex items-center gap-3">
          <motion.button
            whileHover={{ scale: 1.03, y: -2 }}
            whileTap={{ scale: 0.97, y: 0 }}
            className="px-5 py-3 rounded-full text-[12px] tracking-[0.2em]"
            style={{
              fontFamily: "DM Mono, monospace",
              background: C.red,
              color: C.cream,
              border: `3px solid ${C.ink}`,
              boxShadow: `0 4px 0 ${C.ink}`,
            }}
          >
            ACKNOWLEDGE FEED
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.03, y: -2 }}
            whileTap={{ scale: 0.97, y: 0 }}
            className="px-5 py-3 rounded-full text-[12px] tracking-[0.2em]"
            style={{
              fontFamily: "DM Mono, monospace",
              background: C.cream,
              color: C.ink,
              border: `3px solid ${C.ink}`,
              boxShadow: `0 4px 0 ${C.ink}`,
            }}
          >
            PAIR THIRD EYE
          </motion.button>
        </div>

        <TierLegend />
      </section>

      <section className="col-span-5 flex items-center justify-center">
        <div className="relative">
          <SecurityEye size={320} />
        </div>
      </section>

      <section className="col-span-7">
        <Card className="overflow-hidden">
          <div
            className="flex items-center justify-between px-5 py-4"
            style={{ borderBottom: `4px solid ${C.ink}`, background: C.gold }}
          >
            <div className="flex items-center gap-3">
              <motion.div
                className="w-3 h-3 rounded-full"
                style={{ background: C.red, border: `2px solid ${C.ink}` }}
                animate={{ scale: [1, 1.3, 1] }}
                transition={{ duration: 1.4, repeat: Infinity }}
              />
              <span
                className="text-[11px] tracking-[0.3em]"
                style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
              >
                INCIDENT FEED · LAST 24H
              </span>
            </div>
            <span
              className="text-[10px] tracking-[0.2em]"
              style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
            >
              {incidents.length} EVENTS · {counts.emergency ?? 0} EMERGENCY · {counts.alert ?? 0} ALERTS
            </span>
          </div>
          <div>
            {incidents.length === 0 && (
              <div
                className="px-5 py-6 text-[11px] tracking-[0.2em]"
                style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.7 }}
              >
                AWAITING EVENTS · STREAM CONNECTED
              </div>
            )}
            {incidents.map((i, idx) => (
              <IncidentRow key={`${i.time}-${idx}`} {...i} delay={0.05 * Math.min(idx, 5)} />
            ))}
          </div>
        </Card>
      </section>

      <section className="col-span-5">
        <Card className="p-5">
          <div
            className="text-[11px] tracking-[0.3em] mb-4 flex items-center gap-2"
            style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
          >
            <Radio size={12} /> NODES · {cameras.length} ACTIVE
          </div>
          <div className="space-y-2">
            {cameras.length === 0 && (
              <div
                className="px-3 py-2 text-[10px] tracking-[0.2em]"
                style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.7 }}
              >
                NO CAMERAS REGISTERED
              </div>
            )}
            {cameras.map((c, i) => (
              <NodeRow
                key={c.node_id}
                id={c.node_id.toUpperCase()}
                loc={c.name.toUpperCase()}
                status={statusFromEntry(c.status)}
                delay={0.05 * i}
              />
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}

function TierLegend() {
  const tiers: { tier: Tier; label: string; desc: string; bg: string }[] = [
    { tier: "ambient", label: "Ambient", desc: "logged, no notice", bg: "#cfc4a6" },
    { tier: "notice", label: "Notice", desc: "soft awareness", bg: C.gold },
    { tier: "alert", label: "Alert", desc: "call + clip", bg: C.orange },
    { tier: "emergency", label: "Emergency", desc: "full escalation", bg: C.red },
  ];
  return (
    <div className="mt-12 grid grid-cols-4 gap-3 max-w-[600px]">
      {tiers.map((t, i) => (
        <motion.div
          key={t.tier}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 + i * 0.1 }}
          className="px-3 py-3 rounded-lg"
          style={{
            background: t.bg,
            border: `3px solid ${C.ink}`,
            boxShadow: `0 4px 0 ${C.ink}`,
          }}
        >
          <div
            className="text-[10px] tracking-[0.2em] mb-1"
            style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
          >
            {t.label.toUpperCase()}
          </div>
          <div
            className="text-[10px]"
            style={{ fontFamily: "DM Mono, monospace", color: C.ink, opacity: 0.7 }}
          >
            {t.desc}
          </div>
        </motion.div>
      ))}
    </div>
  );
}

function LiveView() {
  const cameras = useCameras();
  // Vision engine writes its annotated frame (boxes + confidences) here on
  // every loop. Same exact image the engine's OpenCV window shows, served
  // by the action_router's static mount.
  const enginePreview = `${BACKEND_URL}/media/live/preview.jpg`;
  return (
    <div>
      <SectionHeader title="Live View" sub="Vision engine preview · boxes + confidence overlays" />
      <div className="mt-8">
        {cameras.length === 0 ? (
          // No LAN cams registered → render the engine preview running on
          // this Mac. Boxes, classes, confidences are baked into the JPEG
          // by the engine, so the web shows exactly what the overlay sees.
          <div className="grid grid-cols-1 gap-6">
            <CameraTile
              name="THIS LAPTOP · ENGINE PREVIEW"
              status="live"
              previewUrl={enginePreview}
              delay={0}
              large
            />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-6">
            {cameras.map((c, i) => (
              <CameraTile
                key={c.node_id}
                name={`${c.node_id.toUpperCase()} · ${c.name.toUpperCase()}`}
                status={statusFromEntry(c.status)}
                streamUrl={c.stream_url}
                delay={0.05 * i}
                large
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Timeline() {
  const incidents = useIncidentStream();
  return (
    <div>
      <SectionHeader title="Timeline" sub="Filter by tier · the last calm minute is what matters" />
      <Card className="mt-6 overflow-hidden">
        {incidents.length === 0 && (
          <div
            className="px-5 py-6 text-[11px] tracking-[0.2em]"
            style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.7 }}
          >
            AWAITING EVENTS · STREAM CONNECTED
          </div>
        )}
        {incidents.map((i, idx) => (
          <IncidentRow key={`${i.time}-${idx}`} {...i} delay={0.04 * Math.min(idx, 5)} />
        ))}
      </Card>
    </div>
  );
}

function AskView() {
  const [q, setQ] = useState("");
  const [a, setA] = useState<string | null>(null);
  const [thinking, setThinking] = useState(false);
  const submit = () => {
    if (!q.trim()) return;
    setThinking(true);
    setA(null);
    setTimeout(() => {
      setThinking(false);
      setA(
        "Between 22:00 and 06:00, the only Alert-tier event was a package removal at 12:08 (NODE-01). Three Ambient events (yard, back, street) were logged but suppressed. No Emergency-tier escalations in the last 24h."
      );
    }, 1400);
  };
  return (
    <div className="max-w-[820px] mx-auto pt-4">
      <SectionHeader title="Ask" sub="Natural-language query over the event log" />
      <div
        className="mt-8 flex items-center gap-3 px-5 py-3 rounded-full"
        style={{
          background: C.cream,
          border: `4px solid ${C.ink}`,
          boxShadow: `0 4px 0 ${C.ink}`,
        }}
      >
        <MessageSquareText size={16} style={{ color: C.deep }} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="What happened overnight?"
          className="flex-1 bg-transparent outline-none text-[14px]"
          style={{ color: C.ink }}
        />
        <button
          onClick={submit}
          className="px-4 py-1.5 rounded-full text-[11px] tracking-[0.2em]"
          style={{
            fontFamily: "DM Mono, monospace",
            background: C.red,
            color: C.cream,
            border: `3px solid ${C.ink}`,
          }}
        >
          ASK
        </button>
      </div>
      <div className="mt-8 min-h-[120px]">
        {thinking && (
          <div
            className="flex items-center gap-2 text-[12px]"
            style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
          >
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="w-2 h-2 rounded-full"
                style={{ background: C.red }}
                animate={{ opacity: [0.2, 1, 0.2] }}
                transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
              />
            ))}
            scanning event log…
          </div>
        )}
        {a && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <Card className="p-5">
              <div
                className="text-[14px] leading-[1.8] tracking-[0.05em]"
                style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
              >
                {a}
              </div>
            </Card>
          </motion.div>
        )}
      </div>
    </div>
  );
}

function EdgeView() {
  return (
    <div>
      <SectionHeader title="Edge Inference" sub="Per-node model + frame budget · all on-device" />
      <div className="grid grid-cols-3 gap-4 mt-6">
        {["NODE-01", "NODE-02", "NODE-04", "NODE-05", "NODE-07", "PHONE-A"].map((n, i) => (
          <motion.div
            key={n}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.07 }}
          >
            <Card className="p-5">
              <div className="flex items-center justify-between">
                <span
                  className="text-[11px] tracking-[0.2em]"
                  style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
                >
                  {n}
                </span>
                <Cpu size={14} style={{ color: C.red }} />
              </div>
              <div
                className="mt-4 text-[11px]"
                style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
              >
                yolo-third-eye-s · 14 fps
              </div>
              <div
                className="mt-3 h-2 overflow-hidden rounded-full"
                style={{ background: "#e6d2a8", border: `2px solid ${C.ink}` }}
              >
                <motion.div
                  className="h-full"
                  style={{ background: C.red }}
                  initial={{ width: 0 }}
                  animate={{ width: `${40 + Math.random() * 50}%` }}
                  transition={{ duration: 1.2 }}
                />
              </div>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function SettingsView() {
  return (
    <div>
      <SectionHeader title="Settings" sub="Routing · contacts · LAN cameras" />
      <div className="mt-6">
        <LANScanPanel />
      </div>
      <div className="mt-6 grid grid-cols-12 gap-10 items-start">
        <div className="col-span-7 space-y-3">
        {[
          ["Notify on Notice", false],
          ["Outbound call on Alert", true],
          ["Neighbor IVR on Emergency", true],
          ["Keep frames local-only", true],
        ].map(([label, on], i) => (
          <Card key={i} className="flex items-center justify-between px-5 py-4">
            <span
              className="text-[14px] tracking-[0.15em]"
              style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
            >
              {(label as string).toUpperCase()}
            </span>
            <motion.button
              className="w-14 h-7 rounded-full p-0.5"
              style={{
                background: on ? C.red : "#cfc4a6",
                border: `3px solid ${C.ink}`,
              }}
              whileTap={{ scale: 0.95 }}
            >
              <motion.div
                className="w-5 h-5 rounded-full"
                style={{ background: C.cream, border: `2px solid ${C.ink}` }}
                animate={{ x: on ? 24 : 0 }}
              />
            </motion.button>
          </Card>
        ))}
        </div>
        <div className="col-span-5 flex flex-col items-center justify-start pt-2 gap-3">
          <WaterTower size={200} />
          <div className="text-center">
            <div
              style={{
                fontFamily: "Playfair Display, serif",
                fontWeight: 900,
                fontSize: "22px",
                lineHeight: 1.05,
                color: C.ink,
              }}
            >
              Built at UC <span style={{ color: C.red, fontStyle: "italic" }}>Davis</span>
            </div>
            <div
              className="text-[10px] tracking-[0.3em] mt-1"
              style={{ fontFamily: "DM Mono, monospace", color: C.wine }}
            >
              AGGIES · 2026
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LANScanPanel() {
  const cameras = useCameras();
  const [discovered, setDiscovered] = useState<DiscoveredCamera[]>([]);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [manualName, setManualName] = useState("Front camera");
  const [manualUrl, setManualUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setScanning(true);
    setError(null);
    try {
      const list = await discoverCameras(4);
      setDiscovered(list);
      if (list.length === 0) {
        setError("Nothing advertising on the LAN. Add manually below.");
      }
    } finally {
      setScanning(false);
    }
  };

  const register = async (name: string, url: string) => {
    setBusy(url);
    setError(null);
    try {
      const entry = await addCamera(name, url);
      if (!entry) {
        setError("Couldn't register that stream. Make sure it's on the LAN (HTTP/RTSP, private IP).");
      } else if (manualUrl === url) {
        setManualUrl("");
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="px-5 py-5 rounded-[14px]"
      style={{ background: C.cream, border: `4px solid ${C.ink}`, boxShadow: `0 6px 0 ${C.ink}` }}
    >
      <div className="flex items-center justify-between">
        <div
          className="text-[11px] tracking-[0.3em]"
          style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
        >
          LAN CAMERAS · {cameras.length} REGISTERED
        </div>
        <motion.button
          whileTap={{ scale: 0.96 }}
          disabled={scanning}
          onClick={scan}
          className="px-4 py-1.5 rounded-full text-[11px] tracking-[0.18em] disabled:opacity-50"
          style={{
            fontFamily: "DM Mono, monospace",
            background: scanning ? C.cream : C.gold,
            color: C.ink,
            border: `3px solid ${C.ink}`,
          }}
        >
          {scanning ? "SCANNING…" : "SCAN LAN"}
        </motion.button>
      </div>

      {discovered.length > 0 && (
        <div className="mt-4 space-y-2">
          {discovered.map((d) => {
            const already = cameras.some((c) => c.stream_url === d.stream_url);
            return (
              <div
                key={d.stream_url}
                className="flex items-center justify-between px-3 py-2 rounded-lg"
                style={{ background: C.cream, border: `3px solid ${C.ink}` }}
              >
                <div>
                  <div
                    className="text-[12px] tracking-[0.18em]"
                    style={{ fontFamily: "DM Mono, monospace", color: C.ink }}
                  >
                    {d.name.toUpperCase()}
                  </div>
                  <div
                    className="text-[10px]"
                    style={{ fontFamily: "DM Mono, monospace", color: C.deep, opacity: 0.7 }}
                  >
                    {d.host}:{d.port} · {d.stream_url}
                  </div>
                </div>
                <button
                  disabled={busy !== null || already}
                  onClick={() => register(d.name, d.stream_url)}
                  className="px-3 py-1 rounded-full text-[10px] tracking-[0.18em] disabled:opacity-50"
                  style={{
                    fontFamily: "DM Mono, monospace",
                    background: already ? "#cfc4a6" : C.red,
                    color: already ? C.ink : C.cream,
                    border: `2px solid ${C.ink}`,
                  }}
                >
                  {already ? "ADDED" : busy === d.stream_url ? "ADDING…" : "ADD"}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 grid grid-cols-[1fr_2fr_auto] gap-2">
        <input
          value={manualName}
          onChange={(e) => setManualName(e.target.value)}
          placeholder="Camera name"
          className="px-3 py-2 outline-none text-[12px]"
          style={{
            background: C.cream,
            color: C.ink,
            border: `3px solid ${C.ink}`,
            borderRadius: 10,
          }}
        />
        <input
          value={manualUrl}
          onChange={(e) => setManualUrl(e.target.value)}
          placeholder="http://192.168.1.42:8765/stream"
          className="px-3 py-2 outline-none text-[12px]"
          style={{
            background: C.cream,
            color: C.ink,
            border: `3px solid ${C.ink}`,
            borderRadius: 10,
            fontFamily: "DM Mono, monospace",
          }}
        />
        <button
          disabled={busy !== null || !manualUrl}
          onClick={() => register(manualName || "Camera", manualUrl)}
          className="px-4 py-2 rounded-full text-[11px] tracking-[0.18em] disabled:opacity-50"
          style={{
            fontFamily: "DM Mono, monospace",
            background: C.red,
            color: C.cream,
            border: `3px solid ${C.ink}`,
          }}
        >
          ADD
        </button>
      </div>

      {error && (
        <div
          className="mt-3 px-3 py-2 text-[10px] tracking-[0.18em]"
          style={{
            fontFamily: "DM Mono, monospace",
            color: C.red,
            background: "rgba(200,34,45,0.08)",
            border: `2px solid ${C.red}`,
            borderRadius: 8,
          }}
        >
          {error.toUpperCase()}
        </div>
      )}
    </div>
  );
}

function SectionHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h2
        style={{
          fontFamily: "Playfair Display, serif",
          fontWeight: 700,
          fontSize: "60px",
          lineHeight: 1.05,
          color: C.ink,
        }}
      >
        <EyeText>{title}</EyeText>
      </h2>
      <div
        className="mt-2 text-[11px] tracking-[0.25em]"
        style={{ fontFamily: "DM Mono, monospace", color: C.deep }}
      >
        {sub.toUpperCase()}
      </div>
    </div>
  );
}

function Footer() {
  return (
    <footer
      className="mt-16 pt-6 flex items-center justify-between text-[10px] tracking-[0.3em]"
      style={{
        fontFamily: "DM Mono, monospace",
        color: C.deep,
        borderTop: `3px solid ${C.ink}`,
      }}
    >
      <span>THIRD EYE · LOCAL-FIRST</span>
      <span>FRAMES NEVER LEAVE THE NODE</span>
      <span>BUILD 0.4.2 · {new Date().getFullYear()}</span>
    </footer>
  );
}
