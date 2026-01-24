/**
 * Onboarding component for connecting user's store to an existing mapping.
 * Allows users to select and connect to a store mapping.
 */

import { useState, useEffect } from 'react'
import {
  Card,
  FormLayout,
  Select,
  Button,
  Text,
  Banner,
  BlockStack,
  Spinner,
} from '@shopify/polaris'
import { apiClient } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

interface StoreMapping {
  id: string
  source_system: string
  source_store_id: string
  hipoink_store_code: string | null
  is_active: boolean
}

export function Onboarding() {
  const { user } = useAuth()
  const [storeMappings, setStoreMappings] = useState<StoreMapping[]>([])
  const [selectedMappingId, setSelectedMappingId] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  /**
   * Fetch available store mappings that the user can connect to.
   */
  useEffect(() => {
    const fetchStoreMappings = async () => {
      try {
        setLoading(true)
        // Fetch all active store mappings
        const response = await apiClient.get('/api/store-mappings/', {
          params: { is_active: true },
        })
        setStoreMappings(response.data || [])
      } catch (err: any) {
        console.error('Error fetching store mappings:', err)
        setError('Failed to load store mappings. Please try again.')
      } finally {
        setLoading(false)
      }
    }

    if (user) {
      fetchStoreMappings()
    }
  }, [user])

  /**
   * Connect user to selected store mapping.
   */
  const handleConnect = async () => {
    if (!selectedMappingId) {
      setError('Please select a store')
      return
    }

    setSubmitting(true)
    setError(null)
    setSuccess(false)

    try {
      // Call backend to associate user with store mapping
      await apiClient.post('/api/auth/connect-store', {
        store_mapping_id: selectedMappingId,
      })
      setSuccess(true)
      // Reload page after a short delay to refresh user data
      setTimeout(() => {
        window.location.reload()
      }, 2000)
    } catch (err: any) {
      console.error('Error connecting store:', err)
      setError(
        err.response?.data?.detail || 'Failed to connect store. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <BlockStack gap="400" align="center">
          <Spinner size="large" />
          <Text variant="bodyMd" tone="subdued" as="p">
            Loading available stores...
          </Text>
        </BlockStack>
      </Card>
    )
  }

  const mappingOptions = [
    { label: 'Select a store', value: '' },
    ...storeMappings.map((mapping) => ({
      label: `${mapping.source_store_id} (${mapping.source_system})`,
      value: mapping.id,
    })),
  ]

  return (
    <Card>
      <BlockStack gap="500">
        <Text variant="headingXl" as="h2">
          Connect Your Store
        </Text>
        <Text variant="bodyMd" tone="subdued" as="p">
          Select the store you want to manage. This will connect your account to an
          existing store mapping.
        </Text>

        <FormLayout>
          <Select
            label="Store"
            options={mappingOptions}
            value={selectedMappingId}
            onChange={setSelectedMappingId}
            disabled={submitting || storeMappings.length === 0}
            helpText={
              storeMappings.length === 0
                ? 'No available stores found. Please contact support.'
                : 'Select the store you want to manage'
            }
          />

          {error && (
            <Banner tone="critical" title="Error">
              <Text as="p">{error}</Text>
            </Banner>
          )}

          {success && (
            <Banner tone="success" title="Store Connected">
              <Text as="p">
                Your store has been connected successfully! Redirecting...
              </Text>
            </Banner>
          )}

          <Button
            variant="primary"
            onClick={handleConnect}
            loading={submitting}
            disabled={!selectedMappingId || storeMappings.length === 0}
          >
            Connect Store
          </Button>
        </FormLayout>
      </BlockStack>
    </Card>
  )
}

