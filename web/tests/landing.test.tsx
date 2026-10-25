import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BlastReport, FileView } from "@/lib/types";

const SUBLINE =
  "Every diff is checked against your repository's history: past bug fixes, files that change together, the tests that cover it. Runs on your machine, on open models, with no API keys.";

function file(path: string, behavior: number, mechanical: number): FileView {
  const hunks = [
    ...Array.from({ length: behavior }, () => ({ old_start: 1, new_start: 1, new_end: 2, label: "behavior" as const, reason: "logic", text: "-a\n+b" })),
    ...Array.from({ length: mechanical }, () => ({ old_start: 5, new_start: 5, new_end: 6, label: "mechanical" as const, reason: "formatting only (identical Python syntax tree)", text: " x" })),
  ];
  return { path, status: "modified", behavior_hunks: behavior, mechanical_hunks: mechanical, hunks };
}

const ctxBlast: BlastReport = {
  targets: ["src/flask/ctx.py"], cochanged: [], tests: [], owners: [], risk: "medium", risk_reasons: [],
  dependents: Array.from({ length: 7 }, (_, i) => ({ path: `d${i}.py`, depth: 1 })),
  past_fixes: [{ sha: "a", date: "2024-01-01", subject: "fix", author: "x" }, { sha: "b", date: "2024-01-02", subject: "fix", author: "y" }],
};

const DEMO: Record<string, unknown> = {
  hero: {
    repo: "pallets/flask", commit: "53c893b646252d610e877eb9385e9e250a1ae5e1", subject: "fix string concats left over by black",
    files: [file("src/flask/app.py", 0, 13), file("src/flask/ctx.py", 1, 0)], mechanical: 13, behavior: 1, blast: null,
  },
  blast: { "src/flask/ctx.py": ctxBlast, "src/flask/app.py": { ...ctxBlast, targets: ["src/flask/app.py"] } },
};

function serve(demo: Record<string, unknown> | null) {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!demo) throw new Error("offline");
    const name = url.split("/").pop()!.replace(".json", "");
    return { ok: name in demo, json: async () => demo[name] } as Response;
  }));
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("landing page", () => {
  it("leads with the agreed headline and subline", async () => {
    serve(DEMO);
    const { default: Landing } = await import("@/app/page");
    render(<Landing />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toContain("Code review");
    expect(h1.textContent).toContain("with a memory.");
    expect(screen.getByText(SUBLINE)).toBeInTheDocument();
  });

  it("links the two calls to action", async () => {
    serve(DEMO);
    const { default: Landing } = await import("@/app/page");
    render(<Landing />);
    expect(screen.getByRole("link", { name: /See it review Flask/ }).getAttribute("href")).toMatch(/^\/app\/review\/?$/);
    expect(screen.getByRole("link", { name: /Install locally/ })).toHaveAttribute("href", "#install");
  });

  it("fills the review window from the demo data", async () => {
    serve(DEMO);
    const { default: Landing } = await import("@/app/page");
    render(<Landing />);
    expect(await screen.findByText(/13 set aside/)).toBeInTheDocument();
    expect(screen.getByText(/1 to read/)).toBeInTheDocument();
    expect(screen.getByText(/7 importers · 2 past fixes/)).toBeInTheDocument();
    expect(screen.getByText(/13 formatting only/)).toBeInTheDocument();
  });

  it("still renders the story when the demo data cannot load", async () => {
    serve(null);
    const { default: Landing } = await import("@/app/page");
    const { container } = render(<Landing />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("with a memory.");
    for (const step of ["Remember", "Triage", "Decide"]) expect(screen.getAllByText(new RegExp(step)).length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("undefined");
  });

  it("installs the v2.0.0 release", async () => {
    serve(DEMO);
    const { default: Landing } = await import("@/app/page");
    render(<Landing />);
    expect(screen.getByText(/releases\/download\/v2\.0\.0\/repopilot-2\.0\.0-py3-none-any\.whl/)).toBeInTheDocument();
  });
});
