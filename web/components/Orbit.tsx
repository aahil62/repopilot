"use client";

import { useEffect, useRef, useState } from "react";

import type { BlastReport } from "@/lib/types";

const SIZE = 440;
const C = SIZE / 2;

interface Node { path: string; kind: "dependent" | "cochange"; x: number; y: number; r: number; detail: string; test: boolean; imports: boolean }

function basename(p: string) {
  return p.split("/").pop() ?? p;
}

const TEST_RE = /(^|\/)(test_[^/]+|[^/]+_test\.\w+|[^/]+\.(test|spec)\.\w+)$|(^|\/)tests?\//;

export function layout(report: BlastReport): Node[] {
  const nodes: Node[] = [];
  const co = report.cochanged.slice(0, 16);
  const coPaths = new Set(co.map((c) => c.path));
  const depPaths = new Set(report.dependents.map((d) => d.path));
  // A file that both imports the target and changes with it is drawn once, on the co-change ring.
  const deps = report.dependents.filter((d) => !coPaths.has(d.path)).slice(0, 18);
  deps.forEach((d, i) => {
    const a = (i / Math.max(deps.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const radius = d.depth === 1 ? 82 : 118;
    nodes.push({ path: d.path, kind: "dependent", x: C + Math.cos(a) * radius, y: C + Math.sin(a) * radius, r: 5,
      detail: d.depth === 1 ? "imports this file" : "imports a file that imports this", test: TEST_RE.test(d.path), imports: true });
  });
  co.forEach((c, i) => {
    const a = (i / Math.max(co.length, 1)) * Math.PI * 2 - Math.PI / 2 + Math.PI / Math.max(co.length, 1);
    const radius = 140 + (1 - c.confidence) * 66;
    nodes.push({ path: c.path, kind: "cochange", x: C + Math.cos(a) * radius, y: C + Math.sin(a) * radius,
      r: 4 + c.confidence * 9,
      detail: `changes together ${Math.round(c.confidence * 100)}% of the time (${c.support} commits)${depPaths.has(c.path) ? " and imports it" : ""}`,
      test: TEST_RE.test(c.path), imports: depPaths.has(c.path) });
  });
  return nodes;
}

export function Orbit({ report, animate = false, onSelect }: { report: BlastReport; animate?: boolean; onSelect?: (path: string) => void }) {
  const nodes = layout(report);
  const [active, setActive] = useState<Node | null>(null);
  const [paused, setPaused] = useState(false);
  const [angle, setAngle] = useState(0);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (!animate || paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let last = performance.now();
    const tick = (now: number) => {
      setAngle((a) => (a + (now - last) * 0.004) % 360);
      last = now;
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => { if (frame.current) cancelAnimationFrame(frame.current); };
  }, [animate, paused]);

  const target = report.targets[0] ?? "";
  const label = report.targets.length > 1 ? `the ${report.targets.length} changed files` : target;
  const fixes = report.past_fixes.length;

  return (
    <figure className="orbit" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width="100%" role="group" aria-label={`Blast radius of ${label}`}>
        <circle cx={C} cy={C} r={82} fill="none" stroke="var(--line)" />
        <circle cx={C} cy={C} r={118} fill="none" stroke="var(--line)" strokeDasharray="2 5" />
        <circle cx={C} cy={C} r={206} fill="none" stroke="var(--line)" />
        <g transform={`rotate(${angle} ${C} ${C})`}>
          {nodes.map((n) => (
            <line key={`l-${n.path}`} x1={C} y1={C} x2={n.x} y2={n.y}
              stroke={n.kind === "cochange" ? "var(--line-strong)" : "var(--line)"} strokeWidth={active?.path === n.path ? 1.6 : 0.8} />
          ))}
          {nodes.map((n) => (
            <g key={n.path} tabIndex={0} role="button" aria-label={`${n.path}: ${n.detail}`}
              onMouseEnter={() => setActive(n)} onFocus={() => setActive(n)} onMouseLeave={() => setActive(null)} onBlur={() => setActive(null)}
              onClick={() => onSelect?.(n.path)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(n.path); } }}
              style={{ cursor: onSelect ? "pointer" : "default", outline: "none" }}>
              <circle cx={n.x} cy={n.y} r={n.r + 6} fill="transparent" />
              <circle cx={n.x} cy={n.y} r={n.r}
                fill={n.test ? "var(--add)" : n.kind === "cochange" ? "var(--ink)" : "var(--surface)"}
                stroke={n.imports ? (n.kind === "cochange" ? "var(--mark)" : "var(--ink)") : "none"} strokeWidth={n.kind === "cochange" ? 2.4 : 1.4} />
              {active?.path === n.path && <circle cx={n.x} cy={n.y} r={n.r + 4} fill="none" stroke="var(--focus)" strokeWidth={2} />}
            </g>
          ))}
        </g>
        <g>
          <circle cx={C} cy={C} r={30} fill="var(--mark)" />
          {fixes > 0 && <circle cx={C} cy={C} r={30} fill="none" stroke="var(--accent)" strokeWidth={2.5} strokeDasharray={`${Math.min(fixes, 10) * 6} 400`} />}
          <text x={C} y={C + 4} textAnchor="middle" fontFamily="var(--mono)" fontSize="11" fontWeight={600} fill="var(--ink)">
            {report.targets.length > 1 ? `${report.targets.length} files` : basename(target).slice(0, 12)}
          </text>
        </g>
      </svg>
      <figcaption className="orbit-caption" aria-live="polite">
        {active ? (<><strong className="mono">{active.path}</strong> {active.detail}</>) : (
          <>Inner rings: files that import it. Outer ring: files that change with it — closer and larger means more often.
            {fixes > 0 && <> The amber arc marks {fixes}{fixes === 10 ? "+" : ""} bug fix{fixes > 1 ? "es" : ""} in its history.</>}</>
        )}
      </figcaption>
      {animate && (
        <button className="btn secondary small orbit-toggle" onClick={() => setPaused(!paused)} aria-pressed={paused}>
          {paused ? "Resume rotation" : "Pause rotation"}
        </button>
      )}
    </figure>
  );
}
