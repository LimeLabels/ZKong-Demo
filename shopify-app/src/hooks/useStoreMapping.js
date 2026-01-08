import { useEffect, useState } from "react";
import { useShopifyAuth } from "./useShopifyAuth";
export function useStoreMapping() {
    const auth = useShopifyAuth();
    const [storeMapping, setStoreMapping] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    useEffect(() => {
        async function fetchStoreMapping() {
            if (!auth.shop || auth.isLoading) {
                return;
            }
            setIsLoading(true);
            setError(null);
            try {
                const response = await fetch(`/api/store-mappings/current?shop=${encodeURIComponent(auth.shop)}`);
                if (!response.ok) {
                    if (response.status === 404) {
                        // Store mapping not found - needs onboarding
                        setStoreMapping(null);
                        setIsLoading(false);
                        return;
                    }
                    throw new Error("Failed to fetch store mapping");
                }
                const data = await response.json();
                setStoreMapping({
                    id: data.id,
                    hipoink_store_code: data.hipoink_store_code,
                    timezone: data.metadata?.timezone || null,
                });
            }
            catch (err) {
                console.error("Error fetching store mapping:", err);
                setError(err instanceof Error ? err.message : "Unknown error");
            }
            finally {
                setIsLoading(false);
            }
        }
        fetchStoreMapping();
    }, [auth.shop, auth.isLoading]);
    return { storeMapping, isLoading, error };
}
