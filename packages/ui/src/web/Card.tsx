import * as React from "react";
import { color, radius, shadow } from "../tokens";

export function Card({
  children,
  elevated = false,
  style,
}: {
  children: React.ReactNode;
  elevated?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: elevated ? color.cream[50] : color.cream[200],
        border: `1px solid ${color.cream[200]}`,
        borderRadius: radius.lg,
        boxShadow: elevated ? shadow.card : undefined,
        color: color.ink,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
