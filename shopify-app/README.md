# Hipoink ESL Shopify App

Shopify embedded app for managing time-based pricing strategies on Hipoink ESL displays.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Configure Shopify app credentials in `.env`:
```
SHOPIFY_API_KEY=your_api_key
SHOPIFY_API_SECRET=your_api_secret
SHOPIFY_SCOPES=read_products,write_products
BACKEND_API_URL=https://your-backend-url.com
```

3. Run development server:
```bash
npm run dev
```

## Features

- Create time-based pricing strategies
- Calendar view for scheduling
- Product selector
- Strategy management

