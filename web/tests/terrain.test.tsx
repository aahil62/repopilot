import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Terrain } from "@/components/Terrain";
import { contourSegments, heightAt, peaksFromBlast } from "@/lib/terrain";
import type { BlastReport } from "@/lib/types";

function report(fixes: number, dependents: number): BlastReport {
  return {
    targets: [], cochanged: [], tests: [], owners: [], risk: "low", risk_reasons: [],
    past_fixes: Array.from({ length: fixes }, (_, i) => ({ sha: `s${i}`, date: "2024-01-01", subject: "fix", author: "a" })),
    dependents: Array.from({ length: dependents }, (_, i) => ({ path: `d${i}.py`, depth: 1 })),
  };
}

const blast: Record<string, BlastReport> = {
  "src/flask/app.py": report(12, 60),
  "src/flask/ctx.py": report(2, 7),
  "src/flask/sansio/app.py": report(3, 20),
  "src/flask/helpers.py": report(3, 4),
  "src/flask/cli.py": report(0, 1),
};

describe("terrain", () => {
  it("turns the riskiest files into four labelled peaks, riskiest first", () => {
    const peaks = peaksFromBlast(blast);
    expect(peaks).toHaveLength(4);
    expect(peaks[0].sub).toBe("12 fixes · 60 dependents");
    expect(peaks[0].h).toBeGreaterThan(peaks[3].h);
    expect(peaks.map((p) => p.label)).not.toContain("cli.py");
  });

  it("disambiguates files that share a basename", () => {
    const labels = peaksFromBlast(blast).map((p) => p.label);
    expect(labels).toContain("flask/app.py");
    expect(labels).toContain("sansio/app.py");
  });

  it("is highest at a peak's centre", () => {
    const [p] = peaksFromBlast(blast);
    expect(heightAt(p.x, p.y, 0, [p])).toBeGreaterThan(heightAt(p.x + 0.3, p.y, 0, [p]));
  });

  it("traces one closed contour around a single high point", () => {
    const grid = [
      [0, 0, 0],
      [0, 1, 0],
      [0, 0, 0],
    ];
    expect(contourSegments(grid, 0.5, 10, 10)).toHaveLength(4);
  });

  it("draws once and never animates under reduced motion", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    // jsdom has no canvas: a no-op 2D context lets the component run its real draw path
    const noop = () => {};
    const ctx = { setTransform: noop, clearRect: noop, beginPath: noop, moveTo: noop, lineTo: noop, stroke: noop, arc: noop, fill: noop, fillText: noop } as unknown as CanvasRenderingContext2D;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx);
    const raf = vi.fn();
    vi.stubGlobal("requestAnimationFrame", raf);
    const { container } = render(<Terrain peaks={peaksFromBlast(blast)} />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(raf).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
});
