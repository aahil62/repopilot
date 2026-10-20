import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { hunkRows } from "@/components/DiffView";
import { layout } from "@/components/Orbit";
import { ReviewReportView } from "@/components/ReviewReport";
import type { BlastReport, ReviewReport } from "@/lib/types";

const blast: BlastReport = {
  targets: ["app.py"], risk: "medium", risk_reasons: ["`app.py` usually changes together with `ctx.py` (80% of the time)"],
  cochanged: [{ path: "ctx.py", support: 8, confidence: 0.8 }, { path: "tests/test_app.py", support: 4, confidence: 0.4 }],
  dependents: [{ path: "ctx.py", depth: 1 }, { path: "cli.py", depth: 2 }], past_fixes: [], tests: [], owners: [],
};

const report: ReviewReport = {
  review_id: "r1", created_at: "2026-01-01T00:00:00Z", source: { kind: "working", base: "HEAD", head: null },
  summary: "Discount now increases the price. Behavior changes to read: 1 of 3 hunks.",
  files: [{
    path: "shop.py", status: "modified", mechanical_hunks: 2, behavior_hunks: 1, hunks: [
      { old_start: 1, new_start: 1, new_end: 2, label: "behavior", reason: "logic, data or interface change", text: " def f(p, r):\n-    return p * (1 - r)\n+    return p * (1 + r)" },
      { old_start: 10, new_start: 10, new_end: 10, label: "mechanical", reason: "whitespace or line-wrapping only", text: "-x = f(a,b)\n+x = f(a, b)" },
      { old_start: 20, new_start: 20, new_end: 20, label: "mechanical", reason: "rename `a` → `b`", text: "-a = 1\n+b = 1" },
    ],
  }],
  mechanical_count: 2, behavior_count: 1,
  findings: [{ severity: "high", path: "shop.py", line: 2, title: "Discount adds instead of subtracting", explanation: "Raises prices.",
    evidence: ["PR #412"], evidence_detail: [{ kind: "review_comment", ref: "PR #412", sha: null, path: "shop.py", excerpt: "Discounts must never raise a price", similarity: 0.81 }] }],
  dropped_unverifiable: 1, blast, precedents: [], checks: { command: "pytest -q", status: "failed", output_tail: "assert 125 == 75", duration_s: 1.2, message: "" },
  model: { strong: "qwen2.5-coder:7b", fast: "qwen2.5-coder:1.5b", embed: "nomic-embed-text" }, model_error: null, truncated: false, timings_ms: { total: 4200 },
};

describe("DiffView", () => {
  it("numbers old and new lines separately", () => {
    const rows = hunkRows({ old_start: 10, new_start: 20, text: " a\n-b\n+c\n d" });
    expect(rows.map((r) => [r.kind, r.oldNo, r.newNo])).toEqual([["ctx", 10, 20], ["del", 11, null], ["add", null, 21], ["ctx", 12, 22]]);
  });
});

describe("Orbit layout", () => {
  it("draws a file that both imports and co-changes only once", () => {
    const paths = layout(blast).map((n) => n.path);
    expect(paths.filter((p) => p === "ctx.py")).toHaveLength(1);
    expect(new Set(paths).size).toBe(paths.length);
    expect(layout(blast).find((n) => n.path === "ctx.py")?.imports).toBe(true);
  });
});

describe("ReviewReportView", () => {
  it("leads with what to read and keeps mechanical hunks collapsed", () => {
    render(<ReviewReportView report={report} />);
    expect(screen.getByText(/of 3 hunks change behavior/)).toBeInTheDocument();
    expect(screen.getByText(/The other 2 are whitespace or line-wrapping only, rename `a` → `b`/)).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Mechanical · 2 hunks/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("x = f(a, b)")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByText("x = f(a, b)")).toBeInTheDocument();
  });

  it("shows evidence, dropped findings and failing checks", () => {
    render(<ReviewReportView report={report} />);
    expect(screen.getByText("Discount adds instead of subtracting")).toBeInTheDocument();
    expect(screen.getByText("Discounts must never raise a price")).toBeInTheDocument();
    expect(screen.getByText(/1 model finding was discarded/)).toBeInTheDocument();
    expect(screen.getByText("assert 125 == 75")).toBeInTheDocument();
  });
});

describe("Ask answer", () => {
  it("turns only supplied citation numbers into buttons", async () => {
    const { Answer } = await import("@/components/Answer");
    const onCite = vi.fn();
    render(<Answer text="Login lives in auth [1] and maybe [7]." citations={[{ n: 1, path: "auth.py", start_line: 1, end_line: 3, snippet: "" }]} active={null} onCite={onCite} />);
    fireEvent.click(screen.getByRole("button", { name: "Show source 1" }));
    expect(onCite).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("button", { name: "Show source 7" })).not.toBeInTheDocument();
    expect(screen.getByText(/maybe \[7\]/)).toBeInTheDocument();
  });
});
