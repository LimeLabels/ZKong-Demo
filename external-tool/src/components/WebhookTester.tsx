import React, { useState } from 'react'
import { Card, FormLayout, TextField, Button, Banner, Text, BlockStack, Select, InlineStack } from '@shopify/polaris'
import { apiClient } from '../services/api'

type WebhookType = 'ncr' | 'square' | 'manual'

export function WebhookTester() {
  const [webhookType, setWebhookType] = useState<WebhookType>('ncr')
  const [itemCode, setItemCode] = useState('')
  const [objectId, setObjectId] = useState('')
  const [storeMappingId, setStoreMappingId] = useState('')
  const [scheduleId, setScheduleId] = useState('')
  const [authorization, setAuthorization] = useState('')
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const webhookTypeOptions = [
    { label: 'NCR', value: 'ncr' },
    { label: 'Square', value: 'square' },
    { label: 'Manual Trigger', value: 'manual' },
  ]

  const handleTest = async () => {
    setLoading(true)
    setError(null)
    setResponse(null)

    try {
      let endpoint = ''
      let payload: any = {
        store_mapping_id: storeMappingId,
        trigger_type: 'schedule',
      }

      if (webhookType === 'ncr') {
        endpoint = '/external/ncr/trigger-price-update'
        payload.item_code = itemCode
        if (scheduleId) payload.schedule_id = scheduleId
      } else if (webhookType === 'square') {
        endpoint = '/external/square/trigger-price-update'
        payload.object_id = objectId
        if (scheduleId) payload.schedule_id = scheduleId
      } else if (webhookType === 'manual') {
        if (!scheduleId) {
          setError('Schedule ID is required for manual trigger')
          setLoading(false)
          return
        }
        endpoint = `/external/trigger-schedule/${scheduleId}`
      }

      const config: any = {
        headers: {},
      }

      if (authorization) {
        config.headers.Authorization = `Bearer ${authorization}`
      }

      let result
      if (webhookType === 'manual') {
        result = await apiClient.post(endpoint, null, config)
      } else {
        result = await apiClient.post(endpoint, payload, config)
      }

      setResponse(result.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  return (
    <BlockStack gap="500">
      <Text variant="headingMd" as="h2">
        Webhook Tester
      </Text>
      <Text as="p" tone="subdued">
        Test webhook endpoints that NCR and Square can call to trigger price updates
      </Text>

      <Card>
        <FormLayout>
          <Select
            label="Webhook Type"
            options={webhookTypeOptions}
            value={webhookType}
            onChange={(value) => setWebhookType(value as WebhookType)}
          />

          {webhookType === 'ncr' && (
            <TextField
              label="Item Code"
              value={itemCode}
              onChange={setItemCode}
              placeholder="ITEM-001"
              helpText="Required for NCR webhooks"
            />
          )}

          {webhookType === 'square' && (
            <TextField
              label="Object ID"
              value={objectId}
              onChange={setObjectId}
              placeholder="catalog-object-id"
              helpText="Required for Square webhooks"
            />
          )}

          {webhookType !== 'manual' && (
            <TextField
              label="Store Mapping ID"
              value={storeMappingId}
              onChange={setStoreMappingId}
              placeholder="uuid-here"
              helpText="Required for price update triggers"
            />
          )}

          <TextField
            label="Schedule ID"
            value={scheduleId}
            onChange={setScheduleId}
            placeholder="schedule-uuid-here"
            helpText={webhookType === 'manual' ? 'Required for manual triggers' : 'Optional - specific schedule to trigger'}
          />

          <TextField
            label="Authorization Token"
            value={authorization}
            onChange={setAuthorization}
            type="password"
            placeholder="Bearer token"
            helpText="Optional - for authenticated requests"
          />

          <InlineStack>
            <Button
              onClick={handleTest}
              loading={loading}
              variant="primary"
            >
              Test Webhook
            </Button>
          </InlineStack>
        </FormLayout>
      </Card>

      {response && (
        <Banner tone="success" title="Success Response">
          <pre style={{ 
            background: '#f6f6f7', 
            padding: '1rem', 
            borderRadius: '4px', 
            overflow: 'auto',
            fontSize: '0.875rem'
          }}>
            {JSON.stringify(response, null, 2)}
          </pre>
        </Banner>
      )}

      {error && (
        <Banner tone="critical" title="Error">
          <p>{error}</p>
        </Banner>
      )}
    </BlockStack>
  )
}
