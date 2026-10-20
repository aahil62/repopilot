import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BenchResult, BlastReport, ModelsResponse, RepoSummary, ReviewReport } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/app/" }));

const repo: RepoSummary = {
  repo_id: "r1", name: "shop", path: "/code/shop", source: "local", remote: null, added_at: "2026-01-01T00:00:00Z",
  files: 12, chunks: 40, commits: 230, review_comments: 0, indexed_at: "2026-01-02T00:00:00Z", history_truncated: false, last_index: null,
};
const blast: BlastReport = {
  targets: ["shop.py"], risk: "medium", risk_reasons: ["`shop.py` usually changes together with `cart.py` (80% of the time)"],
  cochanged: [{ path: "cart.py", support: 8, confidence: 0.8 }], dependents: [{ path: "api.py", depth: 1 }],
  past_fixes: [{ sha: "abcdef1234", date: "2025-12-01T00:00:00Z", subject: "fix rounding in totals", author: "Dana" }],
  tests: ["tests/test_shop.py"], owners: [{ author: "Dana", commits: 5 }],
};
const review: ReviewReport = {
  review_id: "rv1", created_at: "2026-01-03T00:00:00Z", source: { kind: "working", base: "HEAD", head: null },
  summary: "Totals now skip tax.", files: [{ path: "shop.py", status: "modified", mechanical_hunks: 0, behavior_hunks: 1,
    hunks: [{ old_start: 3, new_start: 3, new_end: 3, label: "behavior", reason: "logic", text: "-    return a + tax\n+    return a" }] }],
  mechanical_count: 0, behavior_count: 1, findings: [], dropped_unverifiable: 0, blast, precedents: [],
  checks: { command: "pytest -q", status: "passed", output_tail: "", duration_s: 1, message: "" },
  model: {}, model_error: null, truncated: false, timings_ms: { total: 900 },
};
const models: ModelsResponse = {
  runtimes: [{ base_url: "http://127.0.0.1:11434", kind: "ollama", reachable: true, error: null }],
  models: [
    { id: "qwen2.5-coder:7b", runtime: "ollama", base_url: "x", size_bytes: 4.7 * 1024 ** 3, context_length: 32768, is_embedding: false, fits: true },
    { id: "nomic-embed-text", runtime: "ollama", base_url: "x", size_bytes: 0.3 * 1024 ** 3, context_length: null, is_embedding: true, fits: true },
  ],
  roles: { strong: "qwen2.5-coder:7b", fast: "qwen2.5-coder:7b", embed: "nomic-embed-text" },
  hardware: { total_ram_bytes: 16 * 1024 ** 3, gpu: "Apple M4", vram_bytes: 12 * 1024 ** 3, unified_memory: true, model_budget_bytes: 9.6 * 1024 ** 3 },
};
const bench: BenchResult = {
  created_at: "2026-01-04T00:00:00Z", repo_id: "r1", tasks: [{ sha: "s1", subject: "Add discount", paths: ["shop.py"] }],
  models: [{ model: "qwen2.5-coder:7b", size_bytes: 1, score: 0.71, applies_rate: 1, tests_pass_rate: 0.5, similarity: 0.6, median_latency_s: 18, tokens_per_second: 34, tasks: [] }],
  skipped: [{ model: "qwen3-coder:30b", reason: "needs ~18.6 GB" }],
  recommendation: "Use qwen2.5-coder:7b for review and code (score 0.71, median 18 s on your machine).",
  recommended_strong: "qwen2.5-coder:7b", recommended_fast: "qwen2.5-coder:7b",
};

const mockApi = {
  repos: vi.fn(async () => [repo]),
  models: vi.fn(async () => models),
  reviews: vi.fn(async () => []),
  review: vi.fn(async () => review),
  startReview: vi.fn(async () => ({ job_id: "j1" })),
  files: vi.fn(async () => [{ path: "shop.py", language: "python", lines: 20 }]),
  blast: vi.fn(async () => blast),
  nightReports: vi.fn(async () => []),
  bench: vi.fn(async () => bench),
  settings: vi.fn(async () => ({ test_command: null, detected_test_command: "pytest -q" })),
  saveSettings: vi.fn(),
  deleteRepo: vi.fn(async () => ({ deleted: "r1" })),
  privacy: vi.fn(async () => ({ data_dir: "/home/me/.repopilot", model_runtime_urls: ["http://127.0.0.1:11434"], github_review_import: false, telemetry: false, network_calls: [] })),
};

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, DEMO: false, api: mockApi, waitForJob: vi.fn(async () => review) };
});

