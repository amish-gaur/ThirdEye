"use client";
import { cn } from "@/lib/utils";

export function Aurora({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className
      )}
    >
      <div className="absolute -inset-[20%] bg-aurora-maroon blur-3xl opacity-90 animate-aurora-shift" />
      <div
        className="absolute inset-0 mix-blend-overlay opacity-[0.18] bg-film-grain"
        style={{ backgroundSize: "180px 180px" }}
      />
      <div className="absolute inset-0 grid-mask" />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-maroon-950" />
    </div>
  );
}
