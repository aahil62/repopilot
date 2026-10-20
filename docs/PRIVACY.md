# Privacy

| Destination | When | What is sent |
|---|---|---|
| Your model runtime (`127.0.0.1:11434`, `:1234`, `:8080` by default — `REPOPILOT_RUNTIME_URLS`) | Indexing (embeddings), reviews, questions, edits, night shift, benchmark | Code excerpts and prompts, to a program on your machine |
| `github.com` | Only when you add a repository by URL | A normal `git clone` |
| `api.github.com` | Only with `REPOPILOT_ALLOW_GITHUB_IMPORT=1` and `repopilot index --with-reviews` | Requests for the repository's closed PRs and their review comments (uses `GITHUB_TOKEN` if set) |

Nothing else. There are no accounts, analytics or telemetry, and the web UI loads no third-party scripts or fonts (fonts are bundled).

## Stored data

Everything lives in `~/.repopilot` (`REPOPILOT_HOME`):

- `repos.json` — the repositories you added
- `repos/<id>/memory.sqlite` — code chunks, vectors, symbols, history, review comments, saved reviews
- `repos/<id>/reports/`, `bench/` — night-shift reports and benchmark results
- `clones/` — repositories added by URL; `worktrees/` — temporary, removed after use

Delete a repository's memory from Settings, `DELETE /api/repos/<id>`, or by removing its folder.

## Checking it yourself

While RepoPilot is working: `lsof -i -P | grep -i python`. You should see only loopback connections.
