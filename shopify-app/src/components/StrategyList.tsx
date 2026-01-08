import React, { useState, useEffect } from "react";
import {
  Card,
  ResourceList,
  ResourceItem,
  Text,
  Button,
  Banner,
  EmptyState,
  Spinner,
  Modal,
  TextField,
  FormLayout,
  Select,
  DatePicker,
  Checkbox,
  Badge,
} from "@shopify/polaris";
import { useStoreMapping } from "../hooks/useStoreMapping";
import { useShopifyAuth } from "../hooks/useShopifyAuth";

interface TimeSlot {
  start_time: string;
  end_time: string;
}

interface Strategy {
  id: string;
  name: string;
  order_number: string;
  is_active: boolean;
  next_trigger_at: string | null;
  created_at: string;
  start_date: string;
  end_date: string | null;
  repeat_type: string;
  trigger_days: string[] | null;
  time_slots: TimeSlot[];
  products: {
    products: Array<{
      pc: string;
      pp: string;
      original_price: number | null;
    }>;
  };
}

export function StrategyList() {
  const auth = useShopifyAuth();
  const { storeMapping, isLoading: isLoadingMapping } = useStoreMapping();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
  const [showEditModal, setShowEditModal] = useState(false);

  useEffect(() => {
    if (!storeMapping?.id) {
      setIsLoading(false);
      return;
    }

    fetchStrategies();
  }, [storeMapping]);

  const fetchStrategies = async () => {
    if (!storeMapping?.id) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `/api/price-adjustments/?store_mapping_id=${storeMapping.id}`
      );

      if (!response.ok) {
        throw new Error("Failed to fetch strategies");
      }

      const data = await response.json();
      setStrategies(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (strategyId: string) => {
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
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error occurred";
      setError(errorMessage);
      console.error("Failed to delete strategy", err);
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString();
  };

  const formatTime = (timeString: string) => {
    const [hours, minutes] = timeString.split(":");
    const hour = parseInt(hours);
    const ampm = hour >= 12 ? "PM" : "AM";
    const displayHour = hour % 12 || 12;
    return `${displayHour}:${minutes} ${ampm}`;
  };

  if (isLoadingMapping || isLoading) {
    return <Spinner accessibilityLabel="Loading strategies" size="large" />;
  }

  if (!storeMapping?.id) {
    return (
      <Banner tone="warning" title="Store mapping not found">
        <p>Please complete onboarding to manage pricing strategies.</p>
      </Banner>
    );
  }

  if (error) {
    return (
      <Banner tone="critical" onDismiss={() => setError(null)}>
        {error}
      </Banner>
    );
  }

  return (
    <Card>
      <ResourceList
        resourceName={{ singular: "strategy", plural: "strategies" }}
        items={strategies}
        emptyState={
          <EmptyState
            heading="No pricing strategies yet"
            image="https://cdn.shopify.com/s/files/1/0757/9955/files/empty-state.svg"
          >
            <p>Create your first pricing strategy to get started.</p>
          </EmptyState>
        }
        renderItem={(item) => {
          const strategy = item as Strategy;
          const productCount = strategy.products?.products?.length || 0;
          const firstTimeSlot = strategy.time_slots?.[0];

          return (
            <ResourceItem
              id={strategy.id}
              accessibilityLabel={`View details for ${strategy.name}`}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                <div>
                  <Text variant="bodyMd" fontWeight="bold" as="h3">
                    {strategy.name}
                  </Text>
                  <Text variant="bodySm" as="p">
                    Order: {strategy.order_number}
                  </Text>
                  <Text variant="bodySm" as="p">
                    Products: {productCount}
                  </Text>
                  {firstTimeSlot && (
                    <Text variant="bodySm" as="p">
                      Time: {formatTime(firstTimeSlot.start_time)} - {formatTime(firstTimeSlot.end_time)}
                    </Text>
                  )}
                  <Text variant="bodySm" as="p">
                    Repeat: {strategy.repeat_type === "none" ? "Once" : strategy.repeat_type}
                  </Text>
                  {strategy.next_trigger_at && (
                    <Text variant="bodySm" as="p">
                      Next trigger: {formatDate(strategy.next_trigger_at)}
                    </Text>
                  )}
                  <div style={{ marginTop: "0.5rem" }}>
                    <Badge status={strategy.is_active ? "success" : "attention"}>
                      {strategy.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                </div>
                <div>
                  <Button
                    plain
                    onClick={() => {
                      setSelectedStrategy(strategy);
                      setShowEditModal(true);
                    }}
                  >
                    View
                  </Button>
                  <Button
                    plain
                    destructive
                    onClick={() => handleDelete(strategy.id)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </ResourceItem>
          );
        }}
      />

      {showEditModal && selectedStrategy && (
        <Modal
          open={true}
          onClose={() => {
            setShowEditModal(false);
            setSelectedStrategy(null);
          }}
          title={selectedStrategy.name}
          primaryAction={{
            content: "Close",
            onAction: () => {
              setShowEditModal(false);
              setSelectedStrategy(null);
            },
          }}
        >
          <Modal.Section>
            <FormLayout>
              <TextField label="Name" value={selectedStrategy.name} readOnly />
              <TextField label="Order Number" value={selectedStrategy.order_number} readOnly />
              <Text variant="bodySm" as="p">
                <strong>Status:</strong> {selectedStrategy.is_active ? "Active" : "Inactive"}
              </Text>
              <Text variant="bodySm" as="p">
                <strong>Products:</strong> {selectedStrategy.products?.products?.length || 0}
              </Text>
              <Text variant="bodySm" as="p">
                <strong>Repeat Type:</strong> {selectedStrategy.repeat_type}
              </Text>
              {selectedStrategy.next_trigger_at && (
                <Text variant="bodySm" as="p">
                  <strong>Next Trigger:</strong> {new Date(selectedStrategy.next_trigger_at).toLocaleString()}
                </Text>
              )}
              {selectedStrategy.time_slots && selectedStrategy.time_slots.length > 0 && (
                <div>
                  <Text variant="bodySm" as="p">
                    <strong>Time Slots:</strong>
                  </Text>
                  {selectedStrategy.time_slots.map((slot, idx) => (
                    <Text key={idx} variant="bodySm" as="p">
                      {formatTime(slot.start_time)} - {formatTime(slot.end_time)}
                    </Text>
                  ))}
                </div>
              )}
            </FormLayout>
          </Modal.Section>
        </Modal>
      )}
    </Card>
  );
}
