import React, { useEffect, useState } from 'react'
import { Card, ResourceList, ResourceItem, Text, Button, Banner, Spinner, BlockStack, Badge, InlineStack } from '@shopify/polaris'
import { apiClient } from '../services/api'
import { format } from 'date-fns'

interface Schedule {
  id: string
  name: string
  order_number: string
  is_active: boolean
  start_date: string
  end_date: string | null
  repeat_type: string
  next_trigger_at: string | null
  created_at: string
}

export function ScheduleManager() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadSchedules()
  }, [])

  const loadSchedules = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await apiClient.get('/api/price-adjustments/')
      setSchedules(response.data || [])
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load schedules')
    } finally {
      setLoading(false)
    }
  }

  const handleTriggerSchedule = async (scheduleId: string) => {
    try {
      const authToken = localStorage.getItem('auth_token') || prompt('Enter authorization token:')
      if (!authToken) return

      await apiClient.post(
        `/external/trigger-schedule/${scheduleId}`,
        null,
        {
          headers: {
            Authorization: `Bearer ${authToken}`,
          },
        }
      )
      alert('Schedule triggered successfully!')
      loadSchedules()
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message || 'Failed to trigger schedule')
    }
  }

  if (loading) {
    return (
      <BlockStack gap="500">
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <Spinner accessibilityLabel="Loading schedules" size="large" />
        </div>
      </BlockStack>
    )
  }

  return (
    <BlockStack gap="500">
      <InlineStack align="space-between">
        <div>
          <Text variant="headingMd" as="h2">
            Schedule Manager
          </Text>
          <Text as="p" tone="subdued">
            View and manage time-based pricing schedules
          </Text>
        </div>
        <Button onClick={loadSchedules}>
          Refresh
        </Button>
      </InlineStack>

      {error && (
        <Banner tone="critical" title="Error">
          <p>{error}</p>
        </Banner>
      )}

      {schedules.length === 0 ? (
        <Card>
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <Text as="p" tone="subdued">
              No schedules found. Create schedules through the API.
            </Text>
          </div>
        </Card>
      ) : (
        <Card>
          <ResourceList
            resourceName={{ singular: 'schedule', plural: 'schedules' }}
            items={schedules}
            renderItem={(schedule) => {
              const { id, name, order_number, is_active, start_date, next_trigger_at, repeat_type } = schedule
              
              return (
                <ResourceItem
                  id={id}
                  accessibilityLabel={`View details for ${name}`}
                >
                  <InlineStack align="space-between" blockAlign="start">
                    <BlockStack gap="200">
                      <Text variant="bodyMd" fontWeight="bold" as="h3">
                        {name}
                      </Text>
                      <Text variant="bodySm" tone="subdued" as="p">
                        Order: {order_number}
                      </Text>
                      <InlineStack gap="200">
                        <Badge tone={is_active ? 'success' : 'info'}>
                          {is_active ? 'Active' : 'Inactive'}
                        </Badge>
                        <Text variant="bodySm" tone="subdued">
                          {repeat_type || 'none'}
                        </Text>
                      </InlineStack>
                      <Text variant="bodySm" tone="subdued" as="p">
                        Start: {format(new Date(start_date), 'MMM d, yyyy HH:mm')}
                      </Text>
                      {next_trigger_at && (
                        <Text variant="bodySm" tone="subdued" as="p">
                          Next trigger: {format(new Date(next_trigger_at), 'MMM d, yyyy HH:mm')}
                        </Text>
                      )}
                    </BlockStack>
                    <Button
                      onClick={() => handleTriggerSchedule(id)}
                      size="slim"
                    >
                      Trigger
                    </Button>
                  </InlineStack>
                </ResourceItem>
              )
            }}
          />
        </Card>
      )}
    </BlockStack>
  )
}
