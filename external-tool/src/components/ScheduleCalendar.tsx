import { useState } from 'react'
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
  BlockStack,
  InlineStack,
} from '@shopify/polaris'
import { CalendarIcon } from '@shopify/polaris-icons'
import { apiClient } from '../services/api'

interface ScheduleTimeSlot {
  startTime: string
  endTime: string
}

interface ScheduleFormData {
  platform: 'ncr' | 'square' | ''
  name: string
  startDate: Date
  endDate: Date
  repeatType: 'none' | 'daily' | 'weekly' | 'monthly'
  selectedDays: number[]
  timeSlots: ScheduleTimeSlot[]
  storeMappingId: string
  itemCode: string
  objectId: string // For Square
  price: number
  originalPrice: number
  multiplierPercentage: number | null
}

export function ScheduleCalendar() {
  const [formData, setFormData] = useState<ScheduleFormData>({
    platform: '',
    name: '',
    startDate: new Date(),
    endDate: new Date(),
    repeatType: 'none',
    selectedDays: [],
    timeSlots: [{ startTime: '09:00', endTime: '17:00' }],
    storeMappingId: '',
    itemCode: '',
    objectId: '',
    price: 0,
    originalPrice: 0,
    multiplierPercentage: null,
  })

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  const platformOptions = [
    { label: 'Select Platform', value: '' },
    { label: 'NCR POS', value: 'ncr' },
    { label: 'Square', value: 'square' },
  ]

  const repeatOptions = [
    { label: 'No Repeat', value: 'none' },
    { label: 'Daily', value: 'daily' },
    { label: 'Weekly', value: 'weekly' },
    { label: 'Monthly', value: 'monthly' },
  ]

  const dayOptions = [
    { label: 'Sunday', value: '1' },
    { label: 'Monday', value: '2' },
    { label: 'Tuesday', value: '3' },
    { label: 'Wednesday', value: '4' },
    { label: 'Thursday', value: '5' },
    { label: 'Friday', value: '6' },
    { label: 'Saturday', value: '7' },
  ]

  const handleSubmit = async () => {
    setIsSubmitting(true)
    setSubmitError(null)
    setSubmitSuccess(false)

    try {
      // Validate required fields
      if (!formData.platform) {
        throw new Error('Platform selection is required')
      }

      if (!formData.name.trim()) {
        throw new Error('Schedule name is required')
      }

      if (!formData.storeMappingId.trim()) {
        throw new Error('Store Mapping ID is required')
      }

      if (formData.platform === 'ncr' && !formData.itemCode.trim()) {
        throw new Error('Item Code is required for NCR')
      }

      if (formData.platform === 'square' && !formData.objectId.trim()) {
        throw new Error('Object ID is required for Square')
      }

      if (formData.timeSlots.length === 0) {
        throw new Error('At least one time slot is required')
      }

      // Prepare products array
      // Use itemCode for NCR, objectId for Square (but API expects pc/barcode)
      const productCode = formData.platform === 'ncr' ? formData.itemCode : formData.objectId
      
      const products = [
        {
          pc: productCode,
          pp: formData.multiplierPercentage !== null
            ? (formData.originalPrice * (1 + formData.multiplierPercentage / 100)).toFixed(2)
            : formData.price.toFixed(2),
          original_price: formData.originalPrice || formData.price,
        },
      ]

      // Prepare time slots
      const timeSlots = formData.timeSlots.map((slot) => ({
        start_time: slot.startTime,
        end_time: slot.endTime,
      }))

      // Prepare request payload
      const payload = {
        store_mapping_id: formData.storeMappingId,
        name: formData.name,
        products: products,
        start_date: formData.startDate.toISOString(),
        end_date: formData.endDate.toISOString(),
        repeat_type: formData.repeatType,
        trigger_days: formData.repeatType === 'weekly' ? formData.selectedDays.map(String) : null,
        time_slots: timeSlots,
        multiplier_percentage: formData.multiplierPercentage,
      }

      await apiClient.post('/api/price-adjustments/create', payload)

      setSubmitSuccess(true)
      
      // Reset form
      setFormData({
        platform: formData.platform, // Keep platform selection
        name: '',
        startDate: new Date(),
        endDate: new Date(),
        repeatType: 'none',
        selectedDays: [],
        timeSlots: [{ startTime: '09:00', endTime: '17:00' }],
        storeMappingId: formData.storeMappingId, // Keep store mapping ID
        itemCode: '',
        objectId: '',
        price: 0,
        originalPrice: 0,
        multiplierPercentage: null,
      })
    } catch (err: any) {
      setSubmitError(err.response?.data?.detail || err.message || 'Failed to create schedule')
    } finally {
      setIsSubmitting(false)
    }
  }

  const addTimeSlot = () => {
    setFormData((prev) => ({
      ...prev,
      timeSlots: [...prev.timeSlots, { startTime: '09:00', endTime: '17:00' }],
    }))
  }

  const removeTimeSlot = (index: number) => {
    setFormData((prev) => ({
      ...prev,
      timeSlots: prev.timeSlots.filter((_, i) => i !== index),
    }))
  }

  const updateTimeSlot = (index: number, field: 'startTime' | 'endTime', value: string) => {
    setFormData((prev) => ({
      ...prev,
      timeSlots: prev.timeSlots.map((slot, i) =>
        i === index ? { ...slot, [field]: value } : slot
      ),
    }))
  }

  const toggleDay = (dayValue: string) => {
    const dayNum = parseInt(dayValue)
    setFormData((prev) => ({
      ...prev,
      selectedDays: prev.selectedDays.includes(dayNum)
        ? prev.selectedDays.filter((d) => d !== dayNum)
        : [...prev.selectedDays, dayNum],
    }))
  }

  return (
    <BlockStack gap="500">
      <Card>
        <FormLayout>
          <Select
            label="Platform"
            options={platformOptions}
            value={formData.platform}
            onChange={(value) =>
              setFormData((prev) => ({
                ...prev,
                platform: value as 'ncr' | 'square' | '',
                itemCode: '', // Clear when platform changes
                objectId: '', // Clear when platform changes
              }))
            }
            helpText="Select the platform (NCR POS or Square) for this pricing schedule"
          />

          {formData.platform && (
            <>
              <TextField
                label="Schedule Name"
                value={formData.name}
                onChange={(value) => setFormData((prev) => ({ ...prev, name: value }))}
                placeholder="Evening Flash Sale"
                helpText="A descriptive name for this pricing schedule"
                autoComplete="off"
              />

              <TextField
                label="Store Mapping ID"
                value={formData.storeMappingId}
                onChange={(value) => setFormData((prev) => ({ ...prev, storeMappingId: value }))}
                placeholder="uuid-here"
                helpText="The store mapping UUID from your backend"
                autoComplete="off"
              />

              {formData.platform === 'ncr' && (
                <TextField
                  label="Item Code"
                  value={formData.itemCode}
                  onChange={(value) => setFormData((prev) => ({ ...prev, itemCode: value }))}
                  placeholder="ITEM-001"
                  helpText="The item code (barcode) for the NCR product"
                  autoComplete="off"
                />
              )}

              {formData.platform === 'square' && (
                <TextField
                  label="Object ID"
                  value={formData.objectId}
                  onChange={(value) => setFormData((prev) => ({ ...prev, objectId: value }))}
                  placeholder="catalog-object-id"
                  helpText="The catalog object ID for the Square product"
                  autoComplete="off"
                />
              )}
            </>
          )}

          {formData.platform && (
            <FormLayout.Group>
              <TextField
                label="Original Price"
                type="number"
                value={formData.originalPrice.toString()}
                onChange={(value) =>
                  setFormData((prev) => ({ ...prev, originalPrice: parseFloat(value) || 0 }))
                }
                prefix="$"
                helpText="Current price of the product"
                autoComplete="off"
              />

            <Select
              label="Price Adjustment"
              options={[
                { label: 'Set Specific Price', value: 'fixed' },
                { label: 'Percentage Change', value: 'percentage' },
              ]}
              value={formData.multiplierPercentage !== null ? 'percentage' : 'fixed'}
              onChange={(value) => {
                if (value === 'percentage') {
                  setFormData((prev) => ({ ...prev, multiplierPercentage: 0, price: 0 }))
                } else {
                  setFormData((prev) => ({ ...prev, multiplierPercentage: null, price: prev.originalPrice }))
                }
              }}
            />
            </FormLayout.Group>
          )}

          {formData.platform && formData.multiplierPercentage !== null ? (
            <TextField
              label="Percentage Change"
              type="number"
              value={formData.multiplierPercentage.toString()}
              onChange={(value) =>
                setFormData((prev) => ({
                  ...prev,
                  multiplierPercentage: parseFloat(value) || 0,
                }))
              }
              suffix="%"
              helpText="Positive for increase, negative for decrease (e.g., 10 for 10% increase, -5 for 5% decrease)"
              autoComplete="off"
            />
          ) : formData.platform ? (
            <TextField
              label="Promotional Price"
              type="number"
              value={formData.price.toString()}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, price: parseFloat(value) || 0 }))
              }
              prefix="$"
              helpText="The price during the promotion"
              autoComplete="off"
            />
          ) : null}

          {formData.platform && (
            <>
              <FormLayout.Group>
                <DatePicker
                  month={formData.startDate.getMonth()}
                  year={formData.startDate.getFullYear()}
                  selected={formData.startDate}
                  onMonthChange={(month, year) =>
                    setFormData((prev) => {
                      const newDate = new Date(year, month, prev.startDate.getDate())
                      return { ...prev, startDate: newDate }
                    })
                  }
                  onChange={(range) => {
                    const startDate = new Date(range.start)
                    setFormData((prev) => ({ ...prev, startDate }))
                  }}
                />

                <DatePicker
                  month={formData.endDate.getMonth()}
                  year={formData.endDate.getFullYear()}
                  selected={formData.endDate}
                  onMonthChange={(month, year) =>
                    setFormData((prev) => {
                      const newDate = new Date(year, month, prev.endDate.getDate())
                      return { ...prev, endDate: newDate }
                    })
                  }
                  onChange={(range) => {
                    const endDate = new Date(range.start)
                    setFormData((prev) => ({ ...prev, endDate }))
                  }}
                />
              </FormLayout.Group>

              <Select
                label="Repeat Type"
                options={repeatOptions}
                value={formData.repeatType}
                onChange={(value) =>
                  setFormData((prev) => ({
                    ...prev,
                    repeatType: value as 'none' | 'daily' | 'weekly' | 'monthly',
                    selectedDays: value !== 'weekly' ? [] : prev.selectedDays,
                  }))
                }
              />
            </>
          )}

          {formData.platform && formData.repeatType === 'weekly' && (
            <Card>
              <BlockStack gap="300">
                <Text variant="headingSm" as="h3">
                  Select Days of Week
                </Text>
                <FormLayout>
                  {dayOptions.map((day) => (
                    <Checkbox
                      key={day.value}
                      label={day.label}
                      checked={formData.selectedDays.includes(parseInt(day.value))}
                      onChange={() => toggleDay(day.value)}
                    />
                  ))}
                </FormLayout>
            </BlockStack>
          </Card>
          )}

          {formData.platform && (
            <Card>
              <BlockStack gap="300">
                <InlineStack align="space-between">
                  <Text variant="headingSm" as="h3">
                    Time Slots
                  </Text>
                  <Button onClick={addTimeSlot} size="slim">
                    Add Time Slot
                  </Button>
                </InlineStack>

              {formData.timeSlots.map((slot, index) => (
                <FormLayout.Group key={index}>
                  <TextField
                    label="Start Time"
                    type="time"
                    value={slot.startTime}
                    onChange={(value) => updateTimeSlot(index, 'startTime', value)}
                    autoComplete="off"
                  />
                  <TextField
                    label="End Time"
                    type="time"
                    value={slot.endTime}
                    onChange={(value) => updateTimeSlot(index, 'endTime', value)}
                    autoComplete="off"
                  />
                  {formData.timeSlots.length > 1 && (
                    <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: '0.5rem' }}>
                      <Button
                        onClick={() => removeTimeSlot(index)}
                        tone="critical"
                        size="slim"
                      >
                        Remove
                      </Button>
                    </div>
                  )}
                </FormLayout.Group>
              ))}
              </BlockStack>
            </Card>
          )}

          {submitError && (
            <Banner tone="critical" title="Error">
              <p>{submitError}</p>
            </Banner>
          )}

          {submitSuccess && (
            <Banner tone="success" title="Schedule Created">
              <p>Your pricing schedule has been created successfully!</p>
            </Banner>
          )}

          {formData.platform && (
            <Button
              variant="primary"
              onClick={handleSubmit}
              loading={isSubmitting}
              icon={CalendarIcon}
            >
              Create Schedule
            </Button>
          )}

          {!formData.platform && (
            <Banner tone="info" title="Select Platform">
              <p>Please select a platform (NCR POS or Square) to continue creating a schedule.</p>
            </Banner>
          )}
        </FormLayout>
      </Card>
    </BlockStack>
  )
}

