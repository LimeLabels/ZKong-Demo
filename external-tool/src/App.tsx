import { useState, useEffect } from 'react'
import { Page, Layout, Tabs, Frame, TopBar, Button, Text, Spinner, BlockStack } from '@shopify/polaris'
import { LogOutIcon } from '@shopify/polaris-icons'
import { ScheduleCalendar } from './components/ScheduleCalendar'
import { ScheduleList } from './components/ScheduleList'
import { Login } from './components/Login'
import { Onboarding } from './components/Onboarding'
import { useAuth } from './contexts/AuthContext'
import { apiClient } from './services/api'

function App() {
  const { user, loading, signOut, isAuthenticated } = useAuth()
  const [selectedTab, setSelectedTab] = useState(0)
  const [hasStore, setHasStore] = useState<boolean | null>(null)
  const [checkingStore, setCheckingStore] = useState(true)

  /**
   * Check if user has a connected store.
   */
  useEffect(() => {
    const checkUserStore = async () => {
      if (!isAuthenticated || !user) {
        setHasStore(false)
        setCheckingStore(false)
        return
      }

      try {
        setCheckingStore(true)
        const response = await apiClient.get('/api/auth/my-store')
        setHasStore(!!response.data)
      } catch (error: any) {
        // 404 means no store connected
        if (error.response?.status === 404) {
          setHasStore(false)
        } else {
          console.error('Error checking user store:', error)
          setHasStore(false)
        }
      } finally {
        setCheckingStore(false)
      }
    }

    if (!loading) {
      checkUserStore()
    }
  }, [isAuthenticated, user, loading])

  /**
   * Handle logout.
   */
  const handleLogout = async () => {
    try {
      await signOut()
      setHasStore(null)
    } catch (error) {
      console.error('Error signing out:', error)
    }
  }

  // Show loading spinner while checking auth state
  if (loading || checkingStore) {
    return (
      <Frame>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
          <BlockStack gap="400" align="center">
            <Spinner size="large" />
            <Text variant="bodyMd" tone="subdued">Loading...</Text>
          </BlockStack>
        </div>
      </Frame>
    )
  }

  // Show login if not authenticated
  if (!isAuthenticated) {
    return <Login />
  }

  // Show onboarding if authenticated but no store connected
  if (!hasStore) {
    return (
      <Frame>
        <div style={{ maxWidth: '800px', margin: '50px auto', padding: '0 20px' }}>
          <Onboarding />
        </div>
      </Frame>
    )
  }

  // Main app with authenticated user and connected store
  const tabs = [
    {
      id: 'create',
      content: 'Create Schedule',
      panelID: 'create-panel',
    },
    {
      id: 'manage',
      content: 'Manage Schedules',
      panelID: 'manage-panel',
    },
  ]

  const topBarMarkup = (
    <TopBar
      showNavigationToggle={false}
      userMenu={
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Text variant="bodyMd" tone="subdued">
            {user?.email}
          </Text>
          <Button
            icon={LogOutIcon}
            onClick={handleLogout}
            variant="plain"
            size="slim"
          >
            Logout
          </Button>
        </div>
      }
    />
  )

  return (
    <Frame topBar={topBarMarkup}>
      <Page title="Time-Based Pricing Schedules" fullWidth>
        <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
          <Layout>
            <Layout.Section>
              {selectedTab === 0 && <ScheduleCalendar />}
              {selectedTab === 1 && <ScheduleList />}
            </Layout.Section>
          </Layout>
        </Tabs>
      </Page>
    </Frame>
  )
}

export default App
