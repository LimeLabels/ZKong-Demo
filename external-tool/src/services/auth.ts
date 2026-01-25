/**
 * Authentication service using Supabase Auth.
 * Handles login, logout, session management, and token refresh.
 */

import { createClient, SupabaseClient, User } from '@supabase/supabase-js'

// Get Supabase URL and anon key from environment variables
// These should be set in your .env file or build environment
const getSupabaseUrl = () => {
  return import.meta.env.VITE_SUPABASE_URL || ''
}

const getSupabaseAnonKey = () => {
  return import.meta.env.VITE_SUPABASE_ANON_KEY || ''
}

// Create Supabase client
let supabaseClient: SupabaseClient | null = null

/**
 * Get or create Supabase client instance.
 * @returns Supabase client instance
 */
export const getSupabaseClient = (): SupabaseClient => {
  if (!supabaseClient) {
    const url = getSupabaseUrl()
    const anonKey = getSupabaseAnonKey()
    
    if (!url || !anonKey) {
      throw new Error('Supabase URL and anon key must be configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY environment variables.')
    }
    
    supabaseClient = createClient(url, anonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  }
  
  return supabaseClient
}

/**
 * Sign in with email and password.
 * @param email User email address
 * @param password User password
 * @returns User session data
 */
export const signIn = async (email: string, password: string) => {
  const supabase = getSupabaseClient()
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })
  
  if (error) {
    throw error
  }
  
  return data
}

/**
 * Sign up a new user with email and password.
 * @param email User email address
 * @param password User password
 * @returns User session data
 */
export const signUp = async (email: string, password: string) => {
  const supabase = getSupabaseClient()
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
  })
  
  if (error) {
    throw error
  }
  
  return data
}

/**
 * Sign out the current user.
 */
export const signOut = async () => {
  const supabase = getSupabaseClient()
  const { error } = await supabase.auth.signOut()
  
  if (error) {
    throw error
  }
}

/**
 * Get the current user session.
 * @returns Current user session or null
 */
export const getSession = async () => {
  const supabase = getSupabaseClient()
  const { data: { session }, error } = await supabase.auth.getSession()
  
  if (error) {
    throw error
  }
  
  return session
}

/**
 * Get the current authenticated user.
 * @returns Current user or null
 */
export const getCurrentUser = async (): Promise<User | null> => {
  const supabase = getSupabaseClient()
  const { data: { user }, error } = await supabase.auth.getUser()
  
  if (error) {
    throw error
  }
  
  return user
}

/**
 * Listen to auth state changes.
 * @param callback Function to call when auth state changes
 * @returns Unsubscribe function
 */
export const onAuthStateChange = (callback: (user: User | null) => void) => {
  const supabase = getSupabaseClient()
  
  return supabase.auth.onAuthStateChange((_event, session) => {
    callback(session?.user ?? null)
  })
}

/**
 * Get the access token for API requests.
 * @returns Access token or null
 */
export const getAccessToken = async (): Promise<string | null> => {
  const session = await getSession()
  return session?.access_token ?? null
}

