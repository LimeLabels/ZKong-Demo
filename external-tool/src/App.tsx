import { useState, useEffect } from 'react'
import { Page, Layout, Tabs, Frame, TopBar, Button, Text, Spinner, BlockStack } from '@shopify/polaris'
import { ExitIcon } from '@shopify/polaris-icons'
import { ScheduleCalendar } from './components/ScheduleCalendar'
import { ScheduleList } from './components/ScheduleList'
import { Login } from './components/Login'
import { Onboarding } from './components/Onboarding'
import { EmailVerification } from './components/EmailVerification'
import { useAuth } from './contexts/AuthContext'
import { apiClient } from './services/api'

function App() {
  const { user, loading, signOut, isAuthenticated, needsEmailVerification } = useAuth()
  const [selectedTab, setSelectedTab] = useState(0)
  const [hasStore, setHasStore] = useState<boolean | null>(null)
  const [checkingStore, setCheckingStore] = useState(true)
  const [storeChecked, setStoreChecked] = useState(false) // Track if we've already checked

  /**
   * Check if user has a connected store.
   * Only check once when user becomes authenticated, not on every render or tab switch.
   */
  useEffect(() => {
    // Only check if we haven't checked yet and user is authenticated
    if (storeChecked || loading || !isAuthenticated || !user) {
      if (!isAuthenticated || !user) {
        setHasStore(false)
        setCheckingStore(false)
        setStoreChecked(false) // Reset when user logs out
      }
      return
    }

    const checkUserStore = async () => {
      try {
        setCheckingStore(true)
        const response = await apiClient.get('/api/auth/my-store')
        setHasStore(!!response.data)
        setStoreChecked(true) // Mark as checked
      } catch (error: any) {
        // 404 means no store connected
        if (error.response?.status === 404) {
          setHasStore(false)
        } else {
          console.error('Error checking user store:', error)
          setHasStore(false)
        }
        setStoreChecked(true) // Mark as checked even on error
      } finally {
        setCheckingStore(false)
      }
    }

    checkUserStore()
  }, [isAuthenticated, user, loading, storeChecked])

  /**
   * Handle logout.
   */
  const handleLogout = async () => {
    try {
      await signOut()
      setHasStore(null)
      setStoreChecked(false) // Reset store check on logout
    } catch (error) {
      console.error('Error signing out:', error)
    }
  }

  // Show loading spinner while checking auth state (but only if we have a user or are loading)
  if (loading) {
    return (
      <Frame>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
          <BlockStack gap="400" align="center">
            <Spinner size="large" />
            <Text variant="bodyMd" tone="subdued" as="p">Loading...</Text>
          </BlockStack>
        </div>
      </Frame>
    )
  }

  // Show email verification screen if user needs to verify email
  if (needsEmailVerification) {
    return <EmailVerification />
  }

  // Show login if not authenticated (this should be the first screen)
  if (!isAuthenticated || !user) {
    return <Login />
  }

  // Show loading while checking store (only if authenticated)
  if (checkingStore) {
    return (
      <Frame>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
          <BlockStack gap="400" align="center">
            <Spinner size="large" />
            <Text variant="bodyMd" tone="subdued" as="p">Checking store connection...</Text>
          </BlockStack>
        </div>
      </Frame>
    )
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

  /**
   * Handle disconnect store (change store).
   */
  const handleDisconnectStore = async () => {
    try {
      await apiClient.post('/api/auth/disconnect-store')
      setHasStore(false)
      setStoreChecked(false) // Reset so we check again
      // This will trigger the onboarding screen
    } catch (error: any) {
      console.error('Error disconnecting store:', error)
      alert(error.response?.data?.detail || 'Failed to disconnect store. Please try again.')
    }
  }

  const topBarMarkup = (
    <TopBar
      showNavigationToggle={false}
      userMenu={
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Button
            onClick={handleDisconnectStore}
            variant="plain"
            size="slim"
          >
            Change Store
          </Button>
          <Text variant="bodyMd" tone="subdued" as="p">
            {user?.email}
          </Text>
          <Button
            icon={ExitIcon}
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
