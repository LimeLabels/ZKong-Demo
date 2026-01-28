import { useState, useEffect } from 'react'
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
  Spinner,
} from '@shopify/polaris'
import { CalendarIcon } from '@shopify/polaris-icons'
import { apiClient } from '../services/api'
import { useUserStore } from '../hooks/useUserStore'

interface Product {
  id: string
  title: string
  barcode: string | null
  sku: string | null
  price: number | null
  image_url: string | null
  variant_id: string | null
  product_id: string | null
}

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
  const { store, stores, switchStore, loading: storeLoading } = useUserStore()
  
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

  const [products, setProducts] = useState<Product[]>([])
  const [productsLoading, setProductsLoading] = useState(false)
  const [productSearchQuery, setProductSearchQuery] = useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  const [selectedProductIds, setSelectedProductIds] = useState<Set<string>>(new Set())
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // Debounce search query (300ms) for server-side search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(productSearchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [productSearchQuery])

  // When Square or NCR search query changes, clear selection so it reflects the new result set
  useEffect(() => {
    if (formData.platform === 'square' || formData.platform === 'ncr') {
      setSelectedProductIds(new Set())
    }
  }, [debouncedSearchQuery, formData.platform])

  // Auto-populate store mapping ID and platform when store is loaded or switched
  useEffect(() => {
    if (store) {
      setFormData((prev) => {
        const updates: Partial<ScheduleFormData> = {
          storeMappingId: store.id,
        }
        
        // Auto-set platform based on store's source system
        // Map source_system to platform value (ncr, square, shopify)
        if (store.source_system) {
          const systemMap: Record<string, 'ncr' | 'square' | ''> = {
            'ncr': 'ncr',
            'square': 'square',
            'shopify': 'square', // Shopify uses similar structure to Square
          }
          const platform = systemMap[store.source_system.toLowerCase()] || ''
          if (platform) {
            updates.platform = platform
          }
        }
        
        return { ...prev, ...updates }
      })
      
      // Reset product selection when store changes
      setSelectedProductIds(new Set())
      setProductSearchQuery('')
    }
  }, [store])

  /**
   * Fetch products for the user's store. Square and NCR: server-side search via q + debounce for the multi-select table.
   */
  useEffect(() => {
    const fetchProducts = async () => {
      if (!store || !formData.platform) {
        setProducts([])
        return
      }

      try {
        setProductsLoading(true)
        const params: { limit: number; q?: string } = { limit: 100 }
        if (
          (formData.platform === 'square' || formData.platform === 'ncr') &&
          debouncedSearchQuery.trim()
        ) {
          params.q = debouncedSearchQuery.trim()
        }
        const response = await apiClient.get('/api/products/my-products', { params })
        setProducts(response.data || [])
      } catch (error: unknown) {
        console.error('Error fetching products:', error)
        setProducts([])
      } finally {
        setProductsLoading(false)
      }
    }

    if (store && formData.platform) {
      fetchProducts()
    }
  }, [store, formData.platform, debouncedSearchQuery])

  // When Square or NCR and user selects 2+ products, default to percentage mode (hide "Set Specific Price")
  useEffect(() => {
    const multiSelectPlatform =
      formData.platform === 'square' || formData.platform === 'ncr'
    if (
      multiSelectPlatform &&
      selectedProductIds.size > 1 &&
      formData.multiplierPercentage === null
    ) {
      setFormData((prev) => ({ ...prev, multiplierPercentage: 0 }))
    }
  }, [formData.platform, formData.multiplierPercentage, selectedProductIds.size])

  // When Square or NCR and exactly one product selected, sync originalPrice/price from that product
  useEffect(() => {
    const multiSelectPlatform =
      formData.platform === 'square' || formData.platform === 'ncr'
    if (!multiSelectPlatform || selectedProductIds.size !== 1) return
    const id = Array.from(selectedProductIds)[0]
    const product = products.find((p) => p.id === id)
    if (product && product.price != null) {
      setFormData((prev) => {
        if (prev.originalPrice === product.price && prev.price === product.price) return prev
        return { ...prev, originalPrice: product.price, price: product.price }
      })
    }
  }, [formData.platform, products, selectedProductIds])

  const isMultiSelectPlatform =
    formData.platform === 'square' || formData.platform === 'ncr'

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

      if (
        (formData.platform === 'square' || formData.platform === 'ncr') &&
        selectedProductIds.size === 0
      ) {
        throw new Error('Select at least one product')
      }

      if (formData.timeSlots.length === 0) {
        throw new Error('At least one time slot is required')
      }

      // Prepare products array: Square and NCR both use multi-select; pc differs by platform
      const selectedProducts = products.filter((p) => selectedProductIds.has(p.id))
      const productsPayload: Array<{ pc: string; pp: string; original_price: number }> =
        selectedProducts.map((p) => {
          const pc =
            formData.platform === 'square'
              ? (p.variant_id || p.product_id || '')
              : (p.barcode || p.sku || '')
          const pp =
            formData.multiplierPercentage !== null
              ? ((p.price ?? 0) * (1 + formData.multiplierPercentage / 100)).toFixed(2)
              : formData.price.toFixed(2)
          const original_price = p.price ?? formData.originalPrice ?? 0
          return { pc, pp, original_price }
        })

      // Prepare time slots - convert to 24-hour format (matching Shopify pattern)
      const timeSlots = formData.timeSlots.map((slot) => ({
        start_time: slot.startTime,
        end_time: slot.endTime,
      }))

      // Validate dates
      if (isNaN(formData.startDate.getTime())) {
        throw new Error('Invalid start date')
      }
      if (isNaN(formData.endDate.getTime())) {
        throw new Error('Invalid end date')
      }
      if (formData.endDate < formData.startDate) {
        throw new Error('End date must be after start date')
      }

      // Build payload - match Shopify's pattern of only including optional fields when set
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const payload: any = {
        store_mapping_id: formData.storeMappingId,
        name: formData.name,
        products: productsPayload,
        start_date: formData.startDate.toISOString(),
        repeat_type: formData.repeatType,
        time_slots: timeSlots,
      }

      // Add optional fields only if they have meaningful values
      if (formData.endDate) {
        payload.end_date = formData.endDate.toISOString()
      }
      
      // Only add trigger_days for weekly repeats when days are selected
      if (formData.repeatType === 'weekly' && formData.selectedDays.length > 0) {
        payload.trigger_days = formData.selectedDays.map(String)
      }
      
      // Add multiplier_percentage if provided
      if (formData.multiplierPercentage !== null) {
        payload.multiplier_percentage = formData.multiplierPercentage
      }
      
      console.log('Submitting payload:', payload)

      const response = await apiClient.post('/api/price-adjustments/create', payload)
      
      console.log('Schedule created successfully:', response.data)

      setSubmitSuccess(true)
      setSubmitError(null)
      
      // Reset form after a short delay to show success message
      setSelectedProductIds(new Set())
      setProductSearchQuery('')
      setTimeout(() => {
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
        setSubmitSuccess(false)
      }, 3000)
    } catch (err: any) {
      console.error('Error creating schedule:', err)
      console.error('Error response:', err.response?.data)
      
      // Handle different error formats
      let errorMessage = 'Failed to create schedule'
      
      try {
        if (err.response?.data) {
          if (typeof err.response.data.detail === 'string') {
            errorMessage = err.response.data.detail
          } else if (Array.isArray(err.response.data.detail)) {
            // Pydantic validation errors
            const errors = err.response.data.detail.map((e: any) => {
              const field = e.loc?.join('.') || 'unknown'
              return `${field}: ${e.msg || e.message || 'Invalid value'}`
            })
            errorMessage = errors.join('; ')
          } else if (err.response.data.detail) {
            // If detail is an object, stringify it safely
            errorMessage = typeof err.response.data.detail === 'object' 
              ? JSON.stringify(err.response.data.detail, null, 2)
              : String(err.response.data.detail)
          }
        } else if (err.message) {
          errorMessage = String(err.message)
        }
      } catch (parseError) {
        // Fallback if error parsing fails
        errorMessage = `Error: ${err.message || 'Unknown error occurred'}`
      }
      
      setSubmitError(String(errorMessage))
      setSubmitSuccess(false)
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

  if (storeLoading) {
    return (
      <Card>
        <BlockStack gap="400" align="center">
          <Spinner size="large" />
          <Text variant="bodyMd" tone="subdued" as="p">
            Loading store information...
          </Text>
        </BlockStack>
      </Card>
    )
  }

  if (!store) {
    return (
      <Card>
        <Banner tone="critical" title="No Store Connected">
          <Text as="p">
            Please connect a store in the onboarding section before creating schedules.
          </Text>
        </Banner>
      </Card>
    )
  }

  return (
    <BlockStack gap="500">
      <Card>
        <FormLayout>
          {/* Store Selector - show when user has multiple stores */}
          {stores.length > 1 && (
            <Select
              label="Select Store"
              options={stores.map((s) => ({
                label: `${s.store_name || s.source_store_id} (${s.source_system})`,
                value: s.id,
              }))}
              value={store?.id || ''}
              onChange={(value) => switchStore(value)}
              helpText="Switch between your connected stores"
            />
          )}

          {store && (
            <Banner tone="info" title="Store Connected">
              <Text as="p">
                Managing schedules for: <strong>{store.source_store_id}</strong> ({store.source_system})
              </Text>
            </Banner>
          )}

          {/* Platform is auto-set from store, show as read-only info */}
          {formData.platform && (
            <Banner tone="info">
              <Text as="p">
                Platform: <strong>{formData.platform.toUpperCase()}</strong> (automatically set from your store)
              </Text>
            </Banner>
          )}

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
                helpText="Automatically set to your connected store"
                autoComplete="off"
                disabled={!!store}
              />

              {/* Square and NCR: search + multi-select product table (data-product-ui="multiselect" = new build) */}
              {(formData.platform === 'square' || formData.platform === 'ncr') && (
                <div data-product-ui="multiselect" style={{ display: 'contents' }}>
                  <TextField
                    label="Search products"
                    value={productSearchQuery}
                    onChange={setProductSearchQuery}
                    placeholder="Search by name, barcode, or SKU"
                    autoComplete="off"
                    disabled={isSubmitting}
                  />
                  {productsLoading && (
                    <Banner tone="info">
                      <Text as="p">Loading products...</Text>
                    </Banner>
                  )}
                  {!productsLoading && products.length === 0 && (
                    <Banner tone="info">
                      <Text as="p">No products found. Try a different search.</Text>
                    </Banner>
                  )}
                  {!productsLoading && products.length > 0 && (
                    <div style={{ border: '1px solid #e1e3e5', borderRadius: '8px', overflow: 'hidden' }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          padding: '12px 16px',
                          borderBottom: '1px solid #e1e3e5',
                          backgroundColor: 'var(--p-color-bg-surface-secondary)',
                        }}
                      >
                        <div style={{ marginRight: 12 }} onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            label=""
                            labelHidden
                            checked={
                              products.length > 0 &&
                              products.every((p) => selectedProductIds.has(p.id))
                            }
                            onChange={() => {
                              if (products.every((p) => selectedProductIds.has(p.id))) {
                                setSelectedProductIds(new Set())
                              } else {
                                setSelectedProductIds(new Set(products.map((p) => p.id)))
                              }
                            }}
                          />
                        </div>
                        <span style={{ flex: 1 }}>
                          <Text as="span" variant="bodySm" fontWeight="semibold">
                            Item
                          </Text>
                        </span>
                        <Text as="span" variant="bodySm" fontWeight="semibold">
                          Price
                        </Text>
                      </div>
                      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                        {products.map((product) => (
                          <div
                            key={product.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              padding: '12px 16px',
                              borderBottom: '1px solid #e1e3e5',
                            }}
                          >
                            <div style={{ marginRight: 12 }} onClick={(e) => e.stopPropagation()}>
                              <Checkbox
                                label=""
                                labelHidden
                                checked={selectedProductIds.has(product.id)}
                                onChange={() => {
                                  setSelectedProductIds((prev) => {
                                    const next = new Set(prev)
                                    if (next.has(product.id)) next.delete(product.id)
                                    else next.add(product.id)
                                    return next
                                  })
                                }}
                              />
                            </div>
                            <span style={{ flex: 1 }}>
                              <Text as="span" variant="bodyMd">
                                {product.title || '—'}
                              </Text>
                            </span>
                            <Text as="span" variant="bodyMd">
                              ${(product.price ?? 0).toFixed(2)}/ea
                            </Text>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {selectedProductIds.size > 0 && (
                    <Text as="p" variant="bodySm" tone="subdued">
                      {selectedProductIds.size} product(s) selected.
                    </Text>
                  )}
                </div>
              )}
            </>
          )}

          {formData.platform && (
            <FormLayout.Group>
              {/* Original Price: hide when Square/NCR has 2+ products; 0–1 keep it */}
              {!(isMultiSelectPlatform && selectedProductIds.size > 1) && (
                <TextField
                  label="Original Price"
                  type="number"
                  value={formData.originalPrice.toString()}
                  onChange={(value) =>
                    setFormData((prev) => ({ ...prev, originalPrice: parseFloat(value) || 0 }))
                  }
                  prefix="$"
                  helpText={
                    isMultiSelectPlatform && selectedProductIds.size === 0
                      ? 'Select a product to auto-fill'
                      : 'Current price of the product'
                  }
                  autoComplete="off"
                  disabled={isMultiSelectPlatform && selectedProductIds.size === 0}
                />
              )}

              <Select
                label="Price Adjustment"
                options={
                  isMultiSelectPlatform && selectedProductIds.size > 1
                    ? [{ label: 'Percentage Change', value: 'percentage' }]
                    : [
                        { label: 'Set Specific Price', value: 'fixed' },
                        { label: 'Percentage Change', value: 'percentage' },
                      ]
                }
                value={
                  isMultiSelectPlatform && selectedProductIds.size > 1
                    ? 'percentage'
                    : formData.multiplierPercentage !== null
                      ? 'percentage'
                      : 'fixed'
                }
                onChange={(value) => {
                  if (value === 'percentage') {
                    setFormData((prev) => ({ ...prev, multiplierPercentage: 0, price: 0 }))
                  } else {
                    setFormData((prev) => ({
                      ...prev,
                      multiplierPercentage: null,
                      price: prev.originalPrice,
                    }))
                  }
                }}
              />
            </FormLayout.Group>
          )}

          {isMultiSelectPlatform && selectedProductIds.size > 1 && (
            <Text as="p" variant="bodySm" tone="subdued">
              Applying percentage to {selectedProductIds.size} products.
            </Text>
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
          ) : formData.platform && !(isMultiSelectPlatform && selectedProductIds.size > 1) ? (
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

          {/* Square/NCR: preview Original → New when percentage and at least one product selected */}
          {isMultiSelectPlatform &&
            selectedProductIds.size > 0 &&
            formData.multiplierPercentage !== null && (
              <Card>
                <BlockStack gap="200">
                  <Text variant="headingSm" as="h3">
                    Preview
                  </Text>
                  <div style={{ maxHeight: '150px', overflowY: 'auto' }}>
                    {products
                      .filter((p) => selectedProductIds.has(p.id))
                      .map((p) => (
                        <div
                          key={p.id}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '6px 0',
                            borderBottom: '1px solid var(--p-color-border-subdued)',
                          }}
                        >
                          <Text as="span" variant="bodyMd">
                            {p.title || '—'}
                          </Text>
                          <Text as="span" variant="bodyMd" tone="subdued">
                            ${(p.price ?? 0).toFixed(2)} → $
                            {(
                              (p.price ?? 0) *
                              (1 + formData.multiplierPercentage! / 100)
                            ).toFixed(2)}
                          </Text>
                        </div>
                      ))}
                  </div>
                </BlockStack>
              </Card>
            )}

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
              <Text as="p">{String(submitError)}</Text>
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
              disabled={
                isMultiSelectPlatform && selectedProductIds.size === 0
              }
            >
              Create Schedule
            </Button>
          )}

        </FormLayout>
      </Card>
    </BlockStack>
  )
}

