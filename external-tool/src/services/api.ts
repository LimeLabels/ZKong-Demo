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
  (config) => {
    // Add any auth tokens here if needed
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
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
  (error) => {
    if (error.response) {
      // Server responded with error
      console.error('API Error:', error.response.data)
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

