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

// Get host parameter from URL (required by App Bridge)
// Shopify provides this when the app is embedded
const urlParams = new URLSearchParams(window.location.search);
let host = urlParams.get("host");

// If host is not in URL, try to get it from hash (some Shopify setups use hash)
if (!host) {
  const hashParams = new URLSearchParams(window.location.hash.substring(1));
  host = hashParams.get("host");
}

// If still no host, try window.__SHOPIFY_HOST__ (some legacy setups)
if (!host && (window as any).__SHOPIFY_HOST__) {
  host = (window as any).__SHOPIFY_HOST__;
}

if (!host) {
  console.error(
    "Shopify App Bridge requires 'host' parameter. " +
      "Make sure the app is loaded from Shopify Admin as an embedded app. " +
      "Current URL:",
    window.location.href
  );
}

const config = {
  apiKey: apiKey,
  host: host || "", // App Bridge will handle validation
  forceRedirect: true,
};

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

// If host is missing, show error message instead of crashing
// This usually means the app is being accessed directly instead of through Shopify Admin
if (!host) {
  const urlParams = new URLSearchParams(window.location.search);
  const shop = urlParams.get("shop");

  root.render(
    <div
      style={{
        padding: "2rem",
        fontFamily: "system-ui",
        maxWidth: "600px",
        margin: "0 auto",
      }}
    >
      <h1>App Must Be Opened from Shopify Admin</h1>
      <p>
        This app must be accessed through the Shopify Admin interface. The
        "host" parameter is only provided when Shopify loads the app as an
        embedded app.
      </p>
      {shop ? (
        <div style={{ marginTop: "1.5rem" }}>
          <p>
            <strong>To open the app:</strong>
          </p>
          <ol>
            <li>
              Go to your Shopify Admin:{" "}
              <a
                href={`https://admin.shopify.com/store/${shop.split(".")[0]}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Shopify Admin
              </a>
            </li>
            <li>Navigate to Apps → ESL System</li>
            <li>The app will load properly with all required parameters</li>
          </ol>
        </div>
      ) : (
        <div style={{ marginTop: "1.5rem" }}>
          <p>
            <strong>To open the app:</strong>
          </p>
          <ol>
            <li>Go to your Shopify Admin</li>
            <li>Navigate to Apps → ESL System</li>
            <li>The app will load properly with all required parameters</li>
          </ol>
        </div>
      )}
      <p style={{ marginTop: "1.5rem", color: "#666" }}>
        Current URL: {window.location.href}
      </p>
    </div>
  );
} else {
  root.render(
    <React.StrictMode>
      <AppBridgeProvider config={config}>
        <AppProvider i18n={i18n}>
          <App />
        </AppProvider>
      </AppBridgeProvider>
    </React.StrictMode>
  );
}
