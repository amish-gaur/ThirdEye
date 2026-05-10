"use client";
import { useRef, useState } from "react";
import { cn } from "@/lib/utils";

export function Spotlight({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: -1000, y: -1000 });

  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        const r = ref.current?.getBoundingClientRect();
        if (!r) return;
        setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
      }}
      onMouseLeave={() => setPos({ x: -1000, y: -1000 })}
      className={cn("relative overflow-hidden", className)}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-px transition-opacity duration-200"
        style={{
          background: `radial-gradient(420px circle at ${pos.x}px ${pos.y}px, rgba(229,180,187,0.16), transparent 55%)`,
        }}
      />
      {children}
    </div>
  );
}
