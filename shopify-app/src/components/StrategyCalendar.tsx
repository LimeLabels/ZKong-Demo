import React, { useState, useEffect } from "react";
import {
  Card,
  Button,
  Text,
  Select,
  TextField,
  FormLayout,
  DatePicker,
  Checkbox,
  Banner,
  EmptyState,
  Spinner,
} from "@shopify/polaris";
import { CalendarIcon } from "@shopify/polaris-icons";
import { useStoreMapping } from "../hooks/useStoreMapping";
import { useShopifyAuth } from "../hooks/useShopifyAuth";
import { ProductPicker } from "./ProductPicker";

interface StrategyProduct {
  id: string;
  title: string;
  barcode: string;
  price: number;
}

interface StrategyTimeSlot {
  startTime: string;
  endTime: string;
}

interface StrategyFormData {
  name: string;
  startDate: Date;
  endDate: Date;
  repeatType: "none" | "daily" | "weekly" | "monthly";
  selectedDays: number[];
  timeSlots: StrategyTimeSlot[];
  products: StrategyProduct[];
  priceOverride: number;
  promotionText: string;
  storeMappingId: string; // UUID for store mapping
  originalPrice: string;
  barcode: string; // For single product entry
  itemId: string; // Optional Hipoink item ID
  triggerStores: string[]; // Array of store codes for f3 (trigger_stores)
}

