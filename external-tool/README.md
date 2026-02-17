## External Time-Based Pricing Tool

### What Is This?

The External Time-Based Pricing Tool is a **React-based admin UI** for managing time-based pricing schedules and testing webhook integrations for NCR and Square. It is the primary operational interface for anyone configuring, monitoring, or debugging time-based pricing behavior.

It sits on top of the core middleware and communicates exclusively with the FastAPI backend — it never talks directly to Hipoink, Supabase, NCR, or Square. Think of it as the control panel for the pricing engine.

> For a full explanation of how time-based pricing works end to end, see `docs/TIME_BASED_PRICING.md`.  
> For how the backend workers process schedules, see `app/workers/README.md`.

---

### What Does It Do?

| Screen | What It's For |
|---|---|
| **Dashboard** | High-level overview of active schedules, webhook health, and quick action shortcuts |
| **Schedule Manager** | View, create, and manage time-based pricing schedules |
| **Webhook Tester** | Manually trigger and test NCR and Square webhook endpoints |
| **Health Check** | Monitor the live health status of webhook endpoints |
| **Settings** | Configure the backend URL and authentication token |

---

### How It Fits Into the System

```text
External Tool (React UI)
        ↓
FastAPI Backend (via Axios HTTP calls)
        ↓
Supabase (price_adjustment_schedules, store_mappings, products)
        ↓
Background Workers (PriceScheduler, SyncWorker)
        ↓
BOS systems (NCR, Square) + Hipoink ESL labels
```

The tool never bypasses the backend. All reads and writes go through the backend API, which enforces business logic, authentication, and multi-tenant isolation.

---

### API Endpoints Used

| Method | Endpoint | What It Does |
|---|---|---|
| `GET` | `/api/price-adjustments/` | List all pricing schedules |
| `GET` | `/external/health` | Check backend/webhook health |
| `POST` | `/external/ncr/trigger-price-update` | Manually trigger an NCR price update |
| `POST` | `/external/square/trigger-price-update` | Manually trigger a Square price update |
| `POST` | `/external/trigger-schedule/{schedule_id}` | Manually fire a specific schedule immediately |

For how these endpoints connect to the broader system:
- Schedule processing → `app/workers/README.md`
- NCR price handling → `app/integrations/ncr/README.md`
- Square price handling → `app/integrations/square/README.md`

---

### Tech Stack

| Technology | Role |
|---|---|
| **React 18** | UI framework |
| **TypeScript** | Type safety across all components |
| **Vite** | Build tool and dev server |
| **Shopify Polaris** | UI component library (kept consistent with the `shopify-app`) |
| **Axios** | HTTP client for backend API calls |
| **date-fns** | Date formatting and display |

---

### Project Structure

```
external-tool/
├── src/
│   ├── components/          # All UI screens
│   │   ├── Dashboard.tsx        # Overview screen
│   │   ├── ScheduleManager.tsx  # Schedule list and management
│   │   ├── WebhookTester.tsx    # Manual webhook trigger UI
│   │   ├── HealthCheck.tsx      # Endpoint health monitor
│   │   └── ConfigSettings.tsx   # Backend URL and auth config
│   ├── services/
│   │   └── api.ts               # All Axios API calls (single source of truth)
│   ├── App.tsx                  # Root component and routing
│   ├── main.tsx                # App entry point
│   └── index.css               # Global styles
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── README.md
```

All API communication is centralized in `services/api.ts` — components never make HTTP calls directly.

---

### Configuration

#### Backend URL
The tool needs to know where your FastAPI backend is running. Set this in one of two ways:
- **Environment variable:** `VITE_BACKEND_URL=http://localhost:8000`
- **Settings page in the UI** — the URL is saved in `localStorage` so it persists across sessions

#### Authentication Token
Some endpoints require a Bearer token. Set this via the Settings page in the UI. It will be attached automatically to all authenticated requests as `Authorization: Bearer <token>`.

---

### Development Setup

#### Prerequisites
- Node.js 18+ and npm
- FastAPI backend running locally (default: `http://localhost:8000`)

#### Steps

```bash
# From the external-tool/ directory
npm install

# Optional: set backend URL
export VITE_BACKEND_URL=http://localhost:8000

# Start dev server
npm run dev
```

App will be available at `http://localhost:3000`.

#### Available Scripts

| Script | What It Does |
|---|---|
| `npm run dev` | Start local development server with hot reload |
| `npm run build` | Compile TypeScript and build production bundle (output to `dist/`) |
| `npm run typecheck` | Run TypeScript type checker without emitting files |
| `npm run lint` | Run ESLint across all `.ts` and `.tsx` files |

---

### Deploying to Railway

1. Connect the repository to Railway and set the root directory to `external-tool`
2. Railway will automatically detect the Node.js app and run `npm install` + `npm run build`
3. Set environment variables in the Railway dashboard:
   - `VITE_BACKEND_URL` — your deployed FastAPI backend URL (e.g. `https://your-backend.up.railway.app`)
   - `PORT` — set automatically by Railway
4. The app runs in production using `vite preview` (defined in the `start` script in `package.json`)

---

### Troubleshooting

| Problem | What To Check |
|---|---|
| Can't connect to backend | Confirm `VITE_BACKEND_URL` is set correctly, or update it via the Settings page |
| Webhook trigger returns error | Check the backend logs for the specific endpoint. Confirm the store mapping exists for that integration |
| Health check shows unhealthy | The backend may be down, or the specific integration endpoint has a configuration issue |
| Schedules not appearing | Confirm the backend is running and `GET /api/price-adjustments/` returns data |
