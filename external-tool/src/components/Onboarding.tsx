/**
 * Onboarding component for connecting user's store.
 * Allows users to enter their Hipoink store code and select POS system to find/create a store mapping.
 */

import { useState } from 'react'
import {
  Card,
  FormLayout,
  Select,
  Button,
  Text,
  Banner,
  BlockStack,
  TextField,
} from '@shopify/polaris'
import { apiClient } from '../services/api'

export function Onboarding() {
  const [hipoinkStoreCode, setHipoinkStoreCode] = useState('')
  const [posSystem, setPosSystem] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const posSystemOptions = [
    { label: 'Select POS System', value: '' },
    { label: 'NCR POS', value: 'ncr' },
    { label: 'Square', value: 'square' },
    { label: 'Shopify', value: 'shopify' },
  ]

  /**
   * Find existing store mapping and connect user.
   * Does NOT create new mappings - only connects to existing ones (1:1 relationship).
   */
  const handleConnect = async () => {
    if (!hipoinkStoreCode.trim()) {
      setError('Please enter your Hipoink store code')
      return
    }

    if (!posSystem) {
      setError('Please select your POS system')
      return
    }

    setSubmitting(true)
    setError(null)
    setSuccess(false)

    try {
      // Find existing store mapping by POS system and Hipoink store code
      // This does NOT create new mappings - only finds existing ones
      const findResponse = await apiClient.post('/api/auth/find-store-mapping', {
        source_system: posSystem,
        hipoink_store_code: hipoinkStoreCode.trim(),
      })

      const storeMappingId = findResponse.data.id

      // Connect user to the store mapping
      await apiClient.post('/api/auth/connect-store', {
        store_mapping_id: storeMappingId,
      })

      setSuccess(true)
      // Reload page after a short delay to refresh user data
      setTimeout(() => {
        window.location.reload()
      }, 2000)
    } catch (err: any) {
      console.error('Error connecting store:', err)
      
      // Provide more specific error messages
      if (err.code === 'ERR_NETWORK' || err.message?.includes('Network Error')) {
        setError(
          'Cannot connect to the server. Please make sure the backend is running and check your network connection.'
        )
      } else if (err.response?.status === 404) {
        // Store mapping not found - explain that mappings must be created separately
        const detail = err.response?.data?.detail || 'Store mapping not found'
        setError(
          `${detail}. Store mappings must be created separately before users can connect to them.`
        )
      } else if (err.response?.status === 409) {
        setError(
          'This store mapping is already connected to another user. Please contact support if you believe this is an error.'
        )
      } else if (err.response?.data?.detail) {
        // Use the detailed error from the backend
        const detail = err.response.data.detail
        setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
      } else {
        setError(err.message || 'Failed to connect store. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <BlockStack gap="500">
        <Text variant="headingXl" as="h2">
          Connect Your Store
        </Text>
        <Text variant="bodyMd" tone="subdued" as="p">
          Enter your Hipoink store code and select your POS system to connect your account.
        </Text>

        <FormLayout>
          <TextField
            label="Hipoink Store Code"
            value={hipoinkStoreCode}
            onChange={setHipoinkStoreCode}
            placeholder="Enter your Hipoink store code"
            autoComplete="off"
            disabled={submitting}
            helpText="The store code used in your Hipoink ESL system"
          />

          <Select
            label="POS System"
            options={posSystemOptions}
            value={posSystem}
            onChange={setPosSystem}
            disabled={submitting}
            helpText="Select the point-of-sale system you're using"
          />

          {error && (
            <Banner tone="critical" title="Error">
              <BlockStack gap="200">
                <Text as="p">{error}</Text>
                {error.includes('Cannot connect to the server') && (
                  <Text as="p" variant="bodySm" tone="subdued">
                    Current backend URL: {apiClient.defaults.baseURL || 'Not set'}
                  </Text>
                )}
              </BlockStack>
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
            disabled={!hipoinkStoreCode.trim() || !posSystem}
          >
            Connect Store
          </Button>
        </FormLayout>
      </BlockStack>
    </Card>
  )
}

