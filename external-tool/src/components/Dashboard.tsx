import { useEffect, useState } from 'react'
import { Card, Layout, Spinner, Button, Banner, Text, BlockStack, InlineStack } from '@shopify/polaris'
import { apiClient } from '../services/api'

interface DashboardStats {
  totalSchedules: number
  activeSchedules: number
  webhookHealth: 'healthy' | 'unhealthy' | 'unknown'
  lastTriggerTime: string | null
}

export function Dashboard() {
  const [stats, setStats] = useState<DashboardStats>({
    totalSchedules: 0,
    activeSchedules: 0,
    webhookHealth: 'unknown',
    lastTriggerTime: null,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    try {
      setLoading(true)
      // Fetch schedules count
      const schedulesResponse = await apiClient.get('/api/price-adjustments/')
      const schedules = schedulesResponse.data || []
      
      const activeSchedules = schedules.filter((s: any) => s.is_active)
      
      // Check webhook health
      const healthResponse = await apiClient.get('/external/health')
      const webhookHealth = healthResponse.data?.status === 'healthy' ? 'healthy' : 'unhealthy'

      setStats({
        totalSchedules: schedules.length,
        activeSchedules: activeSchedules.length,
        webhookHealth,
        lastTriggerTime: null, // TODO: Get from API
      })
    } catch (error) {
      console.error('Error loading dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <Layout>
        <Layout.Section>
          <Card>
            <div style={{ textAlign: 'center', padding: '2rem' }}>
              <Spinner accessibilityLabel="Loading" size="large" />
            </div>
          </Card>
        </Layout.Section>
      </Layout>
    )
  }

  return (
    <BlockStack gap="500">
      <Text variant="headingMd" as="h2">
        Dashboard Overview
      </Text>

      <Layout>
        <Layout.Section variant="oneThird">
          <Card>
            <BlockStack gap="200">
              <Text variant="headingSm" as="h3">
                Total Schedules
              </Text>
              <Text variant="heading2xl" as="p">
                {stats.totalSchedules}
              </Text>
            </BlockStack>
          </Card>
        </Layout.Section>

        <Layout.Section variant="oneThird">
          <Card>
            <BlockStack gap="200">
              <Text variant="headingSm" as="h3">
                Active Schedules
              </Text>
              <Text variant="heading2xl" as="p" tone={stats.activeSchedules > 0 ? 'success' : undefined}>
                {stats.activeSchedules}
              </Text>
            </BlockStack>
          </Card>
        </Layout.Section>

        <Layout.Section variant="oneThird">
          <Card>
            <BlockStack gap="200">
              <Text variant="headingSm" as="h3">
                Webhook Status
              </Text>
              <Text 
                variant="heading2xl" 
                as="p" 
                tone={stats.webhookHealth === 'healthy' ? 'success' : 'critical'}
              >
                {stats.webhookHealth === 'healthy' ? 'Healthy' : 'Unhealthy'}
              </Text>
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>

      <Card>
        <BlockStack gap="400">
          <Text variant="headingMd" as="h3">
            Quick Actions
          </Text>
          <InlineStack gap="300">
            <Button
              onClick={() => {
                const tabs = document.querySelector('[role="tablist"]') as HTMLElement
                const schedulesTab = Array.from(tabs?.querySelectorAll('[role="tab"]') || [])[1] as HTMLElement
                schedulesTab?.click()
              }}
            >
              View Schedules
            </Button>
            <Button
              onClick={() => {
                const tabs = document.querySelector('[role="tablist"]') as HTMLElement
                const webhooksTab = Array.from(tabs?.querySelectorAll('[role="tab"]') || [])[2] as HTMLElement
                webhooksTab?.click()
              }}
              variant="primary"
            >
              Test Webhook
            </Button>
            <Button onClick={loadDashboardData}>
              Refresh Data
            </Button>
          </InlineStack>
        </BlockStack>
      </Card>

      <Banner tone="info">
        <p>
          This external tool allows you to manage time-based pricing schedules and test webhook endpoints
          that NCR and Square can call to trigger price updates. Use the tabs above to navigate between
          different features.
        </p>
      </Banner>
    </BlockStack>
  )
}
