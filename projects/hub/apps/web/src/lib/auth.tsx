import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, admin, type Admin } from './api'

export const ME_KEY = ['admin', 'me'] as const

/** The admin behind the cookie, or `null`. A 401 is the ordinary "not logged in", not
 *  an error; anything else is. */
export function useAdmin() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<Admin | null> => {
      try {
        return await admin.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: 60_000,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      admin.login(email, password),
    onSuccess: (me) => client.setQueryData(ME_KEY, me),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => admin.logout(),
    onSettled: () => {
      client.clear()
      window.location.assign('/hub/admin/login')
    },
  })
}
