import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Page, Layout, Card, FormLayout, TextField, Button, Banner, Select, } from "@shopify/polaris";
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
export function Onboarding({ shop }) {
    const [hipoinkStoreCode, setHipoinkStoreCode] = useState("");
    const [timezone, setTimezone] = useState("UTC");
    const [storeName, setStoreName] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(false);
    const handleSubmit = async () => {
        if (!hipoinkStoreCode.trim()) {
            setError("Hipoink store code is required");
            return;
        }
        setIsSubmitting(true);
        setError(null);
        try {
            // First, get the current store mapping
            const mappingResponse = await fetch(`/api/store-mappings/current?shop=${encodeURIComponent(shop)}`);
            let mappingId;
            if (mappingResponse.ok) {
                // Update existing mapping (created by OAuth callback)
                const mapping = await mappingResponse.json();
                mappingId = mapping.id;
                // Get existing metadata and merge with new data
                const existingMetadata = mapping.metadata || {};
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
                    throw new Error(errorData.detail ||
                        "Failed to update store mapping. Please try again.");
                }
            }
            else {
                // Create new mapping (OAuth callback didn't create one)
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
                    throw new Error(errorData.detail ||
                        "Failed to create store mapping. Please try again.");
                }
                const created = await createResponse.json();
                mappingId = created.id;
            }
            setSuccess(true);
            setError(null);
            // Reload page after a short delay to refresh auth state
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        }
        catch (err) {
            const errorMessage = err instanceof Error ? err.message : "An unexpected error occurred";
            setError(errorMessage);
            console.error("Onboarding error", err);
        }
        finally {
            setIsSubmitting(false);
        }
    };
    return (_jsx(Page, { title: "Welcome to Hipoink ESL Integration", primaryAction: null, children: _jsx(Layout, { children: _jsx(Layout.Section, { children: _jsx(Card, { children: _jsxs(FormLayout, { children: [error && (_jsx(Banner, { tone: "critical", onDismiss: () => setError(null), children: error })), success && (_jsx(Banner, { tone: "success", children: "Setup complete! Redirecting..." })), _jsx(TextField, { label: "Hipoink Store Code", value: hipoinkStoreCode, onChange: setHipoinkStoreCode, placeholder: "e.g., 001", helpText: "The store code used in your Hipoink ESL system", autoComplete: "off" }), _jsx(TextField, { label: "Store Name (Optional)", value: storeName, onChange: setStoreName, placeholder: shop, helpText: "A friendly name for this store", autoComplete: "off" }), _jsx(Select, { label: "Store Timezone", options: TIMEZONES, value: timezone, onChange: setTimezone, helpText: "Select the timezone for this store. Price schedules will use this timezone." }), _jsx(Button, { variant: "primary", loading: isSubmitting, onClick: handleSubmit, disabled: !hipoinkStoreCode.trim() || isSubmitting, children: "Complete Setup" })] }) }) }) }) }));
}
