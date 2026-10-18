# RepoPilot for VS Code

Private, history-aware code review on open models you run yourself. The extension talks only to the
RepoPilot service on your machine (`http://127.0.0.1:7341`); your code never leaves it.

## Setup

```bash
pipx install "git+https://github.com/aahil62/repopilot#subdirectory=backend"
ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text
```

The extension starts `repopilot serve` for you when it isn't running (setting `repopilot.autoStartServer`).

## Commands

| Command | What it does |
|---|---|
| RepoPilot: Review Working Changes | Splits your uncommitted changes into mechanical edits and behavior changes, runs your tests in a temporary copy, and reports findings in the Problems panel. Also on the Source Control title bar. |
| RepoPilot: Review Staged Changes | The same, for staged changes only. |
| RepoPilot: Show Blast Radius for This File | Files that usually change with this one, files that import it, past bug fixes and who knows it best. A summary also appears as a CodeLens at the top of each file. |
| RepoPilot: Ask About This Repository | Answers with links to the exact lines it used; "why" questions include relevant commits. |
| RepoPilot: Edit with Verification | Describe a change; RepoPilot writes it in a temporary worktree, runs your checks, retries on failure, and shows you only a diff that passed. Apply or discard. |
| RepoPilot: Open Night Shift Report | The overnight report in the RepoPilot web app. |
| RepoPilot: Pick Models | Choose which local model does review/code, classification and embeddings. |

## Settings

- `repopilot.serverUrl` — default `http://127.0.0.1:7341`
- `repopilot.autoStartServer` — default `true`
- `repopilot.codeLens` — blast-radius summary on each file, default `true`
- `repopilot.runChecks` — run tests during reviews, default `true`
