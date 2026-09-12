/**
 * The Home's one-time redirect (ORB-180): after the first login the person lands on
 * «Get started»; the next times the Home stays the Home. «First» is remembered in the
 * browser, per space and per user, by the Get started page itself; a `replace`, so Back
 * does not bounce between the two.
 */
import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useAuth } from '@/lib/auth'
import { hasSeenGetStarted } from './firstSteps'

export function useFirstVisitGoesToGetStarted(): void {
  const { user } = useAuth()
  const navigate = useNavigate()
  const userId = user?.id
  useEffect(() => {
    if (!userId || hasSeenGetStarted(userId)) return
    void navigate({ to: '/app/get-started', replace: true })
  }, [userId, navigate])
}
