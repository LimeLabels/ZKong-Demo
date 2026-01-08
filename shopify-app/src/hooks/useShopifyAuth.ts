import { useEffect, useState } from "react";
import { useAppBridge } from "@shopify/app-bridge-react";

interface AuthState {
  shop: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  needsOnboarding: boolean;
  storeMappingId: string | null;
  timezone: string | null;
}

export function useShopifyAuth(): AuthState {
  const app = useAppBridge();
  const [authState, setAuthState] = useState<AuthState>({
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
        // Get shop from URL or App Bridge
        const urlParams = new URLSearchParams(window.location.search);
        const shop = urlParams.get("shop") || (window as any).shop;

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
      } catch (error) {
        console.error("Error fetching auth state:", error);
        setAuthState((prev) => ({ ...prev, isLoading: false }));
      }
    }

    fetchAuthState();
  }, []);

  return authState;
}
