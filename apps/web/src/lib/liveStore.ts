"use client";

/**
 * Shared client-side store for the real backend feed.
 *
 * Mirrors what `BackendStatus` / `CamerasStore` / `IncidentStream` do on
 * iOS: one health poll, one camera-registry poll, one SSE subscription —
 * shared across every page that mounts the provider. Pages read via the
 * hooks at the bottom so the SSE connection isn't reopened per route.
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { EventRecord } from "@safewatch/api-types";
import {
  type BackendHealth,
  type CameraEntry,
  type IncidentStreamMessage,
  type WarmupStatus,
  fetchCameras,
  fetchHealth,
  fetchWarmup,
  streamMessageToEvent,
  subscribeIncidents,
} from "./api";
import { USE_MOCKS } from "./config";

const HEALTH_POLL_MS = 2_500;
const CAMERA_POLL_MS = 5_000;
const WARMUP_POLL_MS = 2_000;
const MAX_INCIDENTS = 100;

export type BackendState = "connecting" | "live" | "offline";
export type StreamState = "connecting" | "open" | "error";

interface LiveStoreValue {
  backend: BackendState;
  health: BackendHealth | null;
  cameras: CameraEntry[];
  incidents: EventRecord[];
  streamState: StreamState;
  warmup: WarmupStatus | null;
  refreshCameras: () => Promise<void>;
}

const LiveContext = createContext<LiveStoreValue | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [backend, setBackend] = useState<BackendState>("connecting");
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [cameras, setCameras] = useState<CameraEntry[]>([]);
  const [incidents, setIncidents] = useState<EventRecord[]>([]);
  const [streamState, setStreamState] = useState<StreamState>("connecting");
  const [warmup, setWarmup] = useState<WarmupStatus | null>(null);

  // Keep the latest fetcher in a ref so the manual refresh button works
  // without re-running effects.
  const refreshCameras = useCallback(async () => {
    const list = await fetchCameras();
    setCameras(list);
  }, []);

  // Health poll — drives the "ready pillar" badge across pages.
  useEffect(() => {
    if (USE_MOCKS) {
      setBackend("live");
      fetchHealth().then(setHealth);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      const h = await fetchHealth();
      if (cancelled) return;
      if (h && h.status === "ok") {
        setBackend("live");
        setHealth(h);
      } else {
        setBackend("offline");
      }
    };
    tick();
    const id = window.setInterval(tick, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Camera registry poll — pillar count + node tiles.
  useEffect(() => {
    if (USE_MOCKS) return;
    let cancelled = false;
    const tick = async () => {
      const list = await fetchCameras();
      if (!cancelled) setCameras(list);
    };
    tick();
    const id = window.setInterval(tick, CAMERA_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Warmup poll — slows once we hit `ready` since the model only goes
  // cold on a vision-engine restart, not on its own.
  useEffect(() => {
    if (USE_MOCKS) {
      setWarmup({ state: "ready", elapsed_s: 0, running: 1, warming: 0, crashed: 0 });
      return;
    }
    let cancelled = false;
    let timeoutId: number | undefined;
    const tick = async () => {
      const w = await fetchWarmup();
      if (cancelled) return;
      setWarmup(w);
      const delay = w?.state === "ready" ? WARMUP_POLL_MS * 5 : WARMUP_POLL_MS;
      timeoutId = window.setTimeout(tick, delay);
    };
    tick();
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, []);

  // SSE incident stream. Browser EventSource auto-reconnects; we only
  // explicitly close when the provider unmounts.
  useEffect(() => {
    if (USE_MOCKS) {
      setStreamState("open");
      return;
    }
    const onMessage = (msg: IncidentStreamMessage) => {
      if (msg.result?.duplicate) return;
      const ev = streamMessageToEvent(msg);
      if (!ev) return;
      setIncidents((prev) => {
        // De-dupe by id so a server-side replay doesn't double-render.
        const without = prev.filter((p) => p.id !== ev.id);
        return [ev, ...without].slice(0, MAX_INCIDENTS);
      });
    };
    const onStatus = (s: "open" | "error") => setStreamState(s);
    const handle = subscribeIncidents(onMessage, onStatus);
    return () => {
      handle?.close();
    };
  }, []);

  const value = useMemo<LiveStoreValue>(
    () => ({
      backend,
      health,
      cameras,
      incidents,
      streamState,
      warmup,
      refreshCameras,
    }),
    [backend, health, cameras, incidents, streamState, warmup, refreshCameras]
  );

  return createElement(LiveContext.Provider, { value }, children);
}

export function useLiveStore(): LiveStoreValue {
  const ctx = useContext(LiveContext);
  if (!ctx) {
    // Tolerate hooks called outside the provider (e.g. server components);
    // return a static "connecting" snapshot so callers don't crash.
    return {
      backend: "connecting",
      health: null,
      cameras: [],
      incidents: [],
      streamState: "connecting",
      warmup: null,
      refreshCameras: async () => {},
    };
  }
  return ctx;
}

export function useWarmup() {
  const { warmup } = useLiveStore();
  return warmup;
}

export function useBackendStatus() {
  const { backend, health } = useLiveStore();
  return { backend, health };
}

export function useCameras() {
  const { cameras, refreshCameras } = useLiveStore();
  return { cameras, refreshCameras };
}

export function useIncidents() {
  const { incidents, streamState } = useLiveStore();
  return { incidents, streamState };
}
