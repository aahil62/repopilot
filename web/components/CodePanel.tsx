"use client";

import { X } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { FileContent } from "@/lib/types";
import { Code } from "./DiffView";
import { ErrorNotice, Loading } from "./States";

const CONTEXT = 12;

export function CodePanel({ repoId, path, start, end, onClose }: {
  repoId: string; path: string; start: number; end: number; onClose?: () => void;
}) {
  const key = `${repoId}:${path}:${start}:${end}`;
  const [loaded, setLoaded] = useState<{ key: string; file?: FileContent; error?: unknown } | null>(null);
  const first = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.file(repoId, path, Math.max(1, start - CONTEXT), end + CONTEXT).then(
      (file) => setLoaded({ key, file }),
      (error) => setLoaded({ key, error }),
    );
  }, [key, repoId, path, start, end]);

  const current = loaded?.key === key ? loaded : null;
  const file = current?.file ?? null;
  const error = current?.error ?? null;

  useEffect(() => {
    first.current?.scrollIntoView({ block: "center" });
  }, [file]);

  return (
    <section className="panel code-panel" aria-label={`${path} lines ${start} to ${end}`}>
      <header className="code-panel-head">
        <span className="mono">{path}<span className="hint"> · lines {start}–{end}</span></span>
        {onClose && <button className="btn secondary small" onClick={onClose} aria-label="Close code"><X size={14} /></button>}
      </header>
      <div className="diff code-panel-body">
        {error !== null ? <div style={{ padding: 16 }}><ErrorNotice error={error} /></div> : !file ? <div style={{ padding: 16 }}><Loading /></div> : (
          file.lines.map((text, i) => {
            const no = file.start + i;
            const hit = no >= start && no <= end;
            return (
              <div key={no} ref={no === start ? first : undefined} className={`diff-line${hit ? " cited" : ""}`}>
                <span className="no" />
                <span className="no">{no}</span>
                <span className="sign" />
                <Code text={text} />
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
