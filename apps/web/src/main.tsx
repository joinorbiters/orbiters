import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from './lib/auth'
import { queryClient } from './lib/query'
import { tenantPrefix } from './lib/tenant'
import { routeTree } from './routeTree.gen'
import './styles/tokens.css'

// Under a space the same routes live at `/<slug>/app/...`: the basepath is the one
// place the prefix enters the router, so every `to: '/app/...'` keeps working as is.
const router = createRouter({ routeTree, basepath: tenantPrefix || undefined })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