beforeEach(() => {
  Object.values(mockApi).forEach((fn) => fn.mockClear());
  window.history.replaceState(null, "", "/");
});

describe("pages", () => {
  it("Overview shows the repository's memory", async () => {
    const { default: Page } = await import("@/app/app/page");
    render(<Page />);
    expect(await screen.findByRole("heading", { name: "shop" })).toBeInTheDocument();
    expect(screen.getByText("230")).toHaveClass("stat-number");
    expect(screen.getByRole("button", { name: "Add and index" })).toBeDisabled();
  });

  it("Review runs a review and shows what to read", async () => {
    const { default: Page } = await import("@/app/app/review/page");
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "Review changes" }));
    expect(await screen.findByText(/of 1 hunks change behavior/)).toBeInTheDocument();
    expect(mockApi.startReview).toHaveBeenCalledWith("r1", { run_checks: true });
    expect(screen.getByText("Totals now skip tax.")).toBeInTheDocument();
  });

  it("Review titles the page in the display style and marks behavior in amber", async () => {
    const { default: Page } = await import("@/app/app/review/page");
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "Review changes" }));
    await screen.findByText(/of 1 hunks change behavior/);
    expect(screen.getByRole("heading", { level: 1, name: "Review" })).toHaveClass("page-title");
    expect(screen.getAllByText("1 to read").some((el) => el.classList.contains("chip") && el.classList.contains("behavior"))).toBe(true);
  });

  it("Review keeps a very long file path inside its card", async () => {
    const longPath = `src/${"very_long_directory_name/".repeat(6)}shop.py`;
    const { waitForJob } = await import("@/lib/api");
    vi.mocked(waitForJob).mockResolvedValueOnce({ ...review, files: [{ ...review.files[0], path: longPath }] });
    const { default: Page } = await import("@/app/app/review/page");
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "Review changes" }));
    const paths = await screen.findAllByText(longPath);
    expect(paths.some((el) => el.classList.contains("truncate"))).toBe(true);
  });

  it("Blast radius lists coupling, fixes and tests for the chosen file", async () => {
    window.history.replaceState(null, "", "/?path=shop.py");
    const { default: Page } = await import("@/app/app/blast/page");
    render(<Page />);
    expect(await screen.findByText("fix rounding in totals")).toBeInTheDocument();
    expect(screen.getByText("8 of 10 commits")).toBeInTheDocument();
    expect(screen.getByText("tests/test_shop.py")).toBeInTheDocument();
  });

  it("Night shift explains what to do when there are no reports", async () => {
    const { default: Page } = await import("@/app/app/nightshift/page");
    render(<Page />);
    expect(await screen.findByText("No night-shift reports yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run now" })).toBeInTheDocument();
  });

  it("Models shows the recommendation and models that don't fit", async () => {
    const { default: Page } = await import("@/app/app/models/page");
    render(<Page />);
    expect(await screen.findByText(/Use qwen2.5-coder:7b for review and code/)).toBeInTheDocument();
    expect(screen.getByText("skipped: needs ~18.6 GB")).toBeInTheDocument();
  });

  it("Settings deletes repository memory only after confirmation", async () => {
    const { default: Page } = await import("@/app/app/settings/page");
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete memory…" }));
    expect(mockApi.deleteRepo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete memory" }));
    await waitFor(() => expect(mockApi.deleteRepo).toHaveBeenCalledWith("r1"));
  });

  it("Privacy lists every network destination", async () => {
    const { default: Page } = await import("@/app/app/privacy/page");
    render(<Page />);
    expect(await screen.findByText("/home/me/.repopilot")).toBeInTheDocument();
    expect(screen.getByText("api.github.com")).toBeInTheDocument();
  });
});
