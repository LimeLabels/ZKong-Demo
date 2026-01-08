import { useEffect, useState } from "react";
import { useShopifyAuth } from "./useShopifyAuth";

interface StoreMapping {
  id: string;
  hipoink_store_code: string;
  timezone: string | null;
}

export function useStoreMapping() {
  const auth = useShopifyAuth();
  const [storeMapping, setStoreMapping] = useState<StoreMapping | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStoreMapping() {
      if (!auth.shop || auth.isLoading) {
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `/api/store-mappings/current?shop=${encodeURIComponent(auth.shop)}`
        );

        if (!response.ok) {
          if (response.status === 404 || response.status === 422) {
            // Store mapping not found or validation error - needs onboarding
            setStoreMapping(null);
            setIsLoading(false);
            return;
          }
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || "Failed to fetch store mapping"
          );
        }

        const data = await response.json();
        setStoreMapping({
          id: data.id,
          hipoink_store_code: data.hipoink_store_code,
          timezone: data.metadata?.timezone || null,
        });
      } catch (err) {
        console.error("Error fetching store mapping:", err);
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    }

    fetchStoreMapping();
  }, [auth.shop, auth.isLoading]);

  return { storeMapping, isLoading, error };
}
