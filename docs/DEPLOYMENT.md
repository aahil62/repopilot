# Deployment

RepoPilot is a local application. The only hosted piece is a **static demo** of the web UI whose data was produced by a real RepoPilot run on `pallets/flask` (`scripts/build_demo.py`). There is no hosted backend: one would need a cloud model, which contradicts the product's privacy promise.

## Public demo (Vercel)

- Project root: `web/` · framework: Next.js · output: `out` (static export) · env: `NEXT_PUBLIC_DEMO_MODE=1` (set in `web/vercel.json`).
- Production branch: `main`.
- Before deploying, regenerate the demo with real models so every page has data: `backend/.venv/bin/python scripts/build_demo.py` (without `--offline`) and `backend/.venv/bin/python eval/run_eval.py`.
- Check locally: `cd web && NEXT_PUBLIC_DEMO_MODE=1 npm run build && npx serve out`.

## Retiring the hackathon deployment

The old deployment (`repopilot-ext.vercel.app`) served the `website` branch with a Gemini-backed serverless backend, and a Railway service built `main`. To replace it:

1. Vercel → project → Settings → Git → Production Branch = `main`; General → Root Directory = `web`; Environment Variables → remove `GEMINI_API_KEY`, `BACKEND_URL`, `NEXT_PUBLIC_API_URL`; redeploy.
2. Railway → the RepoPilot backend service → disconnect the GitHub repository (or delete the service) and remove its secrets.
3. Verify: the site loads with the demo banner and `/api/health` returns 404.

## Release

`python scripts/bundle_web.py` builds `dist/repopilot-2.0.0-py3-none-any.whl` with the UI bundled; `cd vscode-extension && npx @vscode/vsce package` builds the `.vsix`. Attach both to a GitHub release.
