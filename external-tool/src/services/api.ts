import axios from 'axios'

const getBackendUrl = () => {
  // Check localStorage first (set via Settings page)
  const storedUrl = localStorage.getItem('backend_url')
  if (storedUrl) return storedUrl
  
  // Fall back to environment variable
  return import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
}

export const apiClient = axios.create({
  baseURL: getBackendUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
})

// Update base URL when localStorage changes
export const updateApiBaseUrl = () => {
  apiClient.defaults.baseURL = getBackendUrl()
}

// Request interceptor for adding auth tokens if needed
apiClient.interceptors.request.use(
  async (config) => {
    // Get Supabase session token
    try {
      const { getSession } = await import('./auth')
      const session = await getSession()
      if (session?.access_token) {
        config.headers.Authorization = `Bearer ${session.access_token}`
      }
    } catch (error) {
      // If auth service is not available, continue without token
      console.warn('Failed to get auth token:', error)
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response) {
      // Server responded with error
      console.error('API Error:', error.response.data)
      
      // Handle 401 Unauthorized - redirect to login
      if (error.response.status === 401) {
        // Clear any stored auth data
        try {
          const { signOut } = await import('./auth')
          await signOut()
        } catch (authError) {
          console.warn('Failed to sign out:', authError)
        }
        // Redirect to login will be handled by App component
      }
    } else if (error.request) {
      // Request made but no response
      console.error('Network Error:', error.request)
    } else {
      // Something else happened
      console.error('Error:', error.message)
    }
    return Promise.reject(error)
  }
)

