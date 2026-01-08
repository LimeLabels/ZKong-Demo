import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useEffect } from "react";
import { Card, ResourceList, ResourceItem, Text, Button, Banner, EmptyState, Spinner, Modal, TextField, FormLayout, Badge, } from "@shopify/polaris";
import { useStoreMapping } from "../hooks/useStoreMapping";
import { useShopifyAuth } from "../hooks/useShopifyAuth";
export function StrategyList() {
    const auth = useShopifyAuth();
    const { storeMapping, isLoading: isLoadingMapping } = useStoreMapping();
    const [strategies, setStrategies] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedStrategy, setSelectedStrategy] = useState(null);
    const [showEditModal, setShowEditModal] = useState(false);
    useEffect(() => {
        if (!storeMapping?.id) {
            setIsLoading(false);
            return;
        }
        fetchStrategies();
    }, [storeMapping]);
    const fetchStrategies = async () => {
        if (!storeMapping?.id)
            return;
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetch(`/api/price-adjustments/?store_mapping_id=${storeMapping.id}`);
            if (!response.ok) {
                throw new Error("Failed to fetch strategies");
            }
            const data = await response.json();
            setStrategies(data);
        }
        catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        }
        finally {
            setIsLoading(false);
        }
    };
    const handleDelete = async (strategyId) => {
        if (!confirm("Are you sure you want to delete this strategy? This will stop all scheduled price adjustments.")) {
            return;
        }
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetch(`/api/price-adjustments/${strategyId}`, {
                method: "DELETE",
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || "Failed to delete strategy");
            }
            // Refresh list
            await fetchStrategies();
        }
        catch (err) {
            const errorMessage = err instanceof Error ? err.message : "Unknown error occurred";
            setError(errorMessage);
            console.error("Failed to delete strategy", err);
        }
        finally {
            setIsLoading(false);
        }
    };
    const formatDate = (dateString) => {
        return new Date(dateString).toLocaleDateString();
    };
    const formatTime = (timeString) => {
        const [hours, minutes] = timeString.split(":");
        const hour = parseInt(hours);
        const ampm = hour >= 12 ? "PM" : "AM";
        const displayHour = hour % 12 || 12;
        return `${displayHour}:${minutes} ${ampm}`;
    };
    if (isLoadingMapping || isLoading) {
        return _jsx(Spinner, { accessibilityLabel: "Loading strategies", size: "large" });
    }
    if (!storeMapping?.id) {
        return (_jsx(Banner, { tone: "warning", title: "Store mapping not found", children: _jsx("p", { children: "Please complete onboarding to manage pricing strategies." }) }));
    }
    if (error) {
        return (_jsx(Banner, { tone: "critical", onDismiss: () => setError(null), children: error }));
    }
    return (_jsxs(Card, { children: [_jsx(ResourceList, { resourceName: { singular: "strategy", plural: "strategies" }, items: strategies, emptyState: _jsx(EmptyState, { heading: "No pricing strategies yet", image: "https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg", children: _jsx("p", { children: "Create your first pricing strategy to get started." }) }), renderItem: (item) => {
                    const strategy = item;
                    const productCount = strategy.products?.products?.length || 0;
                    const firstTimeSlot = strategy.time_slots?.[0];
                    return (_jsx(ResourceItem, { id: strategy.id, accessibilityLabel: `View details for ${strategy.name}`, onClick: () => {
                            setSelectedStrategy(strategy);
                            setShowEditModal(true);
                        }, children: _jsxs("div", { style: {
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "start",
                            }, children: [_jsxs("div", { children: [_jsx(Text, { variant: "bodyMd", fontWeight: "bold", as: "h3", children: strategy.name }), _jsxs(Text, { variant: "bodySm", as: "p", children: ["Order: ", strategy.order_number] }), _jsxs(Text, { variant: "bodySm", as: "p", children: ["Products: ", productCount] }), firstTimeSlot && (_jsxs(Text, { variant: "bodySm", as: "p", children: ["Time: ", formatTime(firstTimeSlot.start_time), " -", " ", formatTime(firstTimeSlot.end_time)] })), _jsxs(Text, { variant: "bodySm", as: "p", children: ["Repeat:", " ", strategy.repeat_type === "none"
                                                    ? "Once"
                                                    : strategy.repeat_type] }), strategy.next_trigger_at && (_jsxs(Text, { variant: "bodySm", as: "p", children: ["Next trigger: ", formatDate(strategy.next_trigger_at)] })), _jsx("div", { style: { marginTop: "0.5rem" }, children: _jsx(Badge, { tone: strategy.is_active ? "success" : "attention", children: strategy.is_active ? "Active" : "Inactive" }) })] }), _jsxs("div", { children: [_jsx(Button, { variant: "plain", onClick: () => {
                                                setSelectedStrategy(strategy);
                                                setShowEditModal(true);
                                            }, children: "View" }), _jsx(Button, { variant: "plain", tone: "critical", onClick: () => handleDelete(strategy.id), children: "Delete" })] })] }) }));
                } }), showEditModal && selectedStrategy && (_jsx(Modal, { open: true, onClose: () => {
                    setShowEditModal(false);
                    setSelectedStrategy(null);
                }, title: selectedStrategy.name, primaryAction: {
                    content: "Close",
                    onAction: () => {
                        setShowEditModal(false);
                        setSelectedStrategy(null);
                    },
                }, children: _jsx(Modal.Section, { children: _jsxs(FormLayout, { children: [_jsx(TextField, { label: "Name", value: selectedStrategy.name, readOnly: true, autoComplete: "off" }), _jsx(TextField, { label: "Order Number", value: selectedStrategy.order_number, readOnly: true, autoComplete: "off" }), _jsxs(Text, { variant: "bodySm", as: "p", children: [_jsx("strong", { children: "Status:" }), " ", selectedStrategy.is_active ? "Active" : "Inactive"] }), _jsxs(Text, { variant: "bodySm", as: "p", children: [_jsx("strong", { children: "Products:" }), " ", selectedStrategy.products?.products?.length || 0] }), _jsxs(Text, { variant: "bodySm", as: "p", children: [_jsx("strong", { children: "Repeat Type:" }), " ", selectedStrategy.repeat_type] }), selectedStrategy.next_trigger_at && (_jsxs(Text, { variant: "bodySm", as: "p", children: [_jsx("strong", { children: "Next Trigger:" }), " ", new Date(selectedStrategy.next_trigger_at).toLocaleString()] })), selectedStrategy.time_slots &&
                                selectedStrategy.time_slots.length > 0 && (_jsxs("div", { children: [_jsx(Text, { variant: "bodySm", as: "p", children: _jsx("strong", { children: "Time Slots:" }) }), selectedStrategy.time_slots.map((slot, idx) => (_jsxs(Text, { variant: "bodySm", as: "p", children: [formatTime(slot.start_time), " -", " ", formatTime(slot.end_time)] }, idx)))] }))] }) }) }))] }));
}
