import React from "react";
import ReactDOM from "react-dom/client";
import { Provider as AppBridgeProvider } from "@shopify/app-bridge-react";
import { AppProvider } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";
import App from "./App";

// Minimal i18n for Polaris (can be expanded later)
const i18n = {} as any;

// Get config from URL or environment
// API key must be set via VITE_SHOPIFY_API_KEY environment variable
const apiKey = import.meta.env.VITE_SHOPIFY_API_KEY;

if (!apiKey) {
  throw new Error(
    "VITE_SHOPIFY_API_KEY environment variable is required. Please set it in your environment variables."
  );
}

const config = {
  apiKey: apiKey, // TypeScript now knows apiKey is string after the check
  host: new URLSearchParams(window.location.search).get("host") || "",
  forceRedirect: true,
};

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

root.render(
  <React.StrictMode>
    <AppBridgeProvider config={config}>
      <AppProvider i18n={i18n}>
        <App />
      </AppProvider>
    </AppBridgeProvider>
  </React.StrictMode>
);
