import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Page, Layout, Tabs, Spinner, Banner, Button } from "@shopify/polaris";
import { StrategyCalendar } from "./components/StrategyCalendar";
import { StrategyList } from "./components/StrategyList";
import { useShopifyAuth } from "./hooks/useShopifyAuth";
import { Onboarding } from "./components/Onboarding";
/**
 * Main Shopify App component.
 * This is the entry point for the embedded app.
 */
function App() {
    const [selectedTab, setSelectedTab] = useState(0);
    const auth = useShopifyAuth();
    const tabs = [
        {
            id: "create",
            content: "Create Strategy",
            panelID: "create-panel",
        },
        {
            id: "manage",
            content: "Manage Strategies",
            panelID: "manage-panel",
        },
    ];
    // Show loading state
    if (auth.isLoading) {
        return (_jsx(Page, { title: "Hipoink ESL Pricing Strategies", fullWidth: true, children: _jsx(Layout, { children: _jsx(Layout.Section, { children: _jsx(Spinner, { accessibilityLabel: "Loading", size: "large" }) }) }) }));
    }
    // Show onboarding if needed
    if (auth.needsOnboarding) {
        return _jsx(Onboarding, { shop: auth.shop || "" });
    }
    // Show authentication required message
    if (!auth.isAuthenticated) {
        const handleReAuthenticate = () => {
            // Trigger OAuth flow
            const shop = auth.shop || new URLSearchParams(window.location.search).get("shop");
            if (shop) {
                window.location.href = `/auth/shopify?shop=${encodeURIComponent(shop)}`;
            }
            else {
                alert("Unable to determine shop domain. Please re-install the app from Shopify Admin.");
            }
        };
        return (_jsx(Page, { title: "Hipoink ESL Pricing Strategies", fullWidth: true, children: _jsx(Layout, { children: _jsx(Layout.Section, { children: _jsxs(Banner, { tone: "critical", title: "Authentication Required", children: [_jsx("p", { children: "The app needs to be authenticated with Shopify. This usually happens automatically during installation." }), _jsx("p", { style: { marginTop: "1rem" }, children: _jsx(Button, { variant: "primary", onClick: handleReAuthenticate, children: "Re-authenticate with Shopify" }) })] }) }) }) }));
    }
    return (_jsx(Page, { title: "Hipoink ESL Pricing Strategies", fullWidth: true, children: _jsx(Tabs, { tabs: tabs, selected: selectedTab, onSelect: setSelectedTab, children: _jsx(Layout, { children: _jsxs(Layout.Section, { children: [selectedTab === 0 && _jsx(StrategyCalendar, {}), selectedTab === 1 && _jsx(StrategyList, {})] }) }) }) }));
}
export default App;
