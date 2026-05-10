"use client";
import { cn } from "@/lib/utils";

export function ShimmerText({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("shimmer-text animate-shimmer", className)}>
      {children}
    </span>
  );
}
