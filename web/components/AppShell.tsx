"use client";

import {
  ChatCircleText, Cpu, GearSix, GitDiff, House, LockSimple, MoonStars, Target, List, X,
} from "@phosphor-icons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, ApiError, DEMO } from "@/lib/api";
import type { ModelsResponse, RepoSummary } from "@/lib/types";
import { Brand } from "./Brand";
import "./shell.css";

const NAV = [
  { href: "/app/", label: "Overview", icon: House },
  { href: "/app/review/", label: "Review", icon: GitDiff },
  { href: "/app/blast/", label: "Blast radius", icon: Target },
  { href: "/app/nightshift/", label: "Night shift", icon: MoonStars },
  { href: "/app/ask/", label: "Ask", icon: ChatCircleText },
  { href: "/app/models/", label: "Models", icon: Cpu },
  { href: "/app/settings/", label: "Settings", icon: GearSix },
];

interface RepoCtx {
  repos: RepoSummary[];
  repo: RepoSummary | null;
  loading: boolean;
  error: ApiError | null;
  selectRepo: (id: string) => void;
  refresh: () => Promise<void>;
  models: ModelsResponse | null;
}

const Ctx = createContext<RepoCtx | null>(null);

export function useRepo(): RepoCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRepo must be used inside <AppShell>");
  return ctx;
}

const STORAGE_KEY = "repopilot.repo";

export function AppShell({ title, children }: { title: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  const applyRepos = useCallback((list: RepoSummary[]) => {
    setRepos(list);
    setError(null);
    const fromUrl = new URLSearchParams(window.location.search).get("repo");
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      /* storage unavailable */
    }
    setRepoId((current) => {
      const wanted = current || fromUrl || stored;
      return list.find((r) => r.repo_id === wanted)?.repo_id ?? list[0]?.repo_id ?? null;
    });
  }, []);

  const onLoadError = useCallback((e: unknown) => {
    setError(e instanceof ApiError ? e : new ApiError(0, "RepoPilot is not running. Start it with `repopilot serve`."));
  }, []);

  const refresh = useCallback(async () => {
    try {
      applyRepos(await api.repos());
    } catch (e) {
      onLoadError(e);
    } finally {
      setLoading(false);
    }
  }, [applyRepos, onLoadError]);

  useEffect(() => {
    api.repos().then(applyRepos, onLoadError).finally(() => setLoading(false));
    api.models().then(setModels).catch(() => setModels(null));
  }, [applyRepos, onLoadError]);

  const selectRepo = useCallback((id: string) => {
    setRepoId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const repo = useMemo(() => repos.find((r) => r.repo_id === repoId) ?? null, [repos, repoId]);
  const strong = models?.roles.strong;

  return (
    <Ctx.Provider value={{ repos, repo, loading, error, selectRepo, refresh, models }}>
      <div className="shell">
        {DEMO && (
          <div className="demo-banner" role="note">
            This is a demo with results RepoPilot computed on <strong>pallets/flask</strong>. Run it locally to review your own code.
          </div>
        )}
        <aside className={`rail${navOpen ? " open" : ""}`} aria-label="Main navigation">
          <div className="rail-top">
            <Link href="/" className="rail-brand"><Brand /></Link>
            <button className="rail-close" onClick={() => setNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
          </div>
          <label className="rail-repo">
            <span className="sr-only">Repository</span>
            <select className="select" value={repoId ?? ""} onChange={(e) => selectRepo(e.target.value)} disabled={!repos.length}>
              {!repos.length && <option value="">No repositories yet</option>}
              {repos.map((r) => <option key={r.repo_id} value={r.repo_id}>{r.name}</option>)}
            </select>
          </label>
          <nav>
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = href === "/app/" ? pathname === "/app" || pathname === "/app/" : pathname?.startsWith(href.slice(0, -1));
              return (
                <Link key={href} href={href} className={`rail-link${active ? " active" : ""}`} aria-current={active ? "page" : undefined}
                  onClick={() => setNavOpen(false)}>
                  <Icon size={18} weight={active ? "fill" : "regular"} />
                  {label}
                </Link>
              );
            })}
          </nav>
          <Link href="/app/privacy/" className="rail-privacy">
            <LockSimple size={16} weight="fill" />
            <span>Local only<small>No code leaves this machine</small></span>
          </Link>
        </aside>
        <div className="main">
          <header className="topbar">
            <button className="rail-open" onClick={() => setNavOpen(true)} aria-label="Open navigation"><List size={20} /></button>
            <h1>{title}</h1>
            <div className="topbar-right">
              {repo && <span className="topbar-repo mono">{repo.name}</span>}
              <span className={`model-pill${strong ? "" : " off"}`} title={strong ? "Model used for review and code" : "No model runtime detected"}>
                <span className="dot" />
                {strong ? strong : DEMO ? "demo data" : "no model runtime"}
              </span>
            </div>
          </header>
          <main className="content">{children}</main>
        </div>
      </div>
    </Ctx.Provider>
  );
}
