import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: parseInt(process.env.PORT || "3000"),
    host: true,
    strictPort: true,
    // Proxy API calls to backend
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      "/external": {
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
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      "/external": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});

