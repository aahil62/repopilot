# Deployment

RepoPilot is a local application: the backend and the models run on the user's machine, which is the product's privacy promise. The only hosted piece is the **public website**: the same Next.js app as the local UI, built in demo mode with data from a real RepoPilot run on `pallets/flask` (`scripts/build_demo.py`). There is no hosted backend, database or API key.

## Website (Vercel)

- Project `repopilot`, linked to `aahil62/repopilot` · root directory `web/` · framework Next.js · static export to `out` · `NEXT_PUBLIC_DEMO_MODE=1` (set in `web/vercel.json`).
- Production branch `main`; every pull request gets a preview URL.
- Before deploying new demo data, regenerate it with real models: `backend/.venv/bin/python scripts/build_demo.py` and `backend/.venv/bin/python eval/run_eval.py`.
- Check locally: `cd web && NEXT_PUBLIC_DEMO_MODE=1 npm run build && npx serve out`.

Why not Render (used for FraudLens): FraudLens is a live multi-user server with a database, so it needs a web service. RepoPilot's site is static, and Vercel serves it from a CDN with no cold start and per-PR previews.

## Retired (2026-10-20)

The hackathon deployments were removed: the Railway project `heroic-determination` and the Vercel projects `repopilot-backend`, `repopilot-frontend`, `backend` and `frontend`. Nothing in this repository points at them.

## Release

`python scripts/bundle_web.py` builds `dist/repopilot-2.0.0-py3-none-any.whl` with the UI bundled; `cd vscode-extension && npx @vscode/vsce package` builds the `.vsix`. Both are attached to the GitHub release `v2.0.0`.
