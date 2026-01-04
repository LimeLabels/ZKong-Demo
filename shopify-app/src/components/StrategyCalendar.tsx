import React, { useState } from "react";
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
} from "@shopify/polaris";
import { CalendarIcon } from "@shopify/polaris-icons";

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
}

export function StrategyCalendar() {
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
    storeMappingId: "fb3a2563-9950-4610-b479-8b76b24bb359", // Default store mapping ID - update with your actual ID
    originalPrice: "",
    barcode: "",
    itemId: "",
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);

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
      // Convert form data to Hipoink price adjustment format
      // Generate unique order number
      const orderNumber = `PA-${Date.now()}`;

      // Map selectedDays to Hipoink format
      // Frontend: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat
      // Hipoink: 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun
      let triggerDays: string[] | undefined = undefined;
      if (
        formData.repeatType === "weekly" &&
        formData.selectedDays.length > 0
      ) {
        triggerDays = formData.selectedDays.map((d) => {
          // Convert frontend day to Hipoink day
          // Frontend 1 (Sun) -> Hipoink 7
          // Frontend 2 (Mon) -> Hipoink 1
          // Frontend 3 (Tue) -> Hipoink 2, etc.
          const hipoinkDay = d === 1 ? 7 : d - 1;
          return hipoinkDay.toString();
        });
      } else if (formData.repeatType === "daily") {
        // Daily = all days (Mon-Sun in Hipoink format)
        triggerDays = ["1", "2", "3", "4", "5", "6", "7"];
      }

      // Get start and end times from first time slot
      let startTime: string | undefined = undefined;
      let endTime: string | undefined = undefined;
      if (formData.timeSlots.length > 0) {
        startTime = formData.timeSlots[0].startTime;
        endTime = formData.timeSlots[0].endTime;
      }

      // Build products array
      const products =
        formData.products.length > 0
          ? formData.products.map((product) => ({
              pc: product.barcode,
              pp: formData.priceOverride.toString(),
            }))
          : [
              {
                pc: formData.barcode,
                pp: formData.priceOverride.toString(),
              },
            ];

      const hipoinkPayload = {
        store_mapping_id: formData.storeMappingId,
        order_number: orderNumber,
        order_name: formData.name,
        products: products,
        trigger_days: triggerDays,
        start_time: startTime,
        end_time: endTime,
      };

      // Call Hipoink price adjustment API
      const response = await fetch("/api/price-adjustments/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(hipoinkPayload),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(
          error.detail || "Failed to create price adjustment order"
        );
      }

      setSubmitSuccess(true);
      // Reset form
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
      }));
    } catch (error: any) {
      setSubmitError(error.message || "An error occurred");
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

  return (
    <Card>
      <FormLayout>
        {submitError && (
          <Banner tone="critical" onDismiss={() => setSubmitError(null)}>
            {submitError}
          </Banner>
        )}

        {submitSuccess && (
          <Banner tone="success" onDismiss={() => setSubmitSuccess(false)}>
            Strategy created successfully!
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

        <TextField
          label="Product Barcode"
          value={formData.barcode}
          onChange={(value) => setFormData({ ...formData, barcode: value })}
          placeholder="Enter product barcode"
          autoComplete="off"
        />

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
