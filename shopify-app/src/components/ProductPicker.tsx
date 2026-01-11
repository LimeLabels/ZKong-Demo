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
  Checkbox,
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
  onSelectMultiple?: (products: Product[]) => void;
  onClose: () => void;
  multiSelect?: boolean;
  selectedProducts?: Product[];
}

export function ProductPicker({
  shop,
  onSelect,
  onSelectMultiple,
  onClose,
  multiSelect = false,
  selectedProducts = [],
}: ProductPickerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(selectedProducts.map((p) => p.id))
  );

  // Sync selectedIds when selectedProducts prop changes
  useEffect(() => {
    setSelectedIds(new Set(selectedProducts.map((p) => p.id)));
  }, [selectedProducts]);

  useEffect(() => {
    const searchProducts = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // If no search query, fetch all products (or recent products)
        // Pass empty string or use a wildcard to get all products
        const queryParam = searchQuery.trim() || "";
        const url = `/api/products/search?shop=${encodeURIComponent(
          shop
        )}&limit=50${queryParam ? `&q=${encodeURIComponent(queryParam)}` : ""}`;

        const response = await fetch(url);

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || "Failed to search products. Please try again."
          );
        }

        const data = await response.json();
        setProducts(Array.isArray(data) ? data : []);
        setError(null);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Unknown error occurred";
        setError(errorMessage);
        setProducts([]);
        console.error("Product search error", err);
      } finally {
        setIsLoading(false);
      }
    };

    // Load products immediately on mount, then debounce search changes
    if (searchQuery.trim() === "") {
      // Load immediately when no search query (initial load)
      searchProducts();
    } else {
      // Debounce search queries
      const timeoutId = setTimeout(searchProducts, 300);
      return () => clearTimeout(timeoutId);
    }
  }, [searchQuery, shop]);

  const handleSelect = (product: Product) => {
    if (multiSelect) {
      // In multi-select mode, just toggle selection without closing modal
      const newSelectedIds = new Set(selectedIds);
      if (newSelectedIds.has(product.id)) {
        newSelectedIds.delete(product.id);
      } else {
        newSelectedIds.add(product.id);
      }
      setSelectedIds(newSelectedIds);
      // Don't call onSelectMultiple here - wait for Confirm button
    } else {
      // In single-select mode, select and close
      onSelect(product);
      onClose();
    }
  };

  const handleConfirmSelection = () => {
    if (multiSelect && onSelectMultiple) {
      // Get selected products from the current products list
      const selectedProducts = products.filter((p) => selectedIds.has(p.id));
      onSelectMultiple(selectedProducts);
    }
    onClose();
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      title={multiSelect ? "Select Products" : "Select Product"}
      primaryAction={{
        content: multiSelect ? `Confirm (${selectedIds.size})` : "Close",
        onAction: multiSelect ? handleConfirmSelection : onClose,
      }}
      secondaryActions={
        multiSelect
          ? [
              {
                content: "Clear All",
                onAction: () => {
                  setSelectedIds(new Set());
                  if (onSelectMultiple) {
                    onSelectMultiple([]);
                  }
                },
              },
            ]
          : undefined
      }
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
          <div
            style={{ marginTop: "1rem", maxHeight: "400px", overflowY: "auto" }}
          >
            <ResourceList
              resourceName={{ singular: "product", plural: "products" }}
              items={products}
              renderItem={(item) => {
                const product = item as Product;

                const isSelected = selectedIds.has(product.id);

                return (
                  <ResourceItem
                    id={product.id}
                    media={
                      product.image_url ? (
                        <Thumbnail
                          source={product.image_url}
                          alt={product.title}
                        />
                      ) : undefined
                    }
                    onClick={() => handleSelect(product)}
                    accessibilityLabel={`Select ${product.title}`}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "0.5rem",
                      }}
                    >
                      {multiSelect && (
                        <div
                          style={{ marginTop: "0.25rem" }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Checkbox
                            checked={isSelected}
                            onChange={() => handleSelect(product)}
                            label=""
                          />
                        </div>
                      )}
                      <div style={{ flex: 1 }}>
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
                      </div>
                    </div>
                  </ResourceItem>
                );
              }}
            />
          </div>
        )}

        {!isLoading && !error && products.length === 0 && !searchQuery && (
          <div style={{ marginTop: "1rem" }}>
            <EmptyState
              heading="No products found"
              image="https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg"
            >
              <p>No products available. Try searching for products.</p>
            </EmptyState>
          </div>
        )}
      </Modal.Section>
    </Modal>
  );
}
