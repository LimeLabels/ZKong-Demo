/**
 * Login component for user authentication.
 * Handles email/password login and user registration.
 */

import { useState } from 'react'
import {
  Card,
  FormLayout,
  TextField,
  Button,
  Text,
  Banner,
  BlockStack,
  InlineStack,
} from '@shopify/polaris'
import { useAuth } from '../contexts/AuthContext'

export function Login() {
  const { signIn, signUp } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  /**
   * Handle form submission for login or signup.
   */
  const handleSubmit = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required')
      return
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      if (isSignUp) {
        await signUp(email.trim(), password)
        setSuccess('Account created! Please check your email to verify your account.')
      } else {
        await signIn(email.trim(), password)
        setSuccess('Login successful!')
      }
    } catch (err: any) {
      console.error('Auth error:', err)
      setError(err.message || 'Authentication failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: '500px', margin: '100px auto', padding: '0 20px' }}>
      <Card>
        <BlockStack gap="500">
          <Text variant="heading2xl" as="h1">
            {isSignUp ? 'Create Account' : 'Sign In'}
          </Text>
          <Text variant="bodyMd" tone="subdued" as="p">
            {isSignUp
              ? 'Create an account to manage your time-based pricing schedules'
              : 'Sign in to access your time-based pricing schedules'}
          </Text>

          <FormLayout>
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="your@email.com"
              autoComplete="email"
              disabled={loading}
            />

            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              placeholder="Enter your password"
              autoComplete={isSignUp ? 'new-password' : 'current-password'}
              disabled={loading}
              helpText={isSignUp ? 'Password must be at least 6 characters' : undefined}
            />

            {error && (
              <Banner tone="critical" title="Error">
                <Text as="p">{error}</Text>
              </Banner>
            )}

            {success && (
              <Banner tone="success" title="Success">
                <Text as="p">{success}</Text>
              </Banner>
            )}

            <Button
              variant="primary"
              onClick={handleSubmit}
              loading={loading}
              fullWidth
            >
              {isSignUp ? 'Create Account' : 'Sign In'}
            </Button>

            <InlineStack align="center" gap="200">
              <Text variant="bodyMd" tone="subdued" as="p">
                {isSignUp ? 'Already have an account?' : "Don't have an account?"}
              </Text>
              <Button
                variant="plain"
                onClick={() => {
                  setIsSignUp(!isSignUp)
                  setError(null)
                  setSuccess(null)
                }}
                disabled={loading}
              >
                {isSignUp ? 'Sign In' : 'Sign Up'}
              </Button>
            </InlineStack>
          </FormLayout>
        </BlockStack>
      </Card>
    </div>
  )
}

