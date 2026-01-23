# Railway Deployment Guide for Frontend

## Prerequisites

1. Railway account
2. Backend service already deployed on Railway
3. Backend Railway URL (e.g., `https://your-backend.up.railway.app`)

## Deployment Steps

### 1. Create New Railway Service

1. Go to your Railway project dashboard
2. Click **"New"** → **"GitHub Repo"** (or **"Empty Project"** if deploying manually)
3. Select your repository
4. **Important**: Set **Root Directory** to `frontend`

### 2. Configure Environment Variables

In Railway service settings, add these environment variables:

```
NEXT_PUBLIC_BACKEND_URL=https://your-backend-service.up.railway.app
NEXT_PUBLIC_ESL_DASHBOARD_LINK=http://43.153.107.21/admin/auth/login
NODE_ENV=production
PORT=3000
```

**Replace `https://your-backend-service.up.railway.app` with your actual backend Railway URL.**

### 3. Build Configuration

Railway will automatically detect:
- **Procfile** → Uses `npm start`
- **nixpacks.toml** → Custom build configuration
- **package.json** → Dependencies and scripts

### 4. Deploy

Railway will:
1. Install dependencies (`npm ci`)
2. Build the Next.js app (`npm run build`)
3. Start the production server (`npm start`)

### 5. Get Your Frontend URL

After deployment, Railway will provide a URL like:
- `https://your-frontend.up.railway.app`

### 6. Update Backend Configuration

Update your backend's `FRONTEND_URL` environment variable to match your new frontend URL:

```
FRONTEND_URL=https://your-frontend.up.railway.app
```

This ensures OAuth callbacks redirect to the correct frontend URL.

## File Structure

```
frontend/
├── Procfile              # Railway start command
├── nixpacks.toml         # Railway build configuration
├── package.json          # Dependencies and scripts
├── next.config.js        # Next.js configuration
├── tsconfig.json         # TypeScript configuration
└── pages/
    └── onboarding/
        └── square/
            ├── square.tsx
            ├── square.module.css
            ├── success.tsx
            └── success.module.css
```

## Troubleshooting

### Build Fails

- Check that `NEXT_PUBLIC_BACKEND_URL` is set correctly
- Verify Node.js version (Railway uses Node 18.x from nixpacks.toml)

### Runtime Errors

- Check Railway logs for errors
- Verify all environment variables are set
- Ensure backend is accessible from frontend

### OAuth Redirect Issues

- Make sure `FRONTEND_URL` in backend matches frontend Railway URL
- Check that Square OAuth redirect URI includes the correct frontend URL

## Testing

After deployment, test the flow:

1. Visit: `https://your-frontend.up.railway.app/onboarding/square`
2. Fill out the form
3. Complete Square OAuth
4. Verify redirect to success page
