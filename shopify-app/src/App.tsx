import React, { useState, useEffect } from "react";
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
    return (
      <Page title="Hipoink ESL Pricing Strategies" fullWidth>
        <Layout>
          <Layout.Section>
            <Spinner accessibilityLabel="Loading" size="large" />
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  // Show onboarding if needed
  if (auth.needsOnboarding) {
    return <Onboarding shop={auth.shop || ""} />;
  }

  // Show authentication required message
  if (!auth.isAuthenticated) {
    const handleReAuthenticate = () => {
      // Get shop domain
      const shop =
        auth.shop || new URLSearchParams(window.location.search).get("shop");

      if (shop) {
        // Redirect to OAuth endpoint
        // Use window.top to break out of iframe and redirect parent window
        try {
          const oauthUrl = `/auth/shopify?shop=${encodeURIComponent(shop)}`;
          // Try to break out of iframe first
          if (window.top && window.top !== window.self) {
            window.top.location.href = oauthUrl;
          } else {
            window.location.href = oauthUrl;
          }
        } catch (e) {
          // If cross-origin, fall back to current window
          window.location.href = `/auth/shopify?shop=${encodeURIComponent(
            shop
          )}`;
        }
      } else {
        alert(
          "Unable to determine shop domain. Please re-install the app from Shopify Admin."
        );
      }
    };

    return (
      <Page title="Hipoink ESL Pricing Strategies" fullWidth>
        <Layout>
          <Layout.Section>
            <Banner tone="critical" title="Authentication Required">
              <p>
                The app needs to be authenticated with Shopify. This usually
                happens automatically during installation.
              </p>
              <p style={{ marginTop: "1rem" }}>
                <Button variant="primary" onClick={handleReAuthenticate}>
                  Re-authenticate with Shopify
                </Button>
              </p>
            </Banner>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  return (
    <Page title="Hipoink ESL Pricing Strategies" fullWidth>
      <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
        <Layout>
          <Layout.Section>
            {selectedTab === 0 && <StrategyCalendar />}
            {selectedTab === 1 && <StrategyList />}
          </Layout.Section>
        </Layout>
      </Tabs>
    </Page>
  );
}

export default App;
