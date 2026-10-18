"""Extract defined symbols and import specifiers from source files."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

JS_EXPORT = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+([\w$]+)|class\s+([\w$]+)"
    r"|(?:const|let|var)\s+([\w$]+)\s*=)"
)
JS_IMPORT = re.compile(r"""(?:import\s+(?:[^'"]+?\s+from\s+)?|require\(\s*|import\(\s*)['"]([^'"]+)['"]""")


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ImportSpec:
    path: str
    spec: str  # python: dotted module with leading dots for relative imports; js: the module specifier
    names: str = ""


def _python(path: str, text: str) -> tuple[list[Symbol], list[ImportSpec]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], []
    symbols: list[Symbol] = []
    imports: list[ImportSpec] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbols.append(Symbol(node.name, kind, path, node.lineno, node.end_lineno or node.lineno))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                        symbols.append(
                            Symbol(
                                f"{node.name}.{child.name}",
                                "method",
                                path,
                                child.lineno,
                                child.end_lineno or child.lineno,
                            )
                        )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(ImportSpec(path, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            spec = "." * node.level + (node.module or "")
            imports.append(ImportSpec(path, spec, ",".join(alias.name for alias in node.names)))
    return symbols, imports


def _javascript(path: str, text: str) -> tuple[list[Symbol], list[ImportSpec]]:
    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith((" ", "\t")):
            continue
        match = JS_EXPORT.match(line)
        if match:
            # Plain module constants (`const x = require(...)`) are not API symbols; keep exported or arrow functions.
            if match.group(3) and not (line.startswith("export") or "=>" in line):
                continue
            name = next(g for g in match.groups() if g)
            kind = "class" if match.group(2) else "function"
            symbols.append(Symbol(name, kind, path, number, number))
    imports = [ImportSpec(path, m.group(1)) for m in JS_IMPORT.finditer(text)]
    return symbols, imports


def extract(path: str, text: str, language: str) -> tuple[list[Symbol], list[ImportSpec]]:
    if language == "python":
        return _python(path, text)
    if language in {"javascript", "typescript"}:
        return _javascript(path, text)
    return [], []
