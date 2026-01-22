import { useState, useEffect } from 'react'
import { Card, Button, Banner, Text, BlockStack, InlineStack } from '@shopify/polaris'
import { apiClient } from '../services/api'

interface HealthStatus {
  status: string
  service?: string
  ncr_pos_url?: string
  timestamp?: string
}

export function HealthCheck() {
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const checkHealth = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.get('/external/health')
      setHealthStatus({
        ...response.data,
        timestamp: new Date().toISOString(),
      })
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Health check failed')
      setHealthStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    checkHealth()
  }, [])

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(() => {
        checkHealth()
      }, 5000) // Check every 5 seconds
      return () => clearInterval(interval)
    }
  }, [autoRefresh])

  const isHealthy = healthStatus?.status === 'healthy'

  return (
    <BlockStack gap="500">
      <InlineStack align="space-between">
        <div>
          <Text variant="headingMd" as="h2">
            Health Check
          </Text>
          <Text as="p" tone="subdued">
            Monitor the health status of webhook endpoints
          </Text>
        </div>
        <InlineStack gap="200">
          <Button
            onClick={checkHealth}
            loading={loading}
          >
            Refresh
          </Button>
          <Button
            onClick={() => setAutoRefresh(!autoRefresh)}
            variant={autoRefresh ? 'primary' : undefined}
          >
            {autoRefresh ? 'Stop Auto-Refresh' : 'Auto-Refresh'}
          </Button>
        </InlineStack>
      </InlineStack>

      <Banner
        tone={isHealthy ? 'success' : 'critical'}
        title={`Status: ${healthStatus?.status || 'Unknown'}`}
      >
        {healthStatus?.service && (
          <p>Service: {healthStatus.service}</p>
        )}
        {healthStatus?.timestamp && (
          <p>
            Last checked: {new Date(healthStatus.timestamp).toLocaleString()}
          </p>
        )}
      </Banner>

      {healthStatus && (
        <Card>
          <BlockStack gap="400">
            <Text variant="headingSm" as="h3">
              Service Information
            </Text>
            <BlockStack gap="200">
              {healthStatus.ncr_pos_url && (
                <InlineStack align="space-between">
                  <Text as="span" tone="subdued">NCR POS URL:</Text>
                  <Text as="span" variant="bodySm">{healthStatus.ncr_pos_url}</Text>
                </InlineStack>
              )}
              {healthStatus.service && (
                <InlineStack align="space-between">
                  <Text as="span" tone="subdued">Service:</Text>
                  <Text as="span" variant="bodySm">{healthStatus.service}</Text>
                </InlineStack>
              )}
            </BlockStack>
          </BlockStack>
        </Card>
      )}

      {error && (
        <Banner tone="critical" title="Error">
          <p>{error}</p>
        </Banner>
      )}

      <Card>
        <BlockStack gap="400">
          <Text variant="headingSm" as="h3">
            Available Endpoints
          </Text>
          <BlockStack gap="200">
            <Text as="p" variant="bodySm">
              <Text as="span" fontWeight="bold">GET /external/health</Text>
              <Text as="span" tone="subdued"> - Health check endpoint</Text>
            </Text>
            <Text as="p" variant="bodySm">
              <Text as="span" fontWeight="bold">POST /external/ncr/trigger-price-update</Text>
              <Text as="span" tone="subdued"> - NCR price update trigger</Text>
            </Text>
            <Text as="p" variant="bodySm">
              <Text as="span" fontWeight="bold">POST /external/square/trigger-price-update</Text>
              <Text as="span" tone="subdued"> - Square price update trigger</Text>
            </Text>
            <Text as="p" variant="bodySm">
              <Text as="span" fontWeight="bold">POST /external/trigger-schedule/{'{schedule_id}'}</Text>
              <Text as="span" tone="subdued"> - Manual schedule trigger</Text>
            </Text>
          </BlockStack>
        </BlockStack>
      </Card>
    </BlockStack>
  )
}
