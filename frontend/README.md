## Frontend – Onboarding App

### Overview

The `frontend/` application is a Next.js frontend that handles merchant onboarding
for POS integrations, with a focus on Square and Clover. It is responsible for:

- Providing a guided onboarding experience for merchants.
- Initiating OAuth flows against the backend (`/auth/...` routes).
- Displaying success/confirmation pages after onboarding completes.

The app does not talk directly to Hipoink or Supabase; it interacts with the
FastAPI backend, which then handles all data persistence and ESL sync logic.

### Tech stack

- **Next.js 14** – React framework for server‑side and client‑side rendering.
- **React 18** – UI library.
- **TypeScript** – Type‑safe components and pages.

See `package.json` for dependency versions and scripts.

### Structure

Key files and directories:

```text
frontend/
├── Procfile              # Railway start command (npm start)
├── RAILWAY_DEPLOY.md     # Detailed Railway deployment guide (Square onboarding)
├── next.config.js        # Next.js configuration
├── tsconfig.json         # TypeScript configuration
├── package.json          # Scripts and dependencies
├── pages/
│   └── onboarding/       # Onboarding flows and landing pages
│       ├── index.tsx     # Onboarding entry/chooser
│       ├── choose.module.css
│       ├── square/       # Square onboarding flow
│       │   ├── square.tsx
│       │   ├── square.module.css
│       │   ├── success.tsx
│       │   └── success.module.css
│       └── clover/       # Clover onboarding flow
│           ├── clover.tsx
│           ├── clover.module.css
│           ├── success.tsx
│           └── success.module.css
└── ...
```

The onboarding pages are tightly coupled to backend OAuth endpoints:

- Square: `app/routers/square_auth.py`
- Clover: `app/routers/clover_auth.py`

### Environment configuration

The app expects configuration via environment variables, typically set in Railway:

- `NEXT_PUBLIC_BACKEND_URL` – Public URL of the FastAPI backend
  (e.g. `https://your-backend.up.railway.app`).
- `NEXT_PUBLIC_ESL_DASHBOARD_LINK` – Link to the external ESL dashboard (optional).
- `NODE_ENV` – Environment (`development` / `production`).
- `PORT` – Port for the Next.js server (Railway sets this automatically).

These variables are documented for deployment in `RAILWAY_DEPLOY.md`. At runtime,
pages read `NEXT_PUBLIC_*` variables via `process.env` to know where to send
backend requests and where to link merchants for ESL access.

### Development

#### Prerequisites

- Node.js 18+ and npm.
- Backend FastAPI service running locally (default `http://localhost:8000`) or
  accessible over the network.

#### Setup

From the `frontend/` directory:

```bash
npm install
```

To start the development server:

```bash
npm run dev
```

The app will be available at `http://localhost:3000` by default.

### Deployment

Deployment to Railway is documented in detail in `RAILWAY_DEPLOY.md`. In summary:

- Root directory for the Railway service: `frontend`.
- Railway will:
  - Install dependencies.
  - Build the Next.js app (`npm run build`).
  - Start the production server with `npm start`.
- After deployment, configure the backend’s `FRONTEND_URL` environment variable to
  point at the deployed frontend URL so OAuth redirects are correct.

For step‑by‑step instructions, troubleshooting tips, and a diagram of the frontend
structure, refer to `RAILWAY_DEPLOY.md`.

### Extending onboarding flows

When adding a new onboarding flow (for another integration or a future feature):

- Add pages under `pages/onboarding/<integration>/...`.
- Keep styling consistent with existing onboarding pages.
- Wire the new frontend flow to corresponding backend OAuth or setup routes under
  `app/routers/*_auth.py` or other dedicated routers.
- Avoid direct calls to Hipoink or Supabase from the frontend; always go through
  the backend API.

