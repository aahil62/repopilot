from repopilot.engines.ask import ask, calibrate_refusal, clean_citations, rrf
from repopilot.memory.history import import_history
from repopilot.memory.indexer import index_code
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime


def test_rrf_rewards_agreement():
    fused = rrf([["a", "b", "c"], ["c", "a", "d"]])
    assert [k for k, _ in fused][:2] == ["a", "c"]
    assert fused[0][1] == round(1 / 61 + 1 / 62, 10) or abs(fused[0][1] - (1 / 61 + 1 / 62)) < 1e-12


def test_unsupported_citation_removed():
    text, used, removed = clean_citations("Login is in auth [1] and billing [7].", {1, 2})
    assert used == [1] and removed == 1
    assert "[7]" not in text and "1 unsupported citation removed" in text


FILES = {
    "auth.py": "def login_user(username, password):\n    session = create_session(username)\n    return session\n",
    "billing.py": "def charge_card(amount):\n    return gateway.charge(amount)\n",
    "utils.py": "def slugify(text):\n    return text.lower().replace(' ', '-')\n",
    "models.py": "class User:\n    pass\n\n\nclass Invoice:\n    pass\n",
    "views.py": "def render_page(name):\n    return name\n",
}


async def _index(git_repo, rid, commits=None):
    repo = git_repo(commits or [("init", FILES)])
    store = MemoryStore.open(rid)
    fake = FakeRuntime()
    await index_code(store, repo, fake)
    import_history(store, repo, 100)
    await calibrate_refusal(store, fake)
    return store


async def test_answer_cites_retrieved_lines(git_repo):
    store = await _index(git_repo, "q1")
    fake = FakeRuntime(
        {"strong": ["Users log in through `login_user`, which creates a session [1]. See also [9]."]}
    )
    result = await ask(store, fake, "Where does login_user create the session?")
    assert result.citations[0].path == "auth.py"
    assert (result.citations[0].start_line, result.citations[0].end_line) == (1, 3)
    assert result.removed_citations == 1 and not result.refused


async def test_refuses_when_repository_lacks_topic(git_repo):
    store = await _index(git_repo, "q2")
    fake = FakeRuntime({"strong": ["should not be called"]})
    result = await ask(store, fake, "Show the Kafka consumer configuration")
    assert result.refused and result.answer.startswith("I couldn't find this in the repository.")
    assert not [c for c in fake.calls if c["role"] == "strong"]


async def test_why_question_includes_commit_history(git_repo):
    commits = [
        ("init", FILES),
        (
            "Retry charge_card three times because the gateway drops requests",
            {"billing.py": FILES["billing.py"] + "RETRIES = 3\n"},
        ),
    ]
    store = await _index(git_repo, "q3", commits)
    fake = FakeRuntime({"strong": ["Because the gateway drops requests [1]."]})
    result = await ask(store, fake, "Why does charge_card retry?")
    assert result.commits and "gateway drops requests" in result.commits[0].subject
    assert "Relevant commits" in fake.calls[0]["messages"][1]["content"]
