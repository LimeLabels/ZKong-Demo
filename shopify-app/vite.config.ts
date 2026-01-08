import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: parseInt(process.env.PORT || "3000"),
    allowedHosts: ["shopify-app-production-e35f.up.railway.app"],
    host: true,
    strictPort: true,
    headers: {
      "Content-Security-Policy": "frame-ancestors 'self' https://admin.shopify.com https://*.myshopify.com https://admin.shopify.io;",
    },
    // Proxy API calls to FastAPI backend
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  preview: {
    port: parseInt(process.env.PORT || "3000"),
    host: true,
    strictPort: true,
    headers: {
      "Content-Security-Policy": "frame-ancestors 'self' https://admin.shopify.com https://*.myshopify.com https://admin.shopify.io;",
    },
    // Proxy API calls to FastAPI backend in preview mode
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});

