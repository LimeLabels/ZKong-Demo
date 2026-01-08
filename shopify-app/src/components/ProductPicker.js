import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useEffect } from "react";
import { Modal, TextField, ResourceList, ResourceItem, Thumbnail, Text, EmptyState, Spinner, Banner, } from "@shopify/polaris";
export function ProductPicker({ shop, onSelect, onClose }) {
    const [searchQuery, setSearchQuery] = useState("");
    const [products, setProducts] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    useEffect(() => {
        const searchProducts = async () => {
            if (!searchQuery.trim()) {
                setProducts([]);
                return;
            }
            setIsLoading(true);
            setError(null);
            try {
                const response = await fetch(`/api/products/search?shop=${encodeURIComponent(shop)}&q=${encodeURIComponent(searchQuery)}&limit=20`);
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || "Failed to search products. Please try again.");
                }
                const data = await response.json();
                setProducts(Array.isArray(data) ? data : []);
                setError(null);
            }
            catch (err) {
                const errorMessage = err instanceof Error ? err.message : "Unknown error occurred";
                setError(errorMessage);
                setProducts([]);
                console.error("Product search error", err);
            }
            finally {
                setIsLoading(false);
            }
        };
        // Debounce search
        const timeoutId = setTimeout(searchProducts, 300);
        return () => clearTimeout(timeoutId);
    }, [searchQuery, shop]);
    const handleSelect = (product) => {
        onSelect(product);
    };
    return (_jsx(Modal, { open: true, onClose: onClose, title: "Select Product", primaryAction: {
            content: "Close",
            onAction: onClose,
        }, children: _jsxs(Modal.Section, { children: [_jsx(TextField, { label: "Search Products", value: searchQuery, onChange: setSearchQuery, placeholder: "Search by barcode, SKU, or product name...", autoComplete: "off" }), error && (_jsx("div", { style: { marginTop: "1rem" }, children: _jsx(Banner, { tone: "critical", onDismiss: () => setError(null), children: error }) })), isLoading && (_jsx("div", { style: { marginTop: "1rem", textAlign: "center" }, children: _jsx(Spinner, { accessibilityLabel: "Searching products", size: "small" }) })), !isLoading && !error && products.length === 0 && searchQuery && (_jsx("div", { style: { marginTop: "1rem" }, children: _jsx(EmptyState, { heading: "No products found", image: "https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg", children: _jsx("p", { children: "Try a different search term." }) }) })), !isLoading && products.length > 0 && (_jsx("div", { style: { marginTop: "1rem", maxHeight: "400px", overflowY: "auto" }, children: _jsx(ResourceList, { resourceName: { singular: "product", plural: "products" }, items: products, renderItem: (item) => {
                            const product = item;
                            return (_jsxs(ResourceItem, { id: product.id, media: product.image_url ? (_jsx(Thumbnail, { source: product.image_url, alt: product.title })) : undefined, onClick: () => handleSelect(product), children: [_jsx(Text, { variant: "bodyMd", fontWeight: "bold", as: "h3", children: product.title }), _jsxs("div", { children: [product.barcode && (_jsxs(Text, { variant: "bodySm", as: "p", children: ["Barcode: ", product.barcode] })), product.sku && (_jsxs(Text, { variant: "bodySm", as: "p", children: ["SKU: ", product.sku] })), product.price !== null && (_jsxs(Text, { variant: "bodySm", as: "p", children: ["Price: $", product.price.toFixed(2)] }))] })] }));
                        } }) })), !searchQuery && (_jsx("div", { style: { marginTop: "1rem" }, children: _jsx(EmptyState, { heading: "Search for products", image: "https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg", children: _jsx("p", { children: "Enter a search term to find products." }) }) }))] }) }));
}
