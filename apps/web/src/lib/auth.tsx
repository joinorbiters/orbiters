import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, use, type ReactNode } from 'react'
import { api, unwrap } from './api'
import { queryKeys } from './query'

export interface SessionUser {
  id: string
  email: string
  nome: string
  ruolo: 'admin' | 'collaboratore' | 'readonly'
  attivo: boolean
}

interface AuthValue {
  user: SessionUser | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      try {
        return await unwrap(api.GET('/api/auth/me'))
      } catch {
        return null // not authenticated is a normal state, not an error
      }
    },
    retry: false,
  })

  const loginMutation = useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      unwrap(api.POST('/api/auth/login', { body })),
    onSuccess: (user) => queryClient.setQueryData(queryKeys.me, user),
  })

  const logoutMutation = useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSuccess: () => queryClient.clear(),
  })

  const value: AuthValue = {
    user: (data as SessionUser | null) ?? null,
    isLoading,
    login: async (email, password) => {
      await loginMutation.mutateAsync({ email, password })
    },
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
  }

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const value = use(AuthContext)
  if (!value) throw new Error('useAuth deve essere usato dentro AuthProvider')
  return value
}

export function useCanWrite(): boolean {
  const { user } = useAuth()
  return user?.ruolo === 'admin' || user?.ruolo === 'collaboratore'
}

export function useIsAdmin(): boolean {
  return useAuth().user?.ruolo === 'admin'
}
