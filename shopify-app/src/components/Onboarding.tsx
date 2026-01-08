import React, { useState } from "react";
import {
  Page,
  Layout,
  Card,
  FormLayout,
  TextField,
  Button,
  Banner,
  Select,
} from "@shopify/polaris";

interface OnboardingProps {
  shop: string;
}

const TIMEZONES = [
  { label: "Select timezone...", value: "" },
  { label: "UTC", value: "UTC" },
  { label: "America/New_York (Eastern)", value: "America/New_York" },
  { label: "America/Chicago (Central)", value: "America/Chicago" },
  { label: "America/Denver (Mountain)", value: "America/Denver" },
  { label: "America/Los_Angeles (Pacific)", value: "America/Los_Angeles" },
  { label: "Europe/London (GMT)", value: "Europe/London" },
  { label: "Europe/Paris (CET)", value: "Europe/Paris" },
  { label: "Asia/Tokyo (JST)", value: "Asia/Tokyo" },
  { label: "Asia/Shanghai (CST)", value: "Asia/Shanghai" },
  { label: "Australia/Sydney (AEDT)", value: "Australia/Sydney" },
];

export function Onboarding({ shop }: OnboardingProps) {
  const [hipoinkStoreCode, setHipoinkStoreCode] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [storeName, setStoreName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [existingMappingId, setExistingMappingId] = useState<string | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(true);

  // Load existing store mapping on mount
  React.useEffect(() => {
    async function loadExistingMapping() {
      try {
        const response = await fetch(
          `/api/store-mappings/current?shop=${encodeURIComponent(shop)}`
        );

        if (response.ok) {
          const mapping = await response.json();
          setExistingMappingId(mapping.id);

          // Pre-populate form with existing data
          if (mapping.hipoink_store_code) {
            setHipoinkStoreCode(mapping.hipoink_store_code);
          }
          if (mapping.metadata?.timezone) {
            setTimezone(mapping.metadata.timezone);
          }
          if (mapping.metadata?.store_name) {
            setStoreName(mapping.metadata.store_name);
          } else if (mapping.source_store_id) {
            setStoreName(mapping.source_store_id);
          }
        }
      } catch (err) {
        console.error("Error loading existing mapping:", err);
        // Continue with empty form if fetch fails
      } finally {
        setIsLoading(false);
      }
    }

    loadExistingMapping();
  }, [shop]);

  const handleSubmit = async () => {
    if (!hipoinkStoreCode.trim()) {
      setError("Hipoink store code is required");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // Use existing mapping ID if we have it, otherwise try to fetch
      let mappingId = existingMappingId;
      let existingMetadata: any = {};

      if (!mappingId) {
        // Try to fetch existing mapping, but handle 422/404 gracefully
        try {
          const mappingResponse = await fetch(
            `/api/store-mappings/current?shop=${encodeURIComponent(shop)}`
          );

          if (mappingResponse.ok) {
            const mapping = await mappingResponse.json();
            mappingId = mapping.id;
            existingMetadata = mapping.metadata || {};
          }
          // If 404 or 422, mapping doesn't exist or can't be fetched - will try create
        } catch (e) {
          // Continue to create path if fetch fails
          console.log("Could not fetch existing mapping, will try create");
        }
      } else {
        // Fetch existing metadata if we already have the ID
        try {
          const mappingResponse = await fetch(
            `/api/store-mappings/current?shop=${encodeURIComponent(shop)}`
          );
          if (mappingResponse.ok) {
            const mapping = await mappingResponse.json();
            existingMetadata = mapping.metadata || {};
          }
        } catch (e) {
          // Continue with empty metadata if fetch fails
        }
      }

      if (mappingId) {
        // Update existing mapping
        const updateResponse = await fetch(`/api/store-mappings/${mappingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_system: "shopify",
            source_store_id: shop,
            hipoink_store_code: hipoinkStoreCode.trim(),
            is_active: true,
            metadata: {
              ...existingMetadata, // Preserve existing metadata (like OAuth token)
              timezone: timezone,
              shopify_shop_domain: shop,
              store_name: storeName.trim() || shop,
            },
          }),
        });

        if (!updateResponse.ok) {
          const errorData = await updateResponse.json().catch(() => ({}));
          throw new Error(
            errorData.detail ||
              "Failed to update store mapping. Please try again."
          );
        }
      } else {
        // Create new mapping only if one doesn't exist
        const createResponse = await fetch("/api/store-mappings/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_system: "shopify",
            source_store_id: shop,
            hipoink_store_code: hipoinkStoreCode.trim(),
            is_active: true,
            metadata: {
              timezone: timezone,
              shopify_shop_domain: shop,
              store_name: storeName.trim() || shop,
            },
          }),
        });

        if (!createResponse.ok) {
          const errorData = await createResponse.json().catch(() => ({}));
          // If 409 Conflict (already exists), use list endpoint to find and update
          if (
            createResponse.status === 409 ||
            (errorData.detail && errorData.detail.includes("already exists"))
          ) {
            // List all Shopify mappings and find the one for this shop
            const listResponse = await fetch(
              `/api/store-mappings/?source_system=shopify`
            );

            if (!listResponse.ok) {
              throw new Error(
                "Store mapping already exists but could not be retrieved. Please refresh the page."
              );
            }

            const mappings = await listResponse.json();
            const existing = mappings.find(
              (m: any) => m.source_store_id === shop
            );

            if (!existing) {
              throw new Error(
                "Store mapping already exists but could not be found. Please refresh the page."
              );
            }

            // Update the existing mapping
            const updateResponse = await fetch(
              `/api/store-mappings/${existing.id}`,
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  source_system: "shopify",
                  source_store_id: shop,
                  hipoink_store_code: hipoinkStoreCode.trim(),
                  is_active: true,
                  metadata: {
                    ...(existing.metadata || {}),
                    timezone: timezone,
                    shopify_shop_domain: shop,
                    store_name: storeName.trim() || shop,
                  },
                }),
              }
            );

            if (!updateResponse.ok) {
              const updateError = await updateResponse.json().catch(() => ({}));
              throw new Error(
                updateError.detail ||
                  "Failed to update existing store mapping. Please try again."
              );
            }
          } else {
            throw new Error(
              errorData.detail ||
                "Failed to create store mapping. Please try again."
            );
          }
        }
      }

      setSuccess(true);
      setError(null);
      // Reload page after a short delay to refresh auth state
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "An unexpected error occurred";
      setError(errorMessage);
      console.error("Onboarding error", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <Page title="Welcome to Hipoink ESL Integration" primaryAction={null}>
        <Layout>
          <Layout.Section>
            <Card>
              <p>Loading existing configuration...</p>
            </Card>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  return (
    <Page title="Welcome to Hipoink ESL Integration" primaryAction={null}>
      <Layout>
        <Layout.Section>
          <Card>
            <FormLayout>
              {error && (
                <Banner tone="critical" onDismiss={() => setError(null)}>
                  {error}
                </Banner>
              )}

              {success && (
                <Banner tone="success">Setup complete! Redirecting...</Banner>
              )}

              <TextField
                label="Hipoink Store Code"
                value={hipoinkStoreCode}
                onChange={setHipoinkStoreCode}
                placeholder="e.g., 001"
                helpText="The store code used in your Hipoink ESL system"
                autoComplete="off"
              />

              <TextField
                label="Store Name (Optional)"
                value={storeName}
                onChange={setStoreName}
                placeholder={shop}
                helpText="A friendly name for this store"
                autoComplete="off"
              />

              <Select
                label="Store Timezone"
                options={TIMEZONES}
                value={timezone}
                onChange={setTimezone}
                helpText="Select the timezone for this store. Price schedules will use this timezone."
              />

              <Button
                variant="primary"
                loading={isSubmitting}
                onClick={handleSubmit}
                disabled={!hipoinkStoreCode.trim() || isSubmitting}
              >
                Complete Setup
              </Button>
            </FormLayout>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
