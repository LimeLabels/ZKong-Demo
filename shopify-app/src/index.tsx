import React from "react";
import ReactDOM from "react-dom/client";
import { Provider as AppBridgeProvider } from "@shopify/app-bridge-react";
import { AppProvider } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";
import App from "./App";

// Minimal i18n for Polaris (can be expanded later)
const i18n = {} as any;

// Get config from URL or environment
// API key from environment (VITE_SHOPIFY_API_KEY or SHOPIFY_API_KEY) or fallback to current Client ID
const apiKey =
  import.meta.env.VITE_SHOPIFY_API_KEY

const config = {
  apiKey,
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
