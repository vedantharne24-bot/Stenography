# StegoLab — web app

React 19 + TypeScript + Vite single-page app for StegoLab. See the [project README](../README.md) for the full picture.

```bash
npm install
npm run dev        # http://localhost:5173 — proxies /api to the backend on :8000
npm test           # Vitest component and API-client tests
npm run typecheck  # strict TypeScript check
npm run build      # production bundle in dist/
```

| Folder | Contents |
| --- | --- |
| `src/pages` | One component per route (Dashboard, Secure Hide, Extract, Steganalysis, Forensics, Attack Lab, Experiments, Reports, History, Models, Audit Logs, Settings) |
| `src/landing`, `src/three` | Public landing page: React Three Fiber hero scene, scroll story and live AI demo |
| `src/components` | Shared UI: panels, dropzone, live operation log, risk gauge, charts, before/after slider |
| `src/lib` | API client (JWT in memory, refresh-cookie rotation, NDJSON streaming), auth context, hooks, types |

The dev server proxies `/api` to `VITE_API_PROXY` (default `http://127.0.0.1:8000`). In Docker the same is done by `nginx.conf`.
