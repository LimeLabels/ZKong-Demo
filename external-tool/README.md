# External Time-Based Pricing Tool

A React-based UI for managing time-based pricing schedules and testing webhook endpoints for NCR and Square integrations.

This tool sits on top of the core middleware described in the root `README.md`:

- It provides a UI over `price_adjustments`, `store_mappings`, and related tables.
- It interacts only with the FastAPI backend (not directly with Hipoink or Supabase).
- It is the primary operational interface for configuring and monitoring
  time-based pricing behavior documented in `docs/TIME_BASED_PRICING.md`.

## Features

- **Dashboard**: Overview of schedules, webhook health, and quick actions
- **Schedule Manager**: View and manage time-based pricing schedules
- **Webhook Tester**: Test NCR and Square webhook endpoints
- **Health Check**: Monitor webhook endpoint health status
- **Settings**: Configure backend URL and authentication

## Development

### Prerequisites

- Node.js 18+ and npm
- Backend FastAPI service running (default: http://localhost:8000)

### Setup

1. Install dependencies:
```bash
npm install
```

2. Set environment variables (optional):
```bash
export VITE_BACKEND_URL=http://localhost:8000
```

3. Start development server:
```bash
npm run dev
```

The app will be available at http://localhost:3000

## Building for Production

```bash
npm run build
```

The built files will be in the `dist` directory.

## Deployment to Railway

1. Connect your repository to Railway
2. Railway will automatically detect the Node.js app
3. Set environment variables in Railway dashboard:
   - `VITE_BACKEND_URL`: Your FastAPI backend URL (e.g., https://your-backend.up.railway.app)
   - `PORT`: Railway will set this automatically
4. Deploy!

The app uses `vite preview` for production serving, which is configured in the `start` script.

## Configuration

### Backend URL

The app connects to the FastAPI backend. You can configure this:
- Via environment variable: `VITE_BACKEND_URL`
- Via Settings page in the UI (saved in localStorage)

### Authentication

For webhook testing, you can set an authorization token:
- Via Settings page in the UI
- The token will be used for Bearer authentication

## API Endpoints Used

- `GET /api/price-adjustments/` - List all schedules
- `GET /external/health` - Health check
- `POST /external/ncr/trigger-price-update` - Trigger NCR price update
- `POST /external/square/trigger-price-update` - Trigger Square price update
- `POST /external/trigger-schedule/{schedule_id}` - Manually trigger a schedule

For details on how these endpoints feed into workers and integrations, see:

- `app/workers/README.md` – workers and schedule processing.
- `app/integrations/ncr/README.md` – NCR price handling.
- `app/integrations/square/README.md` – Square price handling.

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Shopify Polaris** - UI component library (consistent with shopify-app)
- **Axios** - HTTP client
- **date-fns** - Date formatting

## Project Structure

```
external-tool/
├── src/
│   ├── components/      # React components
│   │   ├── Dashboard.tsx
│   │   ├── ScheduleManager.tsx
│   │   ├── WebhookTester.tsx
│   │   ├── HealthCheck.tsx
│   │   └── ConfigSettings.tsx
│   ├── services/        # API services
│   │   └── api.ts
│   ├── App.tsx          # Main app component
│   ├── main.tsx         # Entry point
│   └── index.css        # Global styles
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── README.md
```

## License

Same as parent project.

