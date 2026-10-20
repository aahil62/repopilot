"use client";

import { Fragment } from "react";

import type { Citation } from "@/lib/types";

/** Renders an answer; only citation numbers that were actually supplied become clickable chips. */
export function Answer({ text, citations, active, onCite }: { text: string; citations: Citation[]; active: number | null; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d{1,2}\])/g);
  const valid = new Set(citations.map((c) => c.n));
  return (
    <p className="answer">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d{1,2})\]$/);
        if (m && valid.has(Number(m[1]))) {
          const n = Number(m[1]);
          return <button key={i} className="cite-chip" aria-pressed={active === n} onClick={() => onCite(n)} aria-label={`Show source ${n}`}>{n}</button>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </p>
  );
}
