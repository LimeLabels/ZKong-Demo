/**
 * Authentication context for managing user authentication state.
 * Provides auth state and methods throughout the application.
 */

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { User } from '@supabase/supabase-js'
import * as authService from '../services/auth'

interface AuthContextType {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  isAuthenticated: boolean
  needsEmailVerification: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

/**
 * AuthProvider component that wraps the app and provides auth context.
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [needsEmailVerification, setNeedsEmailVerification] = useState(false)

  // Initialize auth state
  useEffect(() => {
    // Check for existing session
    const initAuth = async () => {
      try {
        // Try to get session first (less likely to throw)
        const session = await authService.getSession()
        if (session?.user) {
          setUser(session.user)
          // Check if user needs email verification
          if (!session.user.email_confirmed_at) {
            setNeedsEmailVerification(true)
          } else {
            setNeedsEmailVerification(false)
          }
        } else {
          // No session - try to get user anyway
          try {
            const currentUser = await authService.getCurrentUser()
            setUser(currentUser)
            if (currentUser && !currentUser.email_confirmed_at) {
              setNeedsEmailVerification(true)
            } else {
              setNeedsEmailVerification(false)
            }
          } catch {
            // No user found - show login
            setUser(null)
            setNeedsEmailVerification(false)
          }
        }
      } catch (error) {
        // Any error means no authenticated user - show login
        console.warn('No authenticated session found:', error)
        setUser(null)
        setNeedsEmailVerification(false)
      } finally {
        setLoading(false)
      }
    }

    initAuth()

    // Listen for auth state changes
    const { data: { subscription } } = authService.getSupabaseClient().auth.onAuthStateChange(
      async (_event, session) => {
        const currentUser = session?.user ?? null
        setUser(currentUser)
        // Check if user needs email verification
        if (currentUser && !currentUser.email_confirmed_at) {
          setNeedsEmailVerification(true)
        } else {
          setNeedsEmailVerification(false)
        }
        setLoading(false)
      }
    )

    return () => {
      subscription.unsubscribe()
    }
  }, [])

  /**
   * Sign in with email and password.
   */
  const signIn = async (email: string, password: string) => {
    setLoading(true)
    try {
      await authService.signIn(email, password)
      // User state will be updated via auth state change listener
    } catch (error) {
      setLoading(false)
      throw error
    }
  }

  /**
   * Sign up a new user with email and password.
   */
  const signUp = async (email: string, password: string) => {
    setLoading(true)
    try {
      const result = await authService.signUp(email, password)
      // If user is created but email not confirmed, show verification screen
      if (result.user && !result.user.email_confirmed_at) {
        setNeedsEmailVerification(true)
        setUser(result.user)
      }
      // User state will be updated via auth state change listener
    } catch (error) {
      setLoading(false)
      throw error
    }
  }

  /**
   * Sign out the current user.
   */
  const signOut = async () => {
    setLoading(true)
    try {
      await authService.signOut()
      setUser(null)
    } catch (error) {
      setLoading(false)
      throw error
    } finally {
      setLoading(false)
    }
  }

  const value: AuthContextType = {
    user,
    loading,
    signIn,
    signUp,
    signOut,
    isAuthenticated: !!user && !needsEmailVerification,
    needsEmailVerification,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/**
 * Hook to access auth context.
 * @returns Auth context value
 * @throws Error if used outside AuthProvider
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

