import React, { useState, useEffect } from "react";
import { Page, Layout, Tabs, Spinner, Banner } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";
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
    return (
      <Page title="Hipoink ESL Pricing Strategies" fullWidth>
        <Layout>
          <Layout.Section>
            <Banner tone="critical" title="Authentication Required">
              <p>
                Please complete the OAuth installation process to use this app.
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
