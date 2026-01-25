/**
 * Hook to get the current user's store mapping.
 * Fetches and caches the user's connected store.
 */

import { useState, useEffect } from 'react'
import { apiClient } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

interface UserStore {
  id: string
  source_system: string
  source_store_id: string
  hipoink_store_code: string | null
  is_active: boolean
}

export function useUserStore() {
  const { isAuthenticated } = useAuth()
  const [store, setStore] = useState<UserStore | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchStore = async () => {
      if (!isAuthenticated) {
        setStore(null)
        setLoading(false)
        return
      }

      try {
        setLoading(true)
        setError(null)
        const response = await apiClient.get('/api/auth/my-store')
        setStore(response.data)
      } catch (err: any) {
        if (err.response?.status === 404) {
          // No store connected - this is expected for new users
          setStore(null)
        } else {
          console.error('Error fetching user store:', err)
          setError(err.response?.data?.detail || 'Failed to load store')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchStore()
  }, [isAuthenticated])

  return { store, loading, error }
}

