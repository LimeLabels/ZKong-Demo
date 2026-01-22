import { useEffect, useState } from 'react'
import {
  Card,
  ResourceList,
  ResourceItem,
  Text,
  Button,
  Banner,
  Spinner,
  Modal,
  Badge,
  BlockStack,
  InlineStack,
} from '@shopify/polaris'
import { apiClient } from '../services/api'
import { format } from 'date-fns'

interface TimeSlot {
  start_time: string
  end_time: string
}

interface Schedule {
  id: string
  name: string
  order_number: string
  is_active: boolean
  start_date: string
  end_date: string | null
  repeat_type: string
  trigger_days: string[] | null
  time_slots: TimeSlot[]
  next_trigger_at: string | null
  created_at: string
  products: {
    products: Array<{
      pc: string
      pp: string
      original_price: number | null
    }>
  }
}

export function ScheduleList() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null)
  const [showDetailsModal, setShowDetailsModal] = useState(false)

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

  const handleDelete = async (scheduleId: string) => {
    if (
      !confirm(
        'Are you sure you want to delete this schedule? This will stop all scheduled price adjustments.'
      )
    ) {
      return
    }

    setLoading(true)
    setError(null)

    try {
      await apiClient.delete(`/api/price-adjustments/${scheduleId}`)
      await loadSchedules()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete schedule')
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

  const formatTime = (timeString: string) => {
    const [hours, minutes] = timeString.split(':')
    const hour = parseInt(hours)
    const ampm = hour >= 12 ? 'PM' : 'AM'
    const displayHour = hour % 12 || 12
    return `${displayHour}:${minutes} ${ampm}`
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem' }}>
        <Spinner accessibilityLabel="Loading schedules" size="large" />
      </div>
    )
  }

  return (
    <BlockStack gap="500">
      <InlineStack align="space-between">
        <div>
          <Text variant="headingMd" as="h2">
            Manage Schedules
          </Text>
          <Text as="p" tone="subdued">
            View and manage your time-based pricing schedules
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
              No schedules found. Create a new schedule using the "Create Schedule" tab.
            </Text>
          </div>
        </Card>
      ) : (
        <Card>
          <ResourceList
            resourceName={{ singular: 'schedule', plural: 'schedules' }}
            items={schedules}
            renderItem={(schedule) => {
              const {
                id,
                name,
                order_number,
                is_active,
                start_date,
                next_trigger_at,
                repeat_type,
                time_slots,
              } = schedule

              return (
                <ResourceItem
                  id={id}
                  accessibilityLabel={`View details for ${name}`}
                  onClick={() => {
                    setSelectedSchedule(schedule)
                    setShowDetailsModal(true)
                  }}
                >
                  <InlineStack align="space-between" blockAlign="start">
                    <BlockStack gap="200">
                      <InlineStack gap="200" blockAlign="center">
                        <Text variant="bodyMd" fontWeight="bold" as="h3">
                          {name}
                        </Text>
                        <Badge tone={is_active ? 'success' : 'info'}>
                          {is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </InlineStack>
                      <Text variant="bodySm" tone="subdued" as="p">
                        Order: {order_number} • {repeat_type || 'none'} repeat
                      </Text>
                      <Text variant="bodySm" tone="subdued" as="p">
                        Start: {format(new Date(start_date), 'MMM d, yyyy')}
                      </Text>
                      {time_slots && time_slots.length > 0 && (
                        <Text variant="bodySm" tone="subdued" as="p">
                          Times: {time_slots.map((slot) => `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}`).join(', ')}
                        </Text>
                      )}
                      {next_trigger_at && (
                        <Text variant="bodySm" tone="subdued" as="p">
                          Next trigger: {format(new Date(next_trigger_at), 'MMM d, yyyy HH:mm')}
                        </Text>
                      )}
                    </BlockStack>
                    <InlineStack gap="200">
                      <Button
                        onClick={() => {
                          handleTriggerSchedule(id)
                        }}
                        size="slim"
                      >
                        Trigger
                      </Button>
                      <Button
                        onClick={() => {
                          handleDelete(id)
                        }}
                        tone="critical"
                        size="slim"
                      >
                        Delete
                      </Button>
                    </InlineStack>
                  </InlineStack>
                </ResourceItem>
              )
            }}
          />
        </Card>
      )}

      {selectedSchedule && (
        <Modal
          open={showDetailsModal}
          onClose={() => {
            setShowDetailsModal(false)
            setSelectedSchedule(null)
          }}
          title={selectedSchedule.name}
          primaryAction={{
            content: 'Close',
            onAction: () => {
              setShowDetailsModal(false)
              setSelectedSchedule(null)
            },
          }}
        >
          <Modal.Section>
            <BlockStack gap="300">
              <div>
                <Text variant="headingSm" as="h3">Details</Text>
                <BlockStack gap="200">
                  <Text as="p">
                    <Text as="span" fontWeight="bold">Order Number:</Text> {selectedSchedule.order_number}
                  </Text>
                  <Text as="p">
                    <Text as="span" fontWeight="bold">Status:</Text>{' '}
                    <Badge tone={selectedSchedule.is_active ? 'success' : 'info'}>
                      {selectedSchedule.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </Text>
                  <Text as="p">
                    <Text as="span" fontWeight="bold">Repeat Type:</Text> {selectedSchedule.repeat_type || 'none'}
                  </Text>
                  <Text as="p">
                    <Text as="span" fontWeight="bold">Start Date:</Text>{' '}
                    {format(new Date(selectedSchedule.start_date), 'MMM d, yyyy HH:mm')}
                  </Text>
                  {selectedSchedule.end_date && (
                    <Text as="p">
                      <Text as="span" fontWeight="bold">End Date:</Text>{' '}
                      {format(new Date(selectedSchedule.end_date), 'MMM d, yyyy HH:mm')}
                    </Text>
                  )}
                  {selectedSchedule.next_trigger_at && (
                    <Text as="p">
                      <Text as="span" fontWeight="bold">Next Trigger:</Text>{' '}
                      {format(new Date(selectedSchedule.next_trigger_at), 'MMM d, yyyy HH:mm')}
                    </Text>
                  )}
                </BlockStack>
              </div>

              {selectedSchedule.time_slots && selectedSchedule.time_slots.length > 0 && (
                <div>
                  <Text variant="headingSm" as="h3">Time Slots</Text>
                  <BlockStack gap="200">
                    {selectedSchedule.time_slots.map((slot, index) => (
                      <Text key={index} as="p">
                        {formatTime(slot.start_time)} - {formatTime(slot.end_time)}
                      </Text>
                    ))}
                  </BlockStack>
                </div>
              )}

              {selectedSchedule.products?.products && selectedSchedule.products.products.length > 0 && (
                <div>
                  <Text variant="headingSm" as="h3">Products</Text>
                  <BlockStack gap="200">
                    {selectedSchedule.products.products.map((product, index) => (
                      <Text key={index} as="p">
                        <Text as="span" fontWeight="bold">Item:</Text> {product.pc} •{' '}
                        <Text as="span" fontWeight="bold">Price:</Text> ${product.pp}
                        {product.original_price && (
                          <Text as="span" tone="subdued">
                            {' '}(Original: ${product.original_price.toFixed(2)})
                          </Text>
                        )}
                      </Text>
                    ))}
                  </BlockStack>
                </div>
              )}
            </BlockStack>
          </Modal.Section>
        </Modal>
      )}
    </BlockStack>
  )
}

