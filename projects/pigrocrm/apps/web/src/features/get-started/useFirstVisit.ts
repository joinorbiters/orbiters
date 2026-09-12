/**
 * The Home's one-time redirect (ORB-180): after the first login the person lands on
 * «Get started»; the next times the Home stays the Home. «First» is remembered in the
 * browser, per space and per user, by the Get started page itself (so a visit through
 * the sidebar counts too, on purpose). A space with nothing left to do is not sent
 * there at all: the root and every space in use mark the visit and stay. A `replace`,
 * so Back does not bounce between the two.
 *
 * The reads happen only while the browser has not decided yet: once, per space and
 * per user, then never again on this device.
 */
import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useAuth } from '@/lib/auth'
import { hasSeenGetStarted, markGetStartedSeen, useFirstSteps } from './firstSteps'

export function useFirstVisitGoesToGetStarted(): void {
  const { user } = useAuth()
  const navigate = useNavigate()
  const userId = user?.id
  const undecided = Boolean(userId) && !hasSeenGetStarted(userId ?? '')
  const state = useFirstSteps({ enabled: undecided })
  const settled = undecided && !state.loading
  const somethingToDo = !(state.allDone && state.assistantConnected)
  useEffect(() => {
    if (!userId || !settled) return
    if (somethingToDo) {
      void navigate({ to: '/app/get-started', replace: true })
    } else {
      markGetStartedSeen(userId)
    }
  }, [userId, settled, somethingToDo, navigate])
}
