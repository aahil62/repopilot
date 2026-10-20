"use client";

import { useEffect, useRef } from "react";

import { contourSegments, heightAt, type Peak } from "@/lib/terrain";

const LEVELS = 16;
const HOT = 0.62; // contours above this elevation glow in the accent colour

function rgb(hex: string): string {
  const h = hex.trim().replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

/** Live contour map of the repository behind the hero. Decorative: aria-hidden, static under reduced motion. */
export function Terrain({ peaks }: { peaks: Peak[] }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const css = getComputedStyle(document.documentElement);
    const accent = rgb(css.getPropertyValue("--accent") || "#e6904f");
    const ink = rgb(css.getPropertyValue("--ink") || "#efe9df");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, frame = 0, last = 0;

    const size = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const n = 110, m = Math.max(1, Math.round((n * h) / Math.max(w, 1)));
      const grid = Array.from({ length: m + 1 }, (_, j) => Array.from({ length: n + 1 }, (_, i) => heightAt(i / n, j / m, t, peaks)));
      for (let l = 1; l < LEVELS; l++) {
        const level = (l / LEVELS) * 1.05;
        const hot = level > HOT;
        ctx.strokeStyle = hot ? `rgba(${accent}, ${0.22 + 0.55 * (level - HOT)})` : `rgba(${ink}, ${0.07 + 0.09 * level})`;
        ctx.lineWidth = hot ? 1.1 : 0.8;
        ctx.beginPath();
        for (const [x1, y1, x2, y2] of contourSegments(grid, level, w / n, h / m)) { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
        ctx.stroke();
      }
      if (w < 640) return; // labels would crowd the copy on small screens
      ctx.font = "11px 'Fragment Mono', monospace";
      for (const p of peaks) {
        const x = p.x * w, y = p.y * h, left = p.x > 0.6, ox = left ? -8 : 8;
        ctx.textAlign = left ? "right" : "left";
        ctx.fillStyle = `rgba(${accent}, 0.9)`; ctx.beginPath(); ctx.arc(x, y, 2.6, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgba(${ink}, 0.6)`; ctx.fillText(`▲ ${p.label}`, x + ox, y - 2);
        ctx.fillStyle = `rgba(${ink}, 0.35)`; ctx.fillText(p.sub, x + ox, y + 12);
      }
    };

    const loop = (ts: number) => {
      if (ts - last > 60) { draw(ts / 1000); last = ts; }
      frame = requestAnimationFrame(loop);
    };

    size();
    draw(0);
    const onResize = () => { size(); draw(last / 1000); };
    window.addEventListener("resize", onResize);
    if (!reduce) frame = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", onResize); };
  }, [peaks]);

  return <canvas ref={ref} className="terrain" aria-hidden="true" />;
}
