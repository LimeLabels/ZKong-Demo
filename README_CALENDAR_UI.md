# Calendar UI System - Setup & Usage

## Overview

The system previously included two calendar interfaces:
1. **Shopify Embedded App** - Native Shopify UI for Shopify stores
2. **Centralized Dashboard** - Web dashboard for all other integrations

Both interfaces connected to the backend API at `/api/strategies/create`.

## Architecture (Historical)

```
┌─────────────────────┐         ┌──────────────────────┐
│  Shopify App        │         │  Centralized         │
│  (Polaris UI)       │         │  Dashboard           │
│                     │         │  (Next.js)           │
└──────────┬──────────┘         └──────────┬───────────┘
           │                                │
           └────────────┬───────────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │  FastAPI Backend       │
           │  /api/strategies/*     │
           └──────────┬─────────────┘
                      │
                      ▼
           ┌────────────────────────┐
           │  Hipoink ESL API       │
           │  (Feature not available)│
           └────────────────────────┘
```

## Current Status

- ❌ Strategy API endpoints removed
- ❌ Calendar UI components disabled
- ✅ Product sync to Hipoink is available
- ✅ Store mappings are available

For product synchronization, see the main README.md.
