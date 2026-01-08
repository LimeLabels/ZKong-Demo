import React, { useState, useEffect } from "react";
import {
  Modal,
  TextField,
  ResourceList,
  ResourceItem,
  Thumbnail,
  Text,
  EmptyState,
  Spinner,
  Banner,
} from "@shopify/polaris";

interface Product {
  id: string;
  title: string;
  barcode: string | null;
  sku: string | null;
  price: number | null;
  image_url: string | null;
}

interface ProductPickerProps {
  shop: string;
  onSelect: (product: Product) => void;
  onClose: () => void;
}

export function ProductPicker({ shop, onSelect, onClose }: ProductPickerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const searchProducts = async () => {
      if (!searchQuery.trim()) {
        setProducts([]);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `/api/products/search?shop=${encodeURIComponent(shop)}&q=${encodeURIComponent(searchQuery)}&limit=20`
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Failed to search products. Please try again.");
        }

        const data = await response.json();
        setProducts(Array.isArray(data) ? data : []);
        setError(null);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Unknown error occurred";
        setError(errorMessage);
        setProducts([]);
        console.error("Product search error", err);
      } finally {
        setIsLoading(false);
      }
    };

    // Debounce search
    const timeoutId = setTimeout(searchProducts, 300);
    return () => clearTimeout(timeoutId);
  }, [searchQuery, shop]);

  const handleSelect = (product: Product) => {
    onSelect(product);
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      title="Select Product"
      primaryAction={{
        content: "Close",
        onAction: onClose,
      }}
    >
      <Modal.Section>
        <TextField
          label="Search Products"
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search by barcode, SKU, or product name..."
          autoComplete="off"
        />

        {error && (
          <div style={{ marginTop: "1rem" }}>
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          </div>
        )}

        {isLoading && (
          <div style={{ marginTop: "1rem", textAlign: "center" }}>
            <Spinner accessibilityLabel="Searching products" size="small" />
          </div>
        )}

        {!isLoading && !error && products.length === 0 && searchQuery && (
          <div style={{ marginTop: "1rem" }}>
            <EmptyState
              heading="No products found"
              image="https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg"
            >
              <p>Try a different search term.</p>
            </EmptyState>
          </div>
        )}

        {!isLoading && products.length > 0 && (
          <div style={{ marginTop: "1rem", maxHeight: "400px", overflowY: "auto" }}>
            <ResourceList
              resourceName={{ singular: "product", plural: "products" }}
              items={products}
              renderItem={(item) => {
                const product = item as Product;
                const media = product.image_url ? (
                  <Thumbnail source={product.image_url} alt={product.title} />
                ) : null;

                return (
                  <ResourceItem
                    id={product.id}
                    media={media}
                    onClick={() => handleSelect(product)}
                  >
                    <Text variant="bodyMd" fontWeight="bold" as="h3">
                      {product.title}
                    </Text>
                    <div>
                      {product.barcode && (
                        <Text variant="bodySm" as="p">
                          Barcode: {product.barcode}
                        </Text>
                      )}
                      {product.sku && (
                        <Text variant="bodySm" as="p">
                          SKU: {product.sku}
                        </Text>
                      )}
                      {product.price !== null && (
                        <Text variant="bodySm" as="p">
                          Price: ${product.price.toFixed(2)}
                        </Text>
                      )}
                    </div>
                  </ResourceItem>
                );
              }}
            />
          </div>
        )}

        {!searchQuery && (
          <div style={{ marginTop: "1rem" }}>
            <EmptyState
              heading="Search for products"
              image="https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg"
            >
              <p>Enter a search term to find products.</p>
            </EmptyState>
          </div>
        )}
      </Modal.Section>
    </Modal>
  );
}
