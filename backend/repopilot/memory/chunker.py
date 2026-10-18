"""Split files into retrievable chunks with exact line ranges (1-based, inclusive)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

WINDOW = 120
OVERLAP = 20
MAX_SYMBOL_LINES = 150
JS_BOUNDARY = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+(?P<fn>[\w$]+)|class\s+(?P<cls>[\w$]+)"
    r"|(?:const|let|var)\s+(?P<const>[\w$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>)"
)
MD_HEADING = re.compile(r"^#{1,6}\s+(.+)")


@dataclass(frozen=True)
class ChunkSpec:
    start_line: int
    end_line: int
    kind: str  # function | class | module | doc | config | window
    symbol: str | None
    text: str


def _windows(lines: list[str], start: int, end: int, kind: str, symbol: str | None) -> list[ChunkSpec]:
    """Cover lines[start-1:end] with overlapping windows."""
    out: list[ChunkSpec] = []
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + WINDOW - 1)
        text = "\n".join(lines[cursor - 1 : stop])
        if text.strip():
            out.append(ChunkSpec(cursor, stop, kind, symbol, text))
        if stop == end:
            break
        cursor = stop - OVERLAP + 1
    return out


def _span(lines: list[str], start: int, end: int, kind: str, symbol: str | None) -> list[ChunkSpec]:
    if end - start + 1 > MAX_SYMBOL_LINES:
        return _windows(lines, start, end, kind, symbol)
    text = "\n".join(lines[start - 1 : end])
    return [ChunkSpec(start, end, kind, symbol, text)] if text.strip() else []


def _with_gaps(lines: list[str], spans: list[tuple[int, int, str, str | None]]) -> list[ChunkSpec]:
    """Emit symbol spans plus window chunks for the code between them (imports, constants, scripts)."""
    out: list[ChunkSpec] = []
    cursor = 1
    for start, end, kind, symbol in sorted(spans):
        if start > cursor:
            out.extend(_windows(lines, cursor, start - 1, "module", None))
        out.extend(_span(lines, start, end, kind, symbol))
        cursor = max(cursor, end + 1)
    if cursor <= len(lines):
        out.extend(_windows(lines, cursor, len(lines), "module", None))
    return out


def _python(lines: list[str], text: str) -> list[ChunkSpec] | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    spans = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            spans.append((start, node.end_lineno or node.lineno, kind, node.name))
    return _with_gaps(lines, spans)


def _javascript(lines: list[str]) -> list[ChunkSpec]:
    starts: list[tuple[int, str, str]] = []
    for number, line in enumerate(lines, start=1):
        match = JS_BOUNDARY.match(line)
        if match:
            kind = "class" if match.group("cls") else "function"
            starts.append((number, kind, match.group("fn") or match.group("cls") or match.group("const")))
    spans = []
    for i, (start, kind, name) in enumerate(starts):
        end = (starts[i + 1][0] - 1) if i + 1 < len(starts) else len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        spans.append((start, end, kind, name))
    return _with_gaps(lines, spans)


def _markdown(lines: list[str]) -> list[ChunkSpec]:
    heads = [
        (n, MD_HEADING.match(line).group(1).strip())
        for n, line in enumerate(lines, 1)
        if MD_HEADING.match(line)
    ]
    if not heads:
        return _windows(lines, 1, len(lines), "doc", None)
    spans = []
    for i, (start, title) in enumerate(heads):
        end = heads[i + 1][0] - 1 if i + 1 < len(heads) else len(lines)
        spans.append((start, end, "doc", title))
    return _with_gaps(lines, spans)


def chunk_file(path: str, text: str, language: str) -> list[ChunkSpec]:
    lines = text.splitlines()
    if not lines:
        return []
    if language == "python":
        result = _python(lines, text)
        if result is not None:
            return result
    if language in {"javascript", "typescript"}:
        return _javascript(lines)
    if language == "markdown":
        return _markdown(lines)
    kind = "config" if language in {"json", "yaml", "toml", "ini", "config"} else "window"
    return _windows(lines, 1, len(lines), kind, None)
