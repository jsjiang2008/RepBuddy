# RepBuddy frontend

The workout interface uses React, TypeScript, and Vite. It gets the rep count,
timer, and camera preview from the local Python backend.

See the [project README](../README.md) for setup and tracking details.

To start both the frontend and Python tracker, run this from the project root:

```powershell
npm run dev
```

Press **Ctrl+C** to stop both. Running `npm run dev` from this `frontend` folder
starts only Vite. Vite proxies `/api` to `http://127.0.0.1:8000`.
The development UI uses port 5173.

From this folder, you can also build or check the frontend:

```powershell
npm run build
npm run lint
```
