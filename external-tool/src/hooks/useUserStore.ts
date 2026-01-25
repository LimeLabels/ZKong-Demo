/**
 * Hook to get the current user's store mappings.
 * Fetches all stores and allows switching between them.
 */

import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

export interface UserStore {
  id: string
  source_system: string
  source_store_id: string
  hipoink_store_code: string | null
  is_active: boolean
  store_name?: string
}

export function useUserStore() {
  const { isAuthenticated } = useAuth()
  const [stores, setStores] = useState<UserStore[]>([])
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(() => {
    // Try to restore from localStorage
    return localStorage.getItem('selected_store_id')
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Fetch all stores
  useEffect(() => {
    const fetchStores = async () => {
      if (!isAuthenticated) {
        setStores([])
        setLoading(false)
        return
      }

      try {
        setLoading(true)
        setError(null)
        const response = await apiClient.get('/api/auth/my-stores')
        const fetchedStores: UserStore[] = response.data || []
        setStores(fetchedStores)
        
        // If we have stores but no selection, select the first one
        if (fetchedStores.length > 0 && !selectedStoreId) {
          const firstStoreId = fetchedStores[0].id
          setSelectedStoreId(firstStoreId)
          localStorage.setItem('selected_store_id', firstStoreId)
        }
        
        // If selected store no longer exists, select first available
        if (selectedStoreId && !fetchedStores.find(s => s.id === selectedStoreId)) {
          if (fetchedStores.length > 0) {
            const firstStoreId = fetchedStores[0].id
            setSelectedStoreId(firstStoreId)
            localStorage.setItem('selected_store_id', firstStoreId)
          } else {
            setSelectedStoreId(null)
            localStorage.removeItem('selected_store_id')
          }
        }
      } catch (err: any) {
        if (err.response?.status === 404) {
          // No stores connected - this is expected for new users
          setStores([])
        } else {
          console.error('Error fetching user stores:', err)
          setError(err.response?.data?.detail || 'Failed to load stores')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchStores()
  }, [isAuthenticated])

  // Function to switch stores
  const switchStore = useCallback((storeId: string) => {
    const store = stores.find(s => s.id === storeId)
    if (store) {
      setSelectedStoreId(storeId)
      localStorage.setItem('selected_store_id', storeId)
    }
  }, [stores])

  // Get the currently selected store
  const store = stores.find(s => s.id === selectedStoreId) || stores[0] || null

  return { 
    store,           // Currently selected store (for backwards compatibility)
    stores,          // All available stores
    selectedStoreId, // ID of selected store
    switchStore,     // Function to switch stores
    loading, 
    error 
  }
}
