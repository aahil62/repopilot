"""File-level import graph for Python and JavaScript/TypeScript."""

from __future__ import annotations

import json
import posixpath
from collections import deque
from dataclasses import dataclass, field

from repopilot.memory.store import MemoryStore

JS_EXTS = (
    "",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)


@dataclass
class Graph:
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}

    @classmethod
    def from_dict(cls, data: dict) -> Graph:
        return cls(nodes=data.get("nodes", []), edges=data.get("edges", []))


def _python_module_index(paths: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in paths:
        if not path.endswith(".py"):
            continue
        parts = path[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        index.setdefault(".".join(parts), path)
        for prefix in ("src", "lib"):  # src-layout packages are imported without the prefix
            if parts[0] == prefix and len(parts) > 1:
                index.setdefault(".".join(parts[1:]), path)
    return index


def _resolve_python(importer: str, spec: str, names: str, index: dict[str, str]) -> list[str]:
    level = len(spec) - len(spec.lstrip("."))
    module = spec[level:]
    if level:
        package = importer.rsplit("/", 1)[0].split("/") if "/" in importer else []
        base = package[: len(package) - (level - 1)] if level > 1 else package
        dotted = ".".join([*base, *([module] if module else [])])
        candidates = [dotted] + [f"{dotted}.{n}" if dotted else n for n in names.split(",") if n]
        out = []
        for cand in candidates:
            for key in (cand, cand.split(".", 1)[1] if cand.startswith(("src.", "lib.")) else None):
                if key and key in index:
                    out.append(index[key])
                    break
        return out
    candidates = [f"{module}.{n}" for n in names.split(",") if n] + [module]
    found = []
    for cand in candidates:
        parts = cand.split(".")
        while parts:
            key = ".".join(parts)
            if key in index:
                found.append(index[key])
                break
            parts.pop()
    return found[:1] if not names else list(dict.fromkeys(found))


def _resolve_js(importer: str, spec: str, paths: set[str]) -> list[str]:
    if spec.startswith("."):
        bases = [posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))]
    elif spec.startswith(("@/", "~/")):
        bases = [spec[2:], f"src/{spec[2:]}"]
    else:
        return []
    for base in bases:
        for ext in JS_EXTS:
            if base + ext in paths:
                return [base + ext]
    return []


def build_graph(store: MemoryStore) -> Graph:
    files = store.query("SELECT path, language, lines FROM files")
    paths = [f["path"] for f in files]
    path_set = set(paths)
    py_index = _python_module_index(paths)
    lang = {f["path"]: f["language"] for f in files}
    edges: set[tuple[str, str]] = set()
    for row in store.query("SELECT path, spec, names FROM imports"):
        if lang.get(row["path"]) == "python":
            targets = _resolve_python(row["path"], row["spec"], row["names"], py_index)
        else:
            targets = _resolve_js(row["path"], row["spec"], path_set)
        edges.update((row["path"], t) for t in targets if t != row["path"])
    graph = Graph(
        nodes=[{"path": f["path"], "language": f["language"], "loc": f["lines"]} for f in files],
        edges=[{"source": s, "target": t} for s, t in sorted(edges)],
    )
    store.set_meta("graph", json.dumps(graph.to_dict()))
    return graph


def load_graph(store: MemoryStore) -> Graph:
    raw = store.get_meta("graph")
    return Graph.from_dict(json.loads(raw)) if raw else Graph()


def dependents(graph: Graph, path: str, depth: int = 2) -> list[tuple[str, int]]:
    """Files that import `path` directly (depth 1) or through one intermediate file (depth 2)."""
    reverse: dict[str, list[str]] = {}
    for edge in graph.edges:
        reverse.setdefault(edge["target"], []).append(edge["source"])
    seen = {path: 0}
    queue = deque([path])
    while queue:
        current = queue.popleft()
        if seen[current] >= depth:
            continue
        for src in reverse.get(current, []):
            if src not in seen:
                seen[src] = seen[current] + 1
                queue.append(src)
    return sorted(((p, d) for p, d in seen.items() if p != path), key=lambda x: (x[1], x[0]))
