import { initAnalytics } from '@orbiters/analytics/browser'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { router } from './router'
import './styles/tokens.css'

// Before the first render, so the router's first entry is the first pageview. Inputs
// only are masked in a recording: the wizards are forms, and the privacy page says the
// hub records pages, clicks and sessions of the signed-in person.
initAnalytics()

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
