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


class _BehaviorOnly(ast.NodeTransformer):
    """Drop what cannot change runtime behavior: annotations, docstrings, TYPE_CHECKING blocks, unused imports."""

    def __init__(self, used: set[str]):
        self.used = used

    def _strip_docstring(self, node):
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(getattr(body[0], "value", None), ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.returns = None
        return self._strip_docstring(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=node.value, lineno=node.lineno)

    def visit_If(self, node):
        test = node.test
        name = (
            test.attr if isinstance(test, ast.Attribute) else test.id if isinstance(test, ast.Name) else None
        )
        if name == "TYPE_CHECKING":
            return node.orelse or None
        self.generic_visit(node)
        return node

    def _imports(self, node):
        kept = [a for a in node.names if (a.asname or a.name.split(".")[0]) in self.used or a.name == "*"]
        if not kept:
            return None
        node.names = kept
        return node

    visit_Import = _imports
    visit_ImportFrom = _imports


def _behavior_dump(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    # names re-exported via __all__ count as used
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            used |= {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
    return ast.dump(_BehaviorOnly(used).visit(tree))


def apply_hunk(old_text: str, hunk: Hunk) -> str:
    """The old file with only this hunk applied."""
    lines = old_text.splitlines()
    start = hunk.old_start if hunk.old_lines == 0 else hunk.old_start - 1
    new_side = [line[1:] for line in hunk.lines if line[:1] in (" ", "+")]
    return "\n".join(lines[:start] + new_side + lines[start + hunk.old_lines :]) + "\n"


def python_hunk_reason(old_text: str | None, hunk: Hunk) -> str | None:
    """If applying this hunk alone leaves the program's behavior unchanged, say why."""
    if old_text is None:
        return None
    new_text = apply_hunk(old_text, hunk)
    try:
        if ast.dump(ast.parse(old_text)) == ast.dump(ast.parse(new_text)):
            return "formatting only (identical Python syntax tree)"
    except (SyntaxError, ValueError):
        return None
    before, after = _behavior_dump(old_text), _behavior_dump(new_text)
    if before is not None and before == after:
        return "type annotations, docstrings or unused imports only"
    return None


def defined_names(text: str | None) -> set[str] | None:
    """Names a Python file defines itself (functions, classes, assignments, parameters)."""
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
    return names


def identifiers(text: str | None) -> set[str] | None:
    return set(IDENT.findall(text)) if text is not None else None


def classify_hunk(
    fd: FileDiff,
    hunk: Hunk,
    *,
    same_tree: bool = False,
    old_idents: set[str] | None = None,
    new_idents: set[str] | None = None,
    old_text: str | None = None,
) -> tuple[Label, str]:
    removed, added = hunk.removed, hunk.added
    is_python = fd.path.endswith((".py", ".pyi"))
    if same_tree:
        return "mechanical", "formatting only (identical Python syntax tree)"
    if not removed and not added:
        return "mechanical", "no content change"
    if fd.path.lower().endswith((".md", ".rst", ".txt")):
        return "mechanical", "documentation only"
    if is_python and fd.status == "modified" and (reason := python_hunk_reason(old_text, hunk)):
        return "mechanical", reason
    # In Python indentation is meaning, so whitespace-only is decided by the syntax tree above.
    if not is_python and _squash(removed) == _squash(added):
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
    # For Python, the old name must also be defined in this file: swapping one imported decorator for
    # another (`@locked_cached_property` -> `@cached_property`) is not a rename.
    old_defined = defined_names(old_text) if is_python else None
    if (
        mapping
        and old_idents is not None
        and new_idents is not None
        and all(a not in new_idents and b not in old_idents for a, b in mapping.items())
        and (old_defined is None or all(a in old_defined for a in mapping))
    ):
        pairs = ", ".join(f"`{a}` → `{b}`" for a, b in list(mapping.items())[:3])
        return "mechanical", f"rename {pairs}"
    return "behavior", "logic, data or interface change"
