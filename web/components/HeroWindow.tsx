import type { BlastReport, HeroDemo } from "@/lib/types";

const TABS = ["Review", "Blast radius", "History", "Ask"];

function basename(path: string) {
  return path.split("/").pop() ?? path;
}

/** The frosted review window over the terrain. Every number comes from the demo data. */
export function HeroWindow({ hero, blast }: { hero: HeroDemo | null; blast: Record<string, BlastReport> | null }) {
  const files = hero ? [...hero.files].sort((a, b) => b.behavior_hunks - a.behavior_hunks) : [];
  const focus = files.find((f) => f.behavior_hunks > 0) ?? files[0];
  const total = hero ? hero.mechanical + hero.behavior : 0;
  const risk = focus && blast ? blast[focus.path] : undefined;
  const reason = files.flatMap((f) => f.hunks).find((h) => h.label === "mechanical")?.reason.split(" (")[0];

  const steps = hero
    ? [
        <>Classified {total} hunks · {hero.mechanical} {reason ?? "mechanical"}</>,
        focus && risk && <>Blast radius <span className="hw-hot">{basename(focus.path)}</span> · {risk.dependents.length} importers · {risk.past_fixes.length} past fixes</>,
        <>Read {hero.behavior} of {total} hunks · <span className="hw-hot">saved {hero.mechanical}</span></>,
      ].filter(Boolean)
    : [];

  return (
    <figure className="hw" aria-label={hero ? `RepoPilot reviewing ${hero.repo}` : "RepoPilot review window"}>
      <div className="hw-bar" aria-hidden="true"><i /><i /><i /></div>
      <header className="hw-head">
        <div>
          <p className="hw-title">Review · {hero?.repo ?? "your repository"}</p>
          <p className="hw-sub">{hero ? <>commit {hero.commit.slice(0, 8)} · “{hero.subject}”</> : "loading the demo commit"}</p>
        </div>
        {hero && (
          <div className="hw-chips">
            <span className="hw-chip">Mechanical <b>{hero.mechanical} set aside ✓</b></span>
            <span className="hw-chip hot">Behavior <b>{hero.behavior} to read</b></span>
          </div>
        )}
      </header>
      <div className="hw-body">
        <div className="hw-card">
          <div className="hw-tabs" aria-hidden="true">{TABS.map((t, i) => <span key={t} className={i === 0 ? "on" : undefined}>{t}</span>)}</div>
          {files.slice(0, 4).map((f) => (
            <div key={f.path} className={`hw-file${f.behavior_hunks ? " hot" : ""}`}>
              <span className="truncate">{f.path}</span>
              <span>{f.behavior_hunks ? `${f.behavior_hunks} behavior` : `formatting${f.mechanical_hunks > 1 ? ` ×${f.mechanical_hunks}` : ""}`}</span>
            </div>
          ))}
          <div className="hw-ask"><span>Why does {focus ? basename(focus.path) : "this file"} change here?</span><kbd>⌘K</kbd></div>
        </div>
        <div className="hw-card hw-log">
          <p className="hw-log-title">Review path · local model, this machine</p>
          {steps.map((s, i) => (
            <p key={i} className="hw-line" style={{ animationDelay: `${0.4 + i * 0.6}s` }}><span className="hw-n">{String(i + 1).padStart(2, "0")}</span>{s}</p>
          ))}
          <p className="hw-line" style={{ animationDelay: `${0.4 + steps.length * 0.6}s` }}><span className="hw-caret" aria-hidden="true" /></p>
        </div>
      </div>
    </figure>
  );
}