// Helper function to convert 12-hour time to 24-hour format
function convertTo24Hour(timeStr: string): string {
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
    } else if (period === "AM" && hours === 12) {
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

  const [formData, setFormData] = useState<StrategyFormData>({
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
  const [submitError, setSubmitError] = useState<string | null>(null);
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
    return (
      <Spinner accessibilityLabel="Loading store information" size="large" />
    );
  }

  if (!storeMapping?.id) {
    const handleGoToOnboarding = () => {
      // Add query parameter to force onboarding, preserve shop
      const url = new URL(window.location.href);
      const shop =
        auth.shop || new URLSearchParams(window.location.search).get("shop");
      url.searchParams.set("onboarding", "true");
      if (shop) {
        url.searchParams.set("shop", shop);
      }
      window.location.href = url.toString();
    };

    return (
      <Card>
        <Banner tone="warning" title="Store mapping not found">
          <p>Please complete onboarding to create pricing strategies.</p>
          <div style={{ marginTop: "1rem" }}>
            <Button variant="primary" onClick={handleGoToOnboarding}>
              Go to Onboarding
            </Button>
          </div>
        </Banner>
      </Card>
    );
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
      const products =
        formData.products.length > 0
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
        throw new Error(
          "At least one product with a valid barcode is required"
        );
      }

      // Map selectedDays to backend format
      // Frontend: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat
      // Backend: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
      let triggerDays: string[] | undefined = undefined;
      if (
        formData.repeatType === "weekly" &&
        formData.selectedDays.length > 0
      ) {
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
      const payload: any = {
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
        throw new Error(
          error.detail ||
            "Failed to create price adjustment order. Please check your input and try again."
        );
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
    } catch (error: any) {
      const errorMessage =
        error.message || "An error occurred while creating the strategy";
      setSubmitError(errorMessage);
      setSubmitSuccess(false);
      console.error("Failed to create strategy", error);
    } finally {
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

  const updateTimeSlot = (
    index: number,
    field: "startTime" | "endTime",
    value: string
  ) => {
    const newSlots = [...formData.timeSlots];
    newSlots[index][field] = value;
    setFormData({ ...formData, timeSlots: newSlots });
  };

  const removeTimeSlot = (index: number) => {
    setFormData({
      ...formData,
      timeSlots: formData.timeSlots.filter((_, i) => i !== index),
    });
  };

  if (!formData.storeMappingId) {
    return (
      <Card>
        <Banner tone="warning" title="Store mapping not found">
          <p>Please wait while we load your store information...</p>
        </Banner>
      </Card>
    );
  }

  return (
    <Card>
      <FormLayout>
        {submitError && (
          <Banner tone="critical" onDismiss={() => setSubmitError(null)}>
            <p>{submitError}</p>
            <p style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
              Please check your input and try again.
            </p>
          </Banner>
        )}

        {submitSuccess && (
          <Banner tone="success" onDismiss={() => setSubmitSuccess(false)}>
            <p>
              Strategy created successfully! The price adjustments will run
              automatically according to the schedule.
            </p>
          </Banner>
        )}

        <TextField
          label="Strategy Name"
          value={formData.name}
          onChange={(value) => setFormData({ ...formData, name: value })}
          placeholder="e.g., Happy Hour Pricing"
          autoComplete="off"
        />

        <FormLayout.Group>
          <DatePicker
            month={formData.startDate.getMonth()}
            year={formData.startDate.getFullYear()}
            selected={formData.startDate}
            onMonthChange={(month, year) =>
              setFormData({
                ...formData,
                startDate: new Date(year, month, formData.startDate.getDate()),
              })
            }
            onChange={(range) => {
              const startDate = new Date(range.start);
              setFormData({ ...formData, startDate });
            }}
          />
          <DatePicker
            month={formData.endDate.getMonth()}
            year={formData.endDate.getFullYear()}
            selected={formData.endDate}
            onMonthChange={(month, year) =>
              setFormData({
                ...formData,
                endDate: new Date(year, month, formData.endDate.getDate()),
              })
            }
            onChange={(range) => {
              const endDate = new Date(range.start);
              setFormData({ ...formData, endDate });
            }}
          />
        </FormLayout.Group>

        <Select
          label="Repeat"
          options={repeatOptions}
          value={formData.repeatType}
          onChange={(value) =>
            setFormData({
              ...formData,
              repeatType: value as StrategyFormData["repeatType"],
            })
          }
        />

        {formData.repeatType === "weekly" && (
          <FormLayout.Group>
            {dayOptions.map((day) => (
              <Checkbox
                key={day.value}
                label={day.label}
                checked={formData.selectedDays.includes(day.value)}
                onChange={(checked) => {
                  const newDays = checked
                    ? [...formData.selectedDays, day.value]
                    : formData.selectedDays.filter((d) => d !== day.value);
                  setFormData({ ...formData, selectedDays: newDays });
                }}
              />
            ))}
          </FormLayout.Group>
        )}

        <TextField
          label="Trigger Stores (Optional)"
          value={formData.triggerStores.join(", ")}
          onChange={(value) => {
            // Parse comma-separated store codes
            const stores = value
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s.length > 0);
            setFormData({ ...formData, triggerStores: stores });
          }}
          placeholder="e.g., 001, 002, 003"
          helpText="Enter store codes separated by commas. Leave empty to use the default store from store mapping."
          autoComplete="off"
        />

        <Text variant="headingSm" as="h3">
          Time Windows
        </Text>
        {formData.timeSlots.map((slot, index) => (
          <FormLayout.Group key={index}>
            <TextField
              label="Start Time"
              type="time"
              value={slot.startTime}
              onChange={(value) => updateTimeSlot(index, "startTime", value)}
              autoComplete="off"
            />
            <TextField
              label="End Time"
              type="time"
              value={slot.endTime}
              onChange={(value) => updateTimeSlot(index, "endTime", value)}
              autoComplete="off"
            />
            {formData.timeSlots.length > 1 && (
              <Button onClick={() => removeTimeSlot(index)}>Remove</Button>
            )}
          </FormLayout.Group>
        ))}
        <Button onClick={addTimeSlot}>Add Time Window</Button>

        <Card>
          <div style={{ padding: "1rem" }}>
            <Text variant="headingSm" as="h3">
              Product Selection
            </Text>
            <div style={{ marginTop: "1rem" }}>
              <Button onClick={() => setShowProductPicker(true)}>
                {formData.barcode
                  ? `Change Product (${formData.barcode})`
                  : "Select Product"}
              </Button>
              {formData.barcode && (
                <Button
                  variant="plain"
                  tone="critical"
                  onClick={() => {
                    setFormData({
                      ...formData,
                      barcode: "",
                      originalPrice: "",
                    });
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
            {formData.barcode && (
              <div style={{ marginTop: "1rem" }}>
                <TextField
                  label="Product Barcode"
                  value={formData.barcode}
                  readOnly
                  autoComplete="off"
                  helpText="Selected product barcode"
                />
              </div>
            )}
          </div>
        </Card>

        {showProductPicker && auth.shop && (
          <ProductPicker
            shop={auth.shop}
            onSelect={(product) => {
              setFormData({
                ...formData,
                barcode: product.barcode || "",
                originalPrice: product.price?.toString() || "",
              });
              setShowProductPicker(false);
            }}
            onClose={() => setShowProductPicker(false)}
          />
        )}

        <TextField
          label="Hipoink Item ID (Optional)"
          value={formData.itemId}
          onChange={(value) => setFormData({ ...formData, itemId: value })}
          placeholder="Hipoink internal item ID"
          autoComplete="off"
          helpText="Leave empty if using barcode lookup"
        />

        <TextField
          label="Original Price (Optional)"
          type="number"
          value={formData.originalPrice}
          onChange={(value) =>
            setFormData({ ...formData, originalPrice: value })
          }
          prefix="$"
          autoComplete="off"
        />

        <TextField
          label="Promotional Price"
          type="number"
          value={formData.priceOverride.toString()}
          onChange={(value) =>
            setFormData({ ...formData, priceOverride: parseFloat(value) || 0 })
          }
          prefix="$"
          autoComplete="off"
        />

        <TextField
          label="Promotion Text (Optional)"
          value={formData.promotionText}
          onChange={(value) =>
            setFormData({ ...formData, promotionText: value })
          }
          placeholder="e.g., Limited Time Offer"
          autoComplete="off"
        />

        <Button
          variant="primary"
          loading={isSubmitting}
          onClick={handleSubmit}
          disabled={
            !formData.name ||
            (!formData.barcode && formData.products.length === 0)
          }
        >
          Create Strategy
        </Button>
      </FormLayout>
    </Card>
  );
}
