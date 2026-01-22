import React, { useState } from 'react'
import { Card, FormLayout, TextField, Button, Banner, Text, BlockStack } from '@shopify/polaris'
import { updateApiBaseUrl } from '../services/api'

export function ConfigSettings() {
  const [backendUrl, setBackendUrl] = useState(
    localStorage.getItem('backend_url') || import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
  )
  const [authToken, setAuthToken] = useState(
    localStorage.getItem('auth_token') || ''
  )
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    localStorage.setItem('backend_url', backendUrl)
    if (authToken) {
      localStorage.setItem('auth_token', authToken)
    } else {
      localStorage.removeItem('auth_token')
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
    
    // Update API client base URL
    updateApiBaseUrl()
  }

  return (
    <BlockStack gap="500">
      <div>
        <Text variant="headingMd" as="h2">
          Settings
        </Text>
        <Text as="p" tone="subdued">
          Configure API endpoints and authentication
        </Text>
      </div>

      <Card>
        <FormLayout>
          <TextField
            label="Backend URL"
            value={backendUrl}
            onChange={setBackendUrl}
            placeholder="http://localhost:8000"
            helpText="Base URL for the FastAPI backend (e.g., https://your-app.up.railway.app)"
          />

          <TextField
            label="Authorization Token"
            value={authToken}
            onChange={setAuthToken}
            type="password"
            placeholder="Bearer token for API authentication"
            helpText="Optional - Token used for authenticating webhook trigger requests"
          />

          <Button
            onClick={handleSave}
            variant="primary"
          >
            {saved ? '✓ Saved!' : 'Save Settings'}
          </Button>
        </FormLayout>
      </Card>

      <Card>
        <BlockStack gap="400">
          <Text variant="headingSm" as="h3">
            Environment Information
          </Text>
          <BlockStack gap="200">
            <Text as="p" variant="bodySm">
              <Text as="span" tone="subdued">Current Backend URL:</Text>
              <Text as="span" fontWeight="bold"> {backendUrl}</Text>
            </Text>
            <Text as="p" variant="bodySm">
              <Text as="span" tone="subdued">Environment:</Text>
              <Text as="span" fontWeight="bold"> {import.meta.env.MODE || 'development'}</Text>
            </Text>
          </BlockStack>
        </BlockStack>
      </Card>

      <Banner tone="info" title="Configuration Instructions">
        <BlockStack gap="200">
          <Text as="p" variant="bodySm">
            • Set the Backend URL to your deployed FastAPI service URL
          </Text>
          <Text as="p" variant="bodySm">
            • For Railway deployments, use your Railway app URL
          </Text>
          <Text as="p" variant="bodySm">
            • Authorization token is optional but recommended for production
          </Text>
          <Text as="p" variant="bodySm">
            • Settings are saved in browser localStorage
          </Text>
        </BlockStack>
      </Banner>
    </BlockStack>
  )
}
