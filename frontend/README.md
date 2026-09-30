# RepBuddy frontend

React + TypeScript + Vite. This UI receives real tracking status from the local
Python API; no demo counter runs in the frontend.

See the [project README](../README.md) for setup, both startup commands, tests,
and the camera/control lifecycle.

From this folder:

```powershell
npm install
npm run dev
```

Start the Python server separately from the project root. Vite proxies `/api`
to `http://127.0.0.1:8000`. The development UI uses port 5173.

```powershell
npm run build
npm run lint
```
