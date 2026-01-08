import { useEffect, useState } from "react";
import { useAppBridge } from "@shopify/app-bridge-react";
export function useShopifyAuth() {
    const app = useAppBridge();
    const [authState, setAuthState] = useState({
        shop: null,
        isLoading: true,
        isAuthenticated: false,
        needsOnboarding: false,
        storeMappingId: null,
        timezone: null,
    });
    useEffect(() => {
        async function fetchAuthState() {
            try {
                // Get shop from URL parameters (Shopify always includes this in embedded apps)
                const urlParams = new URLSearchParams(window.location.search);
                let shop = urlParams.get("shop");
                // If not in URL, try to extract from App Bridge host parameter
                if (!shop) {
                    const host = urlParams.get("host");
                    if (host) {
                        try {
                            // Host is base64 encoded, decode it to get shop domain
                            const decoded = atob(host);
                            // Extract shop from decoded host (format: "shop.myshopify.com/admin")
                            const match = decoded.match(/([a-zA-Z0-9-]+\.myshopify\.com)/);
                            if (match) {
                                shop = match[1];
                            }
                        }
                        catch (e) {
                            // If decoding fails, try window.shop as fallback
                            shop = window.shop;
                        }
                    }
                    else {
                        shop = window.shop;
                    }
                }
                if (!shop) {
                    setAuthState((prev) => ({ ...prev, isLoading: false }));
                    return;
                }
                // Fetch auth state from backend
                const response = await fetch(`/api/auth/me?shop=${encodeURIComponent(shop)}`);
                if (!response.ok) {
                    throw new Error("Failed to fetch auth state");
                }
                const data = await response.json();
                setAuthState({
                    shop: data.shop,
                    isLoading: false,
                    isAuthenticated: data.is_authenticated || false,
                    needsOnboarding: data.needs_onboarding || false,
                    storeMappingId: data.store_mapping?.id || null,
                    timezone: data.store_mapping?.timezone || null,
                });
            }
            catch (error) {
                console.error("Error fetching auth state:", error);
                setAuthState((prev) => ({ ...prev, isLoading: false }));
            }
        }
        fetchAuthState();
    }, []);
    return authState;
}
