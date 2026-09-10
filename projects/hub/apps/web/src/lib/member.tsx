import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  member,
  type FreelancerApplication,
  type MemberProfile,
  type MemberUpdate,
} from './api'

export const MEMBER_KEY = ['member', 'me'] as const

/** The freelancer behind the member cookie, or `null`. A 401 is "not logged in". */
export function useMember() {
  return useQuery({
    queryKey: MEMBER_KEY,
    queryFn: async (): Promise<MemberProfile | null> => {
      try {
        return await member.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: 60_000,
  })
}

export function useRequestLink() {
  return useMutation({ mutationFn: (email: string) => member.requestLink(email) })
}

export function useEnter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => member.enter(token),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useUpdateProfile() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (data: MemberUpdate) => member.update(data),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useReplaceCv() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => member.replaceCv(file),
    onSuccess: (me) => client.setQueryData(MEMBER_KEY, me),
  })
}

export function useMemberLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => member.logout(),
    onSettled: () => {
      client.clear()
      window.location.assign('/hub/accedi')
    },
  })
}

/** The profile in the wizard's own shape, so its steps can render and validate it.
 *  `cv` is `null`: the file we hold is not a `File` in the browser. */
export function toApplication(profile: MemberProfile): FreelancerApplication {
  return {
    nome: profile.nome,
    cognome: profile.cognome,
    email: profile.email,
    linkedin_url: profile.linkedin_url ?? '',
    tariffa_giornaliera: profile.tariffa_giornaliera,
    posizione: profile.posizione,
    remoto: profile.remoto,
    links: profile.links,
    cv: null,
  }
}

/** What `PATCH /me` takes, trimmed the way the wizard trims before posting. */
export function toUpdate(value: FreelancerApplication): MemberUpdate {
  return {
    nome: value.nome.trim(),
    cognome: value.cognome.trim(),
    linkedin_url: value.linkedin_url.trim() || null,
    tariffa_giornaliera: value.tariffa_giornaliera.replace(',', '.').trim(),
    posizione: value.posizione.trim(),
    remoto: value.remoto as MemberUpdate['remoto'],
    links: value.links.map((link) => link.trim()).filter(Boolean),
  }
}
