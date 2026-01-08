import { jsx as _jsx } from "react/jsx-runtime";
import React from "react";
import ReactDOM from "react-dom/client";
import { Provider as AppBridgeProvider } from "@shopify/app-bridge-react";
import { AppProvider } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";
import App from "./App";
// Minimal i18n for Polaris (can be expanded later)
const i18n = {};
// Get config from URL or environment
// API key from environment (VITE_SHOPIFY_API_KEY or SHOPIFY_API_KEY) or fallback to current Client ID
const apiKey = import.meta.env.VITE_SHOPIFY_API_KEY
const config = {
    apiKey,
    host: new URLSearchParams(window.location.search).get("host") || "",
    forceRedirect: true,
};
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(_jsx(React.StrictMode, { children: _jsx(AppBridgeProvider, { config: config, children: _jsx(AppProvider, { i18n: i18n, children: _jsx(App, {}) }) }) }));
