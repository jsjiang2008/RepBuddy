# RepBuddy frontend

The workout interface uses React, TypeScript, and Vite. It gets webcam options,
the countdown, rep count, timer, camera preview, and saved workout history from
the local Python backend.

See the [project README](../README.md) for setup and tracking details.

To start both the frontend and Python tracker, run this from the project root:

```powershell
npm run dev
```

PostgreSQL runs as a Windows service. Configure `DATABASE_URL` in the root
`.env` file using the project README; Docker isn't required. Press **Ctrl+C**
to stop both app servers. The PostgreSQL service keeps running and retains
your saved workouts.

To use the optional Docker database, follow the Docker setup in the project
README and run `npm run dev:docker` from the root. `npm run db:stop` stops only
that Docker database, without deleting saved workouts.

Running `npm run dev` from this `frontend` folder starts only Vite. Vite proxies
`/api` to `http://127.0.0.1:8000`. The development UI uses port 5173.

From this folder, you can also build or check the frontend:

```powershell
npm run build
npm run lint
npm test
```
