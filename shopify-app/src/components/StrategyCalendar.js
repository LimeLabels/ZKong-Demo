import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useEffect } from "react";
import { Card, Button, Text, Select, TextField, FormLayout, DatePicker, Checkbox, Banner, Spinner, } from "@shopify/polaris";
import { useStoreMapping } from "../hooks/useStoreMapping";
import { useShopifyAuth } from "../hooks/useShopifyAuth";
import { ProductPicker } from "./ProductPicker";
// Helper function to convert 12-hour time to 24-hour format
function convertTo24Hour(timeStr) {
    // If already in 24-hour format (HH:MM), return as is
    if (/^\d{2}:\d{2}$/.test(timeStr)) {
        return timeStr;
    }
    // Handle 12-hour format with AM/PM
    const match = timeStr.match(/(\d{1,2}):(\d{2})\s*(AM|PM)/i);
    if (match) {
        let hours = parseInt(match[1]);
        const minutes = match[2];
        const period = match[3].toUpperCase();
        if (period === "PM" && hours !== 12) {
            hours += 12;
        }
        else if (period === "AM" && hours === 12) {
            hours = 0;
        }
        return `${hours.toString().padStart(2, "0")}:${minutes}`;
    }
    // Return as-is if format is unrecognized
    return timeStr;
}
export function StrategyCalendar() {
    const auth = useShopifyAuth();
    const { storeMapping, isLoading: isLoadingMapping } = useStoreMapping();
    const [formData, setFormData] = useState({
        name: "",
        startDate: new Date(),
        endDate: new Date(),
        repeatType: "none",
        selectedDays: [],
        timeSlots: [{ startTime: "09:00", endTime: "17:00" }],
        products: [],
        priceOverride: 0,
        promotionText: "",
        storeMappingId: "",
        originalPrice: "",
        barcode: "",
        itemId: "",
        triggerStores: [],
    });
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const [submitSuccess, setSubmitSuccess] = useState(false);
    const [showProductPicker, setShowProductPicker] = useState(false);
    // Auto-populate store mapping ID when available
    useEffect(() => {
        if (storeMapping?.id && !formData.storeMappingId) {
            setFormData((prev) => ({
                ...prev,
                storeMappingId: storeMapping.id,
            }));
        }
    }, [storeMapping, formData.storeMappingId]);
    if (isLoadingMapping) {
        return (_jsx(Spinner, { accessibilityLabel: "Loading store information", size: "large" }));
    }
    if (!storeMapping?.id) {
        return (_jsx(Banner, { tone: "warning", title: "Store mapping not found", children: _jsx("p", { children: "Please complete onboarding to create pricing strategies." }) }));
    }
    const repeatOptions = [
        { label: "No Repeat", value: "none" },
        { label: "Daily", value: "daily" },
        { label: "Weekly", value: "weekly" },
        { label: "Monthly", value: "monthly" },
    ];
    const dayOptions = [
        { label: "Sunday", value: 1 },
        { label: "Monday", value: 2 },
        { label: "Tuesday", value: 3 },
        { label: "Wednesday", value: 4 },
        { label: "Thursday", value: 5 },
        { label: "Friday", value: 6 },
        { label: "Saturday", value: 7 },
    ];
    const handleSubmit = async () => {
        setIsSubmitting(true);
        setSubmitError(null);
        setSubmitSuccess(false);
        try {
            // Validate barcode is provided
            if (!formData.barcode || formData.barcode.trim() === "") {
                throw new Error("Product barcode is required");
            }
            // Validate and clean price (priceOverride is always a number)
            if (formData.priceOverride <= 0 || isNaN(formData.priceOverride)) {
                throw new Error("Promotional price must be greater than 0");
            }
            const cleanPrice = formData.priceOverride.toFixed(2);
            // Get original price if available
            const originalPrice = formData.originalPrice
                ? parseFloat(formData.originalPrice)
                : null;
            // Build products array - always ensure it's a non-empty array
            const products = formData.products.length > 0
                ? formData.products
                    .filter((p) => p.barcode && p.barcode.trim() !== "")
                    .map((product) => ({
                    pc: product.barcode.trim(),
                    pp: cleanPrice,
                    original_price: product.price || originalPrice,
                }))
                : [
                    {
                        pc: formData.barcode.trim(),
                        pp: cleanPrice,
                        original_price: originalPrice,
                    },
                ];
            // Final validation - ensure we have at least one product
            if (products.length === 0) {
                throw new Error("At least one product with a valid barcode is required");
            }
            // Map selectedDays to backend format
            // Frontend: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat
            // Backend: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
            let triggerDays = undefined;
            if (formData.repeatType === "weekly" &&
                formData.selectedDays.length > 0) {
                triggerDays = formData.selectedDays.map((d) => {
                    // Convert frontend day to backend day
                    // Frontend 1 (Sun) -> Backend 7
                    // Frontend 2 (Mon) -> Backend 1
                    // Frontend 3 (Tue) -> Backend 2, etc.
                    const backendDay = d === 1 ? 7 : d - 1;
                    return backendDay.toString();
                });
            }
            // Convert time slots to 24-hour format
            const timeSlots = formData.timeSlots.map((slot) => ({
                start_time: convertTo24Hour(slot.startTime),
                end_time: convertTo24Hour(slot.endTime),
            }));
            // Build payload for new API
            const payload = {
                store_mapping_id: formData.storeMappingId,
                name: formData.name,
                products: products,
                start_date: formData.startDate.toISOString(),
                repeat_type: formData.repeatType,
                time_slots: timeSlots,
            };
            // Add optional fields
            if (formData.endDate) {
                payload.end_date = formData.endDate.toISOString();
            }
            if (triggerDays && triggerDays.length > 0) {
                payload.trigger_days = triggerDays;
            }
            if (formData.triggerStores && formData.triggerStores.length > 0) {
                // Filter out empty strings and trim store codes
                const validStores = formData.triggerStores
                    .map((s) => s.trim())
                    .filter((s) => s.length > 0);
                if (validStores.length > 0) {
                    payload.trigger_stores = validStores;
                }
            }
            // Call new price adjustment schedule API
            const response = await fetch("/api/price-adjustments/create", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail ||
                    "Failed to create price adjustment order. Please check your input and try again.");
            }
            const result = await response.json();
            setSubmitSuccess(true);
            setSubmitError(null);
            // Reset form after successful submission
            setTimeout(() => {
                setFormData((prev) => ({
                    name: "",
                    startDate: new Date(),
                    endDate: new Date(),
                    repeatType: "none",
                    selectedDays: [],
                    timeSlots: [{ startTime: "09:00", endTime: "17:00" }],
                    products: [],
                    priceOverride: 0,
                    promotionText: "",
                    storeMappingId: prev.storeMappingId, // Keep store mapping ID
                    originalPrice: "",
                    barcode: "",
                    itemId: "",
                    triggerStores: [], // Reset trigger stores
                }));
                setSubmitSuccess(false);
            }, 3000);
        }
        catch (error) {
            const errorMessage = error.message || "An error occurred while creating the strategy";
            setSubmitError(errorMessage);
            setSubmitSuccess(false);
            console.error("Failed to create strategy", error);
        }
        finally {
            setIsSubmitting(false);
        }
    };
    const addTimeSlot = () => {
        setFormData({
            ...formData,
            timeSlots: [
                ...formData.timeSlots,
                { startTime: "09:00", endTime: "17:00" },
            ],
        });
    };
    const updateTimeSlot = (index, field, value) => {
        const newSlots = [...formData.timeSlots];
        newSlots[index][field] = value;
        setFormData({ ...formData, timeSlots: newSlots });
    };
    const removeTimeSlot = (index) => {
        setFormData({
            ...formData,
            timeSlots: formData.timeSlots.filter((_, i) => i !== index),
        });
    };
    if (!formData.storeMappingId) {
        return (_jsx(Card, { children: _jsx(Banner, { tone: "warning", title: "Store mapping not found", children: _jsx("p", { children: "Please wait while we load your store information..." }) }) }));
    }
    return (_jsx(Card, { children: _jsxs(FormLayout, { children: [submitError && (_jsxs(Banner, { tone: "critical", onDismiss: () => setSubmitError(null), children: [_jsx("p", { children: submitError }), _jsx("p", { style: { fontSize: "0.875rem", marginTop: "0.5rem" }, children: "Please check your input and try again." })] })), submitSuccess && (_jsx(Banner, { tone: "success", onDismiss: () => setSubmitSuccess(false), children: _jsx("p", { children: "Strategy created successfully! The price adjustments will run automatically according to the schedule." }) })), _jsx(TextField, { label: "Strategy Name", value: formData.name, onChange: (value) => setFormData({ ...formData, name: value }), placeholder: "e.g., Happy Hour Pricing", autoComplete: "off" }), _jsxs(FormLayout.Group, { children: [_jsx(DatePicker, { month: formData.startDate.getMonth(), year: formData.startDate.getFullYear(), selected: formData.startDate, onMonthChange: (month, year) => setFormData({
                                ...formData,
                                startDate: new Date(year, month, formData.startDate.getDate()),
                            }), onChange: (range) => {
                                const startDate = new Date(range.start);
                                setFormData({ ...formData, startDate });
                            } }), _jsx(DatePicker, { month: formData.endDate.getMonth(), year: formData.endDate.getFullYear(), selected: formData.endDate, onMonthChange: (month, year) => setFormData({
                                ...formData,
                                endDate: new Date(year, month, formData.endDate.getDate()),
                            }), onChange: (range) => {
                                const endDate = new Date(range.start);
                                setFormData({ ...formData, endDate });
                            } })] }), _jsx(Select, { label: "Repeat", options: repeatOptions, value: formData.repeatType, onChange: (value) => setFormData({
                        ...formData,
                        repeatType: value,
                    }) }), formData.repeatType === "weekly" && (_jsx(FormLayout.Group, { children: dayOptions.map((day) => (_jsx(Checkbox, { label: day.label, checked: formData.selectedDays.includes(day.value), onChange: (checked) => {
                            const newDays = checked
                                ? [...formData.selectedDays, day.value]
                                : formData.selectedDays.filter((d) => d !== day.value);
                            setFormData({ ...formData, selectedDays: newDays });
                        } }, day.value))) })), _jsx(TextField, { label: "Trigger Stores (Optional)", value: formData.triggerStores.join(", "), onChange: (value) => {
                        // Parse comma-separated store codes
                        const stores = value
                            .split(",")
                            .map((s) => s.trim())
                            .filter((s) => s.length > 0);
                        setFormData({ ...formData, triggerStores: stores });
                    }, placeholder: "e.g., 001, 002, 003", helpText: "Enter store codes separated by commas. Leave empty to use the default store from store mapping.", autoComplete: "off" }), _jsx(Text, { variant: "headingSm", as: "h3", children: "Time Windows" }), formData.timeSlots.map((slot, index) => (_jsxs(FormLayout.Group, { children: [_jsx(TextField, { label: "Start Time", type: "time", value: slot.startTime, onChange: (value) => updateTimeSlot(index, "startTime", value), autoComplete: "off" }), _jsx(TextField, { label: "End Time", type: "time", value: slot.endTime, onChange: (value) => updateTimeSlot(index, "endTime", value), autoComplete: "off" }), formData.timeSlots.length > 1 && (_jsx(Button, { onClick: () => removeTimeSlot(index), children: "Remove" }))] }, index))), _jsx(Button, { onClick: addTimeSlot, children: "Add Time Window" }), _jsx(Card, { children: _jsxs("div", { style: { padding: "1rem" }, children: [_jsx(Text, { variant: "headingSm", as: "h3", children: "Product Selection" }), _jsxs("div", { style: { marginTop: "1rem" }, children: [_jsx(Button, { onClick: () => setShowProductPicker(true), children: formData.barcode
                                            ? `Change Product (${formData.barcode})`
                                            : "Select Product" }), formData.barcode && (_jsx(Button, { variant: "plain", tone: "critical", onClick: () => {
                                            setFormData({
                                                ...formData,
                                                barcode: "",
                                                originalPrice: "",
                                            });
                                        }, children: "Clear" }))] }), formData.barcode && (_jsx("div", { style: { marginTop: "1rem" }, children: _jsx(TextField, { label: "Product Barcode", value: formData.barcode, readOnly: true, autoComplete: "off", helpText: "Selected product barcode" }) }))] }) }), showProductPicker && auth.shop && (_jsx(ProductPicker, { shop: auth.shop, onSelect: (product) => {
                        setFormData({
                            ...formData,
                            barcode: product.barcode || "",
                            originalPrice: product.price?.toString() || "",
                        });
                        setShowProductPicker(false);
                    }, onClose: () => setShowProductPicker(false) })), _jsx(TextField, { label: "Hipoink Item ID (Optional)", value: formData.itemId, onChange: (value) => setFormData({ ...formData, itemId: value }), placeholder: "Hipoink internal item ID", autoComplete: "off", helpText: "Leave empty if using barcode lookup" }), _jsx(TextField, { label: "Original Price (Optional)", type: "number", value: formData.originalPrice, onChange: (value) => setFormData({ ...formData, originalPrice: value }), prefix: "$", autoComplete: "off" }), _jsx(TextField, { label: "Promotional Price", type: "number", value: formData.priceOverride.toString(), onChange: (value) => setFormData({ ...formData, priceOverride: parseFloat(value) || 0 }), prefix: "$", autoComplete: "off" }), _jsx(TextField, { label: "Promotion Text (Optional)", value: formData.promotionText, onChange: (value) => setFormData({ ...formData, promotionText: value }), placeholder: "e.g., Limited Time Offer", autoComplete: "off" }), _jsx(Button, { variant: "primary", loading: isSubmitting, onClick: handleSubmit, disabled: !formData.name ||
                        (!formData.barcode && formData.products.length === 0), children: "Create Strategy" })] }) }));
}
