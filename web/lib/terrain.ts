/** The codebase as terrain: elevation is risk learned from history (past fixes, dependents). */
import type { BlastReport } from "@/lib/types";

export interface Peak { x: number; y: number; h: number; r: number; label: string; sub: string }

// Peaks sit at the edges so they frame the hero copy instead of running under it.
// The lower two stay above the review window (its top is ~53% down the hero) so their labels aren't covered.
const SLOTS: [number, number][] = [[0.11, 0.24], [0.89, 0.21], [0.86, 0.46], [0.12, 0.48]];
const HEIGHTS = [1, 0.85, 0.7, 0.55];
const RADII = [0.17, 0.15, 0.13, 0.13];

function risk(r: BlastReport): number {
  return r.past_fixes.length * 3 + r.dependents.length;
}

function labelsFor(paths: string[]): string[] {
  const base = (p: string) => p.split("/").pop() ?? p;
  return paths.map((p) => {
    const clash = paths.filter((q) => base(q) === base(p)).length > 1;
    return clash ? p.split("/").slice(-2).join("/") : base(p);
  });
}

export function peaksFromBlast(blast: Record<string, BlastReport>): Peak[] {
  const top = Object.entries(blast).sort((a, b) => risk(b[1]) - risk(a[1])).slice(0, SLOTS.length);
  const labels = labelsFor(top.map(([path]) => path));
  return top.map(([, r], i) => ({
    x: SLOTS[i][0], y: SLOTS[i][1], h: HEIGHTS[i], r: RADII[i], label: labels[i],
    sub: `${r.past_fixes.length} fixes · ${r.dependents.length} dependents`,
  }));
}

export function heightAt(x: number, y: number, t: number, peaks: Peak[]): number {
  let z = 0;
  for (const p of peaks) {
    const dx = (x - p.x) / p.r, dy = (y - p.y) / (p.r * 0.8);
    z += p.h * Math.exp(-(dx * dx + dy * dy));
  }
  return z + 0.06 * Math.sin(x * 11 + t * 0.25) * Math.cos(y * 9 - t * 0.2) + 0.04 * Math.sin((x + y) * 17 + t * 0.3);
}

type Pt = [number, number];
export type Segment = [number, number, number, number];

/** Marching squares: line segments where the height field crosses `level`. */
export function contourSegments(grid: number[][], level: number, sx: number, sy: number): Segment[] {
  const out: Segment[] = [];
  for (let j = 0; j < grid.length - 1; j++) {
    for (let i = 0; i < grid[j].length - 1; i++) {
      const a = grid[j][i], b = grid[j][i + 1], c = grid[j + 1][i + 1], d = grid[j + 1][i];
      const idx = (+(a > level)) | (+(b > level) << 1) | (+(c > level) << 2) | (+(d > level) << 3);
      if (idx === 0 || idx === 15) continue;
      const x = i * sx, y = j * sy, f = (p: number, q: number) => (level - p) / (q - p);
      const top: Pt = [x + sx * f(a, b), y], right: Pt = [x + sx, y + sy * f(b, c)];
      const bottom: Pt = [x + sx * f(d, c), y + sy], left: Pt = [x, y + sy * f(a, d)];
      const pairs: Record<number, Pt[]> = {
        1: [left, top], 2: [top, right], 3: [left, right], 4: [right, bottom], 5: [left, top, right, bottom],
        6: [top, bottom], 7: [left, bottom], 8: [left, bottom], 9: [top, bottom], 10: [top, right, left, bottom],
        11: [right, bottom], 12: [left, right], 13: [top, right], 14: [left, top],
      };
      const pts = pairs[idx];
      for (let k = 0; k < pts.length; k += 2) out.push([pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]]);
    }
  }
  return out;
}
