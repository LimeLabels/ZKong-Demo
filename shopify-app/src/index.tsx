import React from "react";
import ReactDOM from "react-dom/client";
import { AppProvider } from "@shopify/app-bridge-react";
import App from "./App";

// Get config from URL or environment
const config = {
  apiKey: import.meta.env.VITE_SHOPIFY_API_KEY || "f14db8a0845e4b2026facc6594c3e741",
  host: new URLSearchParams(window.location.search).get("host") || "",
  forceRedirect: true,
};

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

root.render(
  <React.StrictMode>
    <AppProvider config={config}>
      <App />
    </AppProvider>
  </React.StrictMode>
);
