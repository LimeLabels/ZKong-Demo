## Frontend — Onboarding App

### What Is This?

The `frontend/` app is a **Next.js application** that guides merchants through the onboarding process for connecting their POS system (Square or Clover) to the Hipoink ESL middleware.

It is the first thing a merchant interacts with when setting up the system. It collects their store details, initiates the OAuth connection to their POS, and confirms when onboarding is complete.

The app does not talk directly to Hipoink, Supabase, NCR, or Square. Everything goes through the FastAPI backend, which handles all data persistence, OAuth token exchange, and ESL sync logic.

---

### What Does It Do?

| Page | What It's For |
|---|---|
| `/onboarding` | Entry point — merchant chooses which integration to connect |
| `/onboarding/square` | Square-specific onboarding form and OAuth initiation |
| `/onboarding/square/success` | Confirmation page shown after Square OAuth completes |
| `/onboarding/clover` | Clover-specific onboarding form and OAuth initiation |
| `/onboarding/clover/success` | Confirmation page shown after Clover OAuth completes |

---

### How It Fits Into the System

```text
Merchant opens onboarding app (frontend/)
        ↓
Fills in store details (name, timezone, Hipoink store code)
        ↓
Clicks "Connect to Square / Clover"
        ↓
Frontend redirects to backend OAuth route:
  Square: /auth/square
  Clover: /auth/clover
        ↓
Backend initiates OAuth with the POS provider
        ↓
Merchant authorizes in Square / Clover
        ↓
POS redirects back to backend callback:
  Square: /auth/square/callback
  Clover: /auth/clover/callback
        ↓
Backend exchanges code for tokens, creates StoreMapping in Supabase,
triggers initial product sync in background
        ↓
Backend redirects merchant to success page in frontend
        ↓
Merchant sees confirmation — onboarding complete
```

---

### Tech Stack

| Technology | Role |
|---|---|
| **Next.js 14** | React framework handling both server-side and client-side rendering |
| **React 18** | UI library |
| **TypeScript** | Type-safe components and pages |

See `package.json` for full dependency list and version details.

---

### Project Structure

```
frontend/
├── Procfile                  # Railway start command (npm start)
├── RAILWAY_DEPLOY.md         # Step-by-step Railway deployment guide
├── next.config.js            # Next.js configuration
├── tsconfig.json             # TypeScript configuration
├── package.json              # Scripts and dependencies
└── pages/
    └── onboarding/
        ├── index.tsx             # Entry page — integration chooser
        ├── choose.module.css
        ├── square/
        │   ├── square.tsx        # Square onboarding form
        │   ├── square.module.css
        │   ├── success.tsx       # Square post-OAuth confirmation
        │   └── success.module.css
        └── clover/
            ├── clover.tsx        # Clover onboarding form
            ├── clover.module.css
            ├── success.tsx       # Clover post-OAuth confirmation
            └── success.module.css
```

The onboarding pages are tightly coupled to the backend OAuth routers:
- Square pages → `app/routers/square_auth.py`
- Clover pages → `app/routers/clover_auth.py`

---

### Configuration

The app reads configuration from environment variables, set in Railway or locally in `.env.local`:

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | Yes | Public URL of the FastAPI backend (e.g. `https://your-backend.up.railway.app`) |
| `NEXT_PUBLIC_ESL_DASHBOARD_LINK` | Optional | Link to the external ESL dashboard shown on success pages |
| `NODE_ENV` | Auto | `development` or `production` |
| `PORT` | Auto (Railway) | Port for the Next.js server |

Pages read `NEXT_PUBLIC_*` variables via `process.env` at runtime. Without `NEXT_PUBLIC_BACKEND_URL`, OAuth redirects will not work.

---

### Development Setup

#### Prerequisites
- Node.js 18+ and npm
- FastAPI backend running locally (default: `http://localhost:8000`) or accessible over the network

#### Steps

```bash
# From the frontend/ directory
npm install

# Start dev server
npm run dev
```

App will be available at `http://localhost:3000`.

#### Available Scripts

| Script | What It Does |
|---|---|
| `npm run dev` | Start local development server with hot reload |
| `npm run build` | Build optimized production bundle |
| `npm start` | Start the production Next.js server |
| `npm run lint` | Run ESLint across the project |
| `npm run typecheck` | Run TypeScript type checker |

---

### Deploying to Railway

Full step-by-step instructions are in `RAILWAY_DEPLOY.md`. Summary:

1. Set the Railway service root directory to `frontend`
2. Railway will automatically run `npm install`, `npm run build`, and `npm start`
3. Set environment variables in Railway dashboard:
   - `NEXT_PUBLIC_BACKEND_URL` — your deployed FastAPI backend URL
4. After deploying, set the backend's `FRONTEND_URL` environment variable to point at this deployed frontend URL so OAuth callbacks redirect correctly

---

### Extending Onboarding Flows

When adding a new integration or onboarding variant (e.g. a BOS-only flow):

1. Add pages under `pages/onboarding/<integration>/` following the existing Square/Clover pattern
2. Keep styling consistent with existing pages using CSS modules
3. Wire the frontend flow to the corresponding backend OAuth or setup route in `app/routers/*_auth.py`
4. Create a `success.tsx` page for the post-OAuth confirmation screen

#### Important Rules
- **Never** call Hipoink, Supabase, NCR, or Square directly from the frontend
- Always go through the FastAPI backend API
- Keep all `NEXT_PUBLIC_*` variables documented in this README and in `RAILWAY_DEPLOY.md`

---

### Troubleshooting

| Problem | What To Check |
|---|---|
| OAuth redirect fails after connect | Confirm `NEXT_PUBLIC_BACKEND_URL` is set and the backend is accessible. Check that the backend's `FRONTEND_URL` env variable points to this app |
| Blank page or 404 on success page | Confirm the backend is redirecting to the correct frontend URL after OAuth callback |
| TypeScript errors on build | Run `npm run typecheck` locally to catch issues before deploying |
| Railway build failing | Check `RAILWAY_DEPLOY.md` for known deployment gotchas and configuration steps |
