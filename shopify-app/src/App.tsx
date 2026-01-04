import React from "react";
import { AppProvider, Page, Layout, Tabs } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";
import { StrategyCalendar } from "./components/StrategyCalendar";

/**
 * Main Shopify App component.
 * This is the entry point for the embedded app.
 */
function App() {
  const [selectedTab, setSelectedTab] = React.useState(0);

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

  return (
    <AppProvider
      i18n={{
        Polaris: {
          Avatar: {
            label: "Avatar",
            labelWithInitials: "Avatar with initials {initials}",
          },
          ContextualSaveBar: {
            save: "Save",
            discard: "Discard",
          },
          TextField: {
            characterCount: "{count} characters",
          },
          TopBar: {
            toggleMenuLabel: "Toggle menu",
            SearchField: {
              clearButtonLabel: "Clear",
              search: "Search",
            },
          },
          Modal: {
            i18n: {
              close: "Close",
            },
          },
          Frame: {
            skipToContent: "Skip to content",
            navigationLabel: "Navigation",
            Navigation: {
              closeMobileNavigationLabel: "Close navigation",
            },
          },
        },
      }}
    >
      <Page title="Hipoink ESL Pricing Strategies" fullWidth>
        <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
          <Layout>
            <Layout.Section>
              {selectedTab === 0 && <StrategyCalendar />}
              {selectedTab === 1 && (
                <div>
                  <p>Strategy management coming soon...</p>
                </div>
              )}
            </Layout.Section>
          </Layout>
        </Tabs>
      </Page>
    </AppProvider>
  );
}

export default App;
