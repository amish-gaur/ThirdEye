"use client";
import { cn } from "@/lib/utils";

export function BentoGrid({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 auto-rows-[10rem]",
        className
      )}
    >
      {children}
    </div>
  );
}

export function BentoCell({
  className,
  children,
  span,
}: {
  className?: string;
  children: React.ReactNode;
  span?: "1" | "2" | "3" | "4";
}) {
  const colSpan = {
    "1": "lg:col-span-1",
    "2": "lg:col-span-2",
    "3": "lg:col-span-3",
    "4": "lg:col-span-4",
  }[span ?? "1"];

  return (
    <div
      className={cn(
        "card-glass ring-glow rounded-2xl relative overflow-hidden",
        colSpan,
        className
      )}
    >
      {children}
    </div>
  );
}
