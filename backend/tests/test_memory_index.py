import subprocess
import time

from repopilot.config import get_settings
from repopilot.memory.chunker import chunk_file
from repopilot.memory.files import iter_repo_files
from repopilot.memory.indexer import index_code
from repopilot.memory.store import MemoryStore
from repopilot.memory.symbols import extract
from repopilot.runtime import FakeRuntime

PY = """import os

LIMIT = 3


def first(a):
    return a + 1


@decorator
def second(b):
    return b * 2


class Box:
    def open(self):
        return True
"""


def test_python_chunks_follow_symbols_and_cover_gaps():
    chunks = chunk_file("m.py", PY, "python")
    by_symbol = {c.symbol: c for c in chunks}
    assert (by_symbol["first"].start_line, by_symbol["first"].end_line) == (6, 7)
    assert by_symbol["second"].start_line == 10  # decorator included
    assert by_symbol["Box"].kind == "class" and by_symbol["Box"].end_line == 17
    module = [c for c in chunks if c.kind == "module"]
    assert module and module[0].start_line == 1 and "LIMIT" in module[0].text


def test_long_function_is_split_into_overlapping_windows():
    body = "\n".join(f"    x{i} = {i}" for i in range(300))
    chunks = [c for c in chunk_file("big.py", f"def big():\n{body}\n", "python") if c.symbol == "big"]
    assert len(chunks) == 3
    assert chunks[1].start_line == chunks[0].end_line - 19


def test_js_exports_and_imports_detected():
    src = "import { a } from './util';\nconst x = require('lodash');\n\nexport function load(url) {\n  return a(url);\n}\n\nexport const save = async (v) => v;\nexport class Store {}\n"
    symbols, imports = extract("src/app.ts", src, "typescript")
    assert [s.name for s in symbols] == ["load", "save", "Store"]
    assert {i.spec for i in imports} == {"./util", "lodash"}
    chunk_symbols = {c.symbol for c in chunk_file("src/app.ts", src, "typescript")}
    assert {"load", "save", "Store"} <= chunk_symbols


def test_python_imports_keep_relative_level():
    _, imports = extract("pkg/a.py", "from .b import thing\nimport pkg.c\nfrom ..d import e\n", "python")
    assert [(i.spec, i.names) for i in imports] == [(".b", "thing"), ("pkg.c", ""), ("..d", "e")]


async def test_incremental_reindex_only_embeds_changed_file(git_repo):
    repo = git_repo([("init", {"a.py": "def a():\n    return 1\n", "b.py": "def b():\n    return 2\n"})])
    store = MemoryStore("t1")
    fake = FakeRuntime()
    first = await index_code(store, repo, fake)
    assert first.files_changed == 2 and first.chunks_embedded == 2

    (repo / "b.py").write_text("def b():\n    return 3\n")
    fake.embed_calls.clear()
    second = await index_code(store, repo, fake)
    assert second.files_changed == 1
    assert sum(len(c) for c in fake.embed_calls) == 1
    assert "return 3" in fake.embed_calls[0][0]


async def test_deleted_file_removes_chunks_and_vectors(git_repo):
    repo = git_repo([("init", {"a.py": "def a():\n    return 1\n", "b.py": "def b():\n    return 2\n"})])
    store = MemoryStore("t2")
    await index_code(store, repo, FakeRuntime())
    (repo / "b.py").unlink()
    stats = await index_code(store, repo, FakeRuntime())
    assert stats.files_removed == 1
    assert store.query("SELECT count(*) n FROM chunks WHERE path='b.py'")[0]["n"] == 0
    assert store.query("SELECT count(*) n FROM vectors")[0]["n"] == 1


def test_gitignored_and_vendored_files_skipped(git_repo):
    repo = git_repo([("init", {".gitignore": "secret.py\n", "keep.py": "x = 1\n", "secret.py": "y = 2\n"})])
    (repo / "node_modules" / "lib").mkdir(parents=True)
    (repo / "node_modules" / "lib" / "index.js").write_text("module.exports = 1\n")
    (repo / "logo.png").write_bytes(b"\x89PNG\0\0data")
    paths = {f.path for f in iter_repo_files(repo, get_settings())}
    assert "keep.py" in paths and "secret.py" not in paths
    assert not any(p.startswith("node_modules") for p in paths)


async def test_vector_search_returns_relevant_chunk(git_repo):
    repo = git_repo(
        [
            (
                "init",
                {
                    "auth.py": "def login_user(password):\n    return check(password)\n",
                    "math.py": "def add_numbers(a, b):\n    return a + b\n",
                },
            )
        ]
    )
    store = MemoryStore("t3")
    fake = FakeRuntime()
    await index_code(store, repo, fake)
    [query_vec] = await fake.embed(["login user password"])
    best_key, _ = store.search("code", query_vec, k=1)[0]
    assert store.one("SELECT path FROM chunks WHERE chunk_id=?", (best_key,))["path"] == "auth.py"


async def test_large_repo_indexes_within_budget(tmp_path):
    root = tmp_path / "large"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for i in range(5000):
        d = root / f"pkg{i // 100}"
        d.mkdir(exist_ok=True)
        (d / f"m{i}.py").write_text(f"def f{i}(x):\n    return x + {i}\n")
    started = time.perf_counter()
    stats = await index_code(MemoryStore("large"), root, FakeRuntime())
    assert stats.files_total == 5000 and stats.chunks_total == 5000
    assert time.perf_counter() - started < 120


async def test_changing_embedding_model_rebuilds_vectors(git_repo):
    from repopilot.runtime.detect import ModelInfo

    repo = git_repo([("init", {"a.py": "def a():\n    return 1\n"})])
    store = MemoryStore("t-emb")
    await index_code(store, repo, FakeRuntime())
    other = FakeRuntime()
    other.roles = {
        **other.roles,
        "embed": ModelInfo("nomic-embed-text", "ollama", "http://x", is_embedding=True),
    }
    stats = await index_code(store, repo, other)
    assert stats.chunks_embedded == 1 and any("rebuilt the search index" in n for n in stats.notes)
    assert store.get_meta("embed_model") == "nomic-embed-text"
