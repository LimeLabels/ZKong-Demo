import { jsx as _jsx } from "react/jsx-runtime";
import React from "react";
import ReactDOM from "react-dom/client";
import { Provider } from "@shopify/app-bridge-react";
import App from "./App";
// Get config from URL or environment
const config = {
    apiKey: import.meta.env.VITE_SHOPIFY_API_KEY || "f14db8a0845e4b2026facc6594c3e741",
    host: new URLSearchParams(window.location.search).get("host") || "",
    forceRedirect: true,
};
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(_jsx(React.StrictMode, { children: _jsx(Provider, { config: config, children: _jsx(App, {}) }) }));
