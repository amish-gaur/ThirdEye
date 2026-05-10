"use client";
import { useEffect, useState } from "react";
import { getContacts, getNodes } from "@/lib/api";
import type { ContactRule, NodeSummary } from "@safewatch/api-types";

export default function SettingsPage() {
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [contacts, setContacts] = useState<ContactRule[]>([]);

  useEffect(() => {
    getNodes().then(setNodes);
    getContacts().then(setContacts);
  }, []);

  return (
    <>
      <header className="mb-8">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.24em] text-maroon-200/80">
          Settings
        </div>
        <h1 className="mt-2 font-serif text-[44px] leading-tight text-cream-50">
          Tune the system.
        </h1>
      </header>

      <div className="grid max-w-[860px] gap-4">
        <Section title="Cameras">
          {nodes.map((n) => (
            <Row
              key={n.node_id}
              left={
                <>
                  <strong className="text-cream-50">{n.label}</strong>
                  <span className="ml-2 font-mono text-[12px] text-cream-50/45">
                    {n.node_id}
                  </span>
                </>
              }
              right={
                <span
                  className={
                    "font-mono text-[11px] uppercase tracking-[0.18em] " +
                    (n.online ? "text-cream-50/85" : "text-cream-50/40")
                  }
                >
                  {n.online ? "● online" : "○ offline"}
                </span>
              }
            />
          ))}
          <button className="mt-2 self-start rounded-full border border-maroon-300/30 px-4 py-1.5 text-[12.5px] text-cream-50 hover:bg-maroon-300/10">
            Add a camera
          </button>
        </Section>

        <Section title="Severity rules">
          <p className="text-[13.5px] text-cream-50/65">
            Mobile rings on Tier 3+, sends SMS on Tier 2+, silently logs Tier 1.
            Critical events fan out to all contacts simultaneously.
          </p>
          {[1, 2, 3, 4].map((t) => (
            <Row
              key={t}
              left={<strong className="text-cream-50">Tier {t}</strong>}
              right={
                <Select
                  defaultValue={
                    t === 1 ? "log" : t === 2 ? "sms" : t === 3 ? "ring" : "fanout"
                  }
                >
                  <option value="log">Log only</option>
                  <option value="sms">Send SMS</option>
                  <option value="ring">Ring me</option>
                  <option value="fanout">Fan out</option>
                </Select>
              }
            />
          ))}
        </Section>

        <Section title="Contacts">
          {contacts.map((c) => (
            <Row
              key={c.id}
              left={
                <>
                  <strong className="text-cream-50">{c.name}</strong>
                  <span className="ml-2 font-mono text-[12px] text-cream-50/45">
                    {c.destination}
                  </span>
                </>
              }
              right={
                <span className="rounded-md bg-maroon-200/10 px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.16em] text-cream-50/75">
                  {c.channel} · ≥ Tier {c.min_tier}
                </span>
              }
            />
          ))}
        </Section>

        <Section title="Retention">
          <Row
            left={<strong className="text-cream-50">Clip storage</strong>}
            right={
              <Select defaultValue="30">
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
              </Select>
            }
          />
          <Row
            left={<strong className="text-cream-50">Local-only mode</strong>}
            right={
              <label className="flex items-center gap-2 text-[13px] text-cream-50/85">
                <input type="checkbox" defaultChecked className="accent-cream-50" />
                Don't upload clips
              </label>
            }
          />
        </Section>

        <Section title="Recording jurisdiction">
          <p className="text-[13.5px] text-cream-50/65">
            Some places require notice that you're recording. Set your jurisdiction so
            audio capture and signage hints follow the right rules.
          </p>
          <Row
            left={<strong className="text-cream-50">Jurisdiction</strong>}
            right={
              <Select defaultValue="us-ca">
                <option value="us-ca">California (US, two-party consent)</option>
                <option value="us-tx">Texas (US, one-party consent)</option>
                <option value="eu">EU (GDPR)</option>
                <option value="uk">UK</option>
              </Select>
            }
          />
        </Section>
      </div>
    </>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card-glass ring-glow rounded-2xl p-6">
      <h2 className="mb-3 font-serif text-[22px] text-cream-50">{title}</h2>
      <div className="grid gap-2">{children}</div>
    </section>
  );
}

function Row({
  left,
  right,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-maroon-300/10 py-2.5 last:border-0">
      <div className="text-[14px] text-cream-50/85">{left}</div>
      <div>{right}</div>
    </div>
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="rounded-md border border-maroon-300/20 bg-maroon-950/60 px-3 py-1.5 font-mono text-[12px] text-cream-50 focus:border-maroon-200/50 focus:outline-none"
    />
  );
}
