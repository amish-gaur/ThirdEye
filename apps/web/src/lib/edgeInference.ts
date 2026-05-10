"use client";

// Loads CLIP via @huggingface/transformers, fully in the browser.
// WebGPU when available; WASM fallback handled by the runtime.

import type { Pipeline } from "@huggingface/transformers";

type CLIPState = {
  status: "idle" | "loading" | "ready" | "error";
  error?: string;
  modelId: string;
  device: "webgpu" | "wasm" | "unknown";
  loadedAt?: number;
  inferenceCount: number;
  totalMs: number;
};

let state: CLIPState = {
  status: "idle",
  modelId: "Xenova/clip-vit-base-patch16",
  device: "unknown",
  inferenceCount: 0,
  totalMs: 0,
};

const listeners = new Set<(s: CLIPState) => void>();

let textPipe: Pipeline | null = null;

function emit() {
  for (const l of listeners) l(state);
}

export function subscribe(fn: (s: CLIPState) => void): () => void {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

export function getEdgeState(): CLIPState {
  return state;
}

export async function ensureLoaded(): Promise<void> {
  if (state.status === "ready" || state.status === "loading") return;
  state = { ...state, status: "loading" };
  emit();
  try {
    const tr = await import("@huggingface/transformers");
    // @ts-ignore — runtime has env
    if (tr.env) tr.env.allowLocalModels = false;

    const hasWebGPU = typeof navigator !== "undefined" && "gpu" in navigator;
    const device = hasWebGPU ? "webgpu" : "wasm";

    const pipe = await tr.pipeline(
      "feature-extraction",
      state.modelId,
      // @ts-ignore — device is a runtime option
      { device }
    );
    textPipe = pipe as unknown as Pipeline;
    state = {
      ...state,
      status: "ready",
      device: device as CLIPState["device"],
      loadedAt: Date.now(),
    };
    emit();
  } catch (err) {
    state = {
      ...state,
      status: "error",
      error: err instanceof Error ? err.message : String(err),
    };
    emit();
  }
}

export async function embedText(text: string): Promise<Float32Array> {
  await ensureLoaded();
  if (!textPipe) throw new Error("model not ready");
  const start = performance.now();
  // @ts-ignore — runtime call signature
  const out = await textPipe(text, { pooling: "mean", normalize: true });
  const arr = (out as { data: Float32Array }).data;
  const dt = performance.now() - start;
  state = {
    ...state,
    inferenceCount: state.inferenceCount + 1,
    totalMs: state.totalMs + dt,
  };
  emit();
  return arr instanceof Float32Array ? arr : new Float32Array(arr);
}
