/**
 * Email verification waiting screen.
 * Shown when user has signed up but hasn't confirmed their email yet.
 */

import { Card, BlockStack, Text, Spinner } from '@shopify/polaris'

export function EmailVerification() {
  return (
    <div style={{ maxWidth: '500px', margin: '100px auto', padding: '0 20px' }}>
      <Card>
        <BlockStack gap="500" align="center">
          <Spinner size="large" />
          <BlockStack gap="300" align="center">
            <Text variant="headingXl" as="h1">
              Check Your Email
            </Text>
            <Text variant="bodyMd" tone="subdued" as="p" alignment="center">
              We've sent you a confirmation email. Please click the link in the email to verify your account.
            </Text>
            <Text variant="bodyMd" tone="subdued" as="p" alignment="center">
              Once you've confirmed your email, you'll be able to continue with the setup.
            </Text>
          </BlockStack>
        </BlockStack>
      </Card>
    </div>
  )
}

