"""Separate mechanical edits (formatting, comments, import order, renames) from behavior changes."""

from __future__ import annotations

import ast
import re
from typing import Literal

from repopilot.engines.diffparse import FileDiff, Hunk

Label = Literal["mechanical", "behavior"]
IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
TOKEN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+(?:\.\d+)?|\S")
KEYWORDS = {
    "def",
    "class",
    "return",
    "if",
    "else",
    "elif",
    "for",
    "while",
    "in",
    "not",
    "and",
    "or",
    "is",
    "None",
    "True",
    "False",
    "import",
    "from",
    "as",
    "with",
    "try",
    "except",
    "finally",
    "raise",
    "lambda",
    "yield",
    "await",
    "async",
    "pass",
    "break",
    "continue",
    "global",
    "nonlocal",
    "del",
    "assert",
    "function",
    "const",
    "let",
    "var",
    "new",
    "this",
    "null",
    "undefined",
    "true",
    "false",
    "export",
    "default",
    "typeof",
    "instanceof",
    "switch",
    "case",
    "throw",
    "catch",
    "public",
    "private",
    "protected",
    "static",
    "void",
    "int",
    "string",
    "self",
}
COMMENT_PREFIXES = ("#", "//", "/*", "*", "*/", "<!--", "--")
IMPORT_LINE = re.compile(r"^\s*(import\s|from\s+\S+\s+import\s|const\s+\w+\s*=\s*require\(|use\s|#include\s)")


def _squash(lines: list[str]) -> str:
    return "".join("".join(line.split()) for line in lines)


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(COMMENT_PREFIXES)


def _docstring_only(lines: list[str]) -> bool:
    stripped = [line.strip() for line in lines if line.strip()]
    return bool(stripped) and all(
        s.startswith(('"""', "'''")) or s.endswith(('"""', "'''")) for s in stripped
    )


def _rename(removed: list[str], added: list[str]) -> dict[str, str] | None:
    """If added == removed with identifiers consistently renamed, return the mapping."""
    if len(removed) != len(added) or not removed:
        return None
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for old_line, new_line in zip(removed, added, strict=True):
        old_tokens, new_tokens = TOKEN.findall(old_line), TOKEN.findall(new_line)
        if len(old_tokens) != len(new_tokens):
            return None
        for a, b in zip(old_tokens, new_tokens, strict=True):
            if a == b:
                continue
            if not (IDENT.fullmatch(a) and IDENT.fullmatch(b)) or a in KEYWORDS or b in KEYWORDS:
                return None
            if mapping.setdefault(a, b) != b or reverse.setdefault(b, a) != a:
                return None
    return mapping or None


def python_same_tree(old_text: str | None, new_text: str | None) -> bool:
    if old_text is None or new_text is None:
        return False
    try:
        return ast.dump(ast.parse(old_text)) == ast.dump(ast.parse(new_text))
    except (SyntaxError, ValueError):
        return False


def identifiers(text: str | None) -> set[str] | None:
    return set(IDENT.findall(text)) if text is not None else None


def classify_hunk(
    fd: FileDiff,
    hunk: Hunk,
    *,
    same_tree: bool = False,
    old_idents: set[str] | None = None,
    new_idents: set[str] | None = None,
) -> tuple[Label, str]:
    removed, added = hunk.removed, hunk.added
    if same_tree:
        return "mechanical", "formatting only (identical Python syntax tree)"
    if not removed and not added:
        return "mechanical", "no content change"
    if fd.path.lower().endswith((".md", ".rst", ".txt")):
        return "mechanical", "documentation only"
    if _squash(removed) == _squash(added):
        return "mechanical", "whitespace or line-wrapping only"
    if all(_is_comment(line) for line in removed + added) or _docstring_only(removed + added):
        return "mechanical", "comments or docstrings only"
    changed = [line for line in removed + added if line.strip()]
    if changed and all(IMPORT_LINE.match(line) for line in changed):
        if sorted(s.strip() for s in removed if s.strip()) == sorted(s.strip() for s in added if s.strip()):
            return "mechanical", "import reordering"
    if fd.status == "renamed" and not removed and not added:
        return "mechanical", "file moved"
    mapping = _rename(removed, added)
    # A true rename: the old name is gone from the new file and the new name did not exist before.
    # Swapping one existing variable for another (`return total` -> `return subtotal`) is behavior.
    if (
        mapping
        and old_idents is not None
        and new_idents is not None
        and all(a not in new_idents and b not in old_idents for a, b in mapping.items())
    ):
        pairs = ", ".join(f"`{a}` → `{b}`" for a, b in list(mapping.items())[:3])
        return "mechanical", f"rename {pairs}"
    return "behavior", "logic, data or interface change"
