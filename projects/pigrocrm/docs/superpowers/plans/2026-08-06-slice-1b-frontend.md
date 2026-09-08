# PigroCRM Slice 1B — Web app, E2E and deploy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the web interface for the Core CRM — login, customers, people, deals with a Kanban, and settings for custom fields, pipeline, users and tokens — plus end-to-end tests and a deployable Docker/CI setup.

**Architecture:** The UI consumes only the public REST API from plan 1A, through a TypeScript client generated from the OpenAPI document. Two shared components carry most of the weight: `EntityDetailLayout` gives Customer, Person and Deal the same page shape, and `DynamicFieldRenderer` turns a field definition into the right form control and the right table cell — so a custom field added at runtime works everywhere with no frontend change.

**Tech Stack:** Vite · React 19 · TypeScript · TanStack Router · TanStack Query · TanStack Table · shadcn/ui · Tailwind v4 · dnd-kit · Playwright · Docker Compose · GitHub Actions

**Spec:** `docs/superpowers/specs/2026-08-06-pigrocrm-core-crm-mcp-design.md` (§10, §12, §13)

**Prerequisite:** plan `2026-08-06-slice-1a-backend.md` complete and green. This plan calls the API it built and never talks to the database directly.

---

## Global Constraints

- **No `fetch` inside components.** Every request goes through the generated client wrapped in TanStack Query hooks. A component that fetches is a component that cannot be tested or cached.
- **The API client is generated, never handwritten.** `openapi-typescript` reads `openapi.json` from the running API. A contract change must break `tsc`, not production.
- **No business logic in the frontend.** Validation messages come from the API's problem documents. Recomputing a rule client-side is how the three interfaces start disagreeing — the exact defect inherited from the previous system, where the fiscal maths lived in `App.jsx`.
- **No component file over ~250 lines.** the previous system's `App.jsx` was one 5,870-line component with 94 `useState`. If a file approaches the limit, extract.
- **UI language is Italian.** Every visible label, button and message.
- **TypeScript strict mode**, no `any`, no `@ts-ignore`.
- **Commit after every task.**

### Pinned versions

`vite 8.2.0` · `react 19.2.8` · `react-dom 19.2.8` · `typescript 5.9` (**not** 7.x — the Go rewrite is too new for this toolchain) · `@tanstack/react-router 1.170.20` · `@tanstack/router-plugin 1.168.25` · `@tanstack/react-query 5.101.4` · `@tanstack/react-table 9.0.0` · `tailwindcss 4.3.3` · `@tailwindcss/vite 4.3.3` · `shadcn 4.16.1` (CLI) · `@dnd-kit/core 6.3.1` · `@dnd-kit/sortable 10.0.0` · `openapi-typescript 7.13.0` · `openapi-fetch 0.17.0` · `@playwright/test 1.62.1` · `lucide-react` latest · `@tabler/icons-react` latest (**brand icons only**)

Package manager: **pnpm 10**.

### Design tokens (exact values — do not improvise)

| Token | Hex | Role |
|---|---|---|
| Watermelon | `#ED254E` | primary action, destructive state |
| Royal Gold | `#F9DC5C` | warning, attention |
| Mint Cream | `#F4FFFD` | app background (light) |
| Prussian Blue | `#011936` | foreground text, dark surface |
| Charcoal Blue | `#465362` | muted / secondary text |

Font: **Outfit** only. `Reenie Beanie` belongs to the landing page in slice 5 — do **not** load it here.

Contrast must reach **WCAG AA**. Watermelon on Mint Cream passes for large text and UI elements; for body copy on light backgrounds use Prussian Blue.

---

## File Structure

```
apps/web/
├── package.json · vite.config.ts · tsconfig.json · components.json
├── index.html
├── e2e/                                   # Playwright specs
└── src/
    ├── main.tsx · routeTree.gen.ts (generated)
    ├── styles/tokens.css                  # the single source of colour
    ├── lib/
    │   ├── api-types.ts (generated)       # openapi-typescript output
    │   ├── api.ts                         # openapi-fetch client + problem-detail parsing
    │   ├── query.ts                       # QueryClient + shared keys
    │   └── auth.tsx                       # session context
    ├── components/
    │   ├── ui/                            # shadcn-generated primitives
    │   ├── AppShell.tsx                   # sidebar + header
    │   ├── EntityDetailLayout.tsx         # Panoramica · Timeline · Collegamenti
    │   ├── DynamicFieldRenderer.tsx       # definition -> control / cell
    │   ├── DynamicForm.tsx                # native + custom fields, problem-detail errors
    │   ├── DataTable.tsx                  # TanStack Table wrapper
    │   └── Timeline.tsx
    ├── features/
    │   ├── customers/{queries.ts,CustomerForm.tsx,columns.tsx}
    │   ├── people/{queries.ts,PersonForm.tsx,columns.tsx}
    │   ├── deals/{queries.ts,DealForm.tsx,columns.tsx,KanbanBoard.tsx,KanbanCard.tsx}
    │   └── settings/{FieldsPanel.tsx,PipelinePanel.tsx,UsersPanel.tsx,TokensPanel.tsx}
    └── routes/                            # TanStack Router file-based
```

**Why these boundaries:** `components/` holds what every feature reuses; `features/` holds what one domain owns. Queries live beside the feature that uses them, so a change to the customers API touches one folder.

---

# Phase 1 — Foundations

### Task 1: Scaffolding, Tailwind v4, shadcn and the design tokens

**Files:**
- Create: `apps/web/{package.json,vite.config.ts,tsconfig.json,tsconfig.node.json,index.html,components.json,.gitignore}`
- Create: `apps/web/src/{main.tsx,styles/tokens.css}`
- Create: `apps/web/src/routes/{__root.tsx,index.tsx}`
- Test: `apps/web/src/styles/tokens.test.ts`

**Interfaces:**
- Consumes: nothing from 1A yet
- Produces: `pnpm dev` serves on :5173; `pnpm build` produces `dist/`; Tailwind v4 with the palette bound to shadcn's semantic variables; `cn()` helper at `src/lib/utils.ts`

- [ ] **Step 1: Create the Vite app**

```bash
cd apps/web 2>/dev/null || mkdir -p apps/web && cd apps/web
pnpm create vite@8.2.0 . --template react-ts
pnpm add react@19.2.8 react-dom@19.2.8
pnpm add -D typescript@5.9 vite@8.2.0
pnpm add tailwindcss@4.3.3 @tailwindcss/vite@4.3.3
pnpm add @tanstack/react-router@1.170.20 @tanstack/react-query@5.101.4 @tanstack/react-table@9.0.0
pnpm add -D @tanstack/router-plugin@1.168.25
pnpm add class-variance-authority clsx tailwind-merge lucide-react
pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom
cd ../..
```

- [ ] **Step 2: Configure Vite**

`apps/web/vite.config.ts`:

```ts
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    // The browser talks to the same origin in dev and in production, so cookies
    // behave identically in both and there is no CORS special case to debug.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test-setup.ts' },
})
```

`apps/web/tsconfig.json` — add the path alias to `compilerOptions`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src", "e2e"]
}
```

`apps/web/src/test-setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 3: Write the design tokens**

`apps/web/src/styles/tokens.css`:

```css
@import 'tailwindcss';
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

/* The single source of colour for the whole application.
   Landing-page tokens live in slice 5 and are the soft expression of this same
   system: Coral #FFB7B2 is the desaturated tint of Watermelon #ED254E. */
@theme {
  --color-watermelon: #ed254e;
  --color-royal-gold: #f9dc5c;
  --color-mint-cream: #f4fffd;
  --color-prussian-blue: #011936;
  --color-charcoal-blue: #465362;

  --font-sans: 'Outfit', ui-sans-serif, system-ui, sans-serif;
  --radius: 0.625rem;
}

:root {
  --background: var(--color-mint-cream);
  --foreground: var(--color-prussian-blue);
  --card: #ffffff;
  --card-foreground: var(--color-prussian-blue);
  --popover: #ffffff;
  --popover-foreground: var(--color-prussian-blue);
  --primary: var(--color-watermelon);
  --primary-foreground: #ffffff;
  --secondary: #e6ecea;
  --secondary-foreground: var(--color-prussian-blue);
  --muted: #eef4f2;
  --muted-foreground: var(--color-charcoal-blue);
  --accent: var(--color-royal-gold);
  --accent-foreground: var(--color-prussian-blue);
  --destructive: var(--color-watermelon);
  --destructive-foreground: #ffffff;
  --border: #d8e2df;
  --input: #d8e2df;
  --ring: var(--color-watermelon);
}

.dark {
  --background: var(--color-prussian-blue);
  --foreground: var(--color-mint-cream);
  --card: #0a2547;
  --card-foreground: var(--color-mint-cream);
  --popover: #0a2547;
  --popover-foreground: var(--color-mint-cream);
  --primary: var(--color-watermelon);
  --primary-foreground: #ffffff;
  --secondary: #14304f;
  --secondary-foreground: var(--color-mint-cream);
  --muted: #14304f;
  --muted-foreground: #9fb0c0;
  --accent: var(--color-royal-gold);
  --accent-foreground: var(--color-prussian-blue);
  --destructive: var(--color-watermelon);
  --destructive-foreground: #ffffff;
  --border: #1d3d61;
  --input: #1d3d61;
  --ring: var(--color-royal-gold);
}

@layer base {
  * {
    border-color: var(--border);
  }
  body {
    background-color: var(--background);
    color: var(--foreground);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
  }
}
```

- [ ] **Step 4: Write the failing token test**

`apps/web/src/styles/tokens.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'tokens.css'), 'utf-8')

describe('design tokens', () => {
  it.each([
    ['watermelon', '#ed254e'],
    ['royal-gold', '#f9dc5c'],
    ['mint-cream', '#f4fffd'],
    ['prussian-blue', '#011936'],
    ['charcoal-blue', '#465362'],
  ])('defines %s as %s', (name, hex) => {
    expect(css).toContain(`--color-${name}: ${hex}`)
  })

  it('uses Watermelon as the primary action colour', () => {
    expect(css).toMatch(/--primary:\s*var\(--color-watermelon\)/)
  })

  it('defines a dark mode', () => {
    expect(css).toContain('.dark {')
  })

  it('does not load Reenie Beanie, which belongs to the landing page', () => {
    expect(css).not.toMatch(/Reenie/i)
  })
})
```

- [ ] **Step 5: Run it to watch it fail, then pass**

Run: `cd apps/web && pnpm vitest run src/styles/tokens.test.ts`
Expected: PASS (8 passed) once `tokens.css` exists. If you ran it before writing the file, it fails with `ENOENT` — that is the red state.

- [ ] **Step 6: Initialise shadcn and add the primitives**

```bash
cd apps/web
pnpm dlx shadcn@4.16.1 init --base-color neutral --css-variables
pnpm dlx shadcn@4.16.1 add button input label textarea select checkbox card dialog \
  dropdown-menu table tabs badge sonner sidebar separator avatar skeleton form popover calendar
cd ../..
```

When the CLI asks about overwriting `src/index.css`, decline — `tokens.css` is authoritative. Then
confirm `components.json` points at it:

```json
{ "tailwind": { "css": "src/styles/tokens.css", "baseColor": "neutral", "cssVariables": true } }
```

- [ ] **Step 7: Write the root route and entry point**

`apps/web/src/routes/__root.tsx`:

```tsx
import { Outlet, createRootRoute } from '@tanstack/react-router'
import { Toaster } from '@/components/ui/sonner'

export const Route = createRootRoute({
  component: () => (
    <>
      <Outlet />
      <Toaster richColors position="top-right" />
    </>
  ),
})
```

`apps/web/src/routes/index.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: () => <div className="p-8 text-2xl font-semibold">PigroCRM</div>,
})
```

`apps/web/src/main.tsx`:

```tsx
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { routeTree } from './routeTree.gen'
import './styles/tokens.css'

const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
```

- [ ] **Step 8: Verify the build**

Run: `cd apps/web && pnpm build && pnpm vitest run`
Expected: build succeeds, tests pass.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(web): Vite + Tailwind v4 + shadcn scaffolding with the PigroCRM palette"
```

---

### Task 2: Generated API client, query layer and session

**Files:**
- Create: `apps/web/src/lib/{api.ts,query.ts,auth.tsx}`
- Create: `apps/web/src/lib/api.test.ts`
- Modify: `apps/web/package.json` (add the `generate:api` script)

**Interfaces:**
- Consumes: the running API from plan 1A
- Produces:
  - `api` — typed `openapi-fetch` client, `credentials: 'include'`
  - `ProblemDetail` type and `toProblem(error: unknown): ProblemDetail`
  - `fieldErrorFrom(problem)` — `{ field, message } | null`, so forms can highlight the offending input
  - `queryClient`, `queryKeys`
  - `AuthProvider`, `useAuth() -> { user, login, logout, isLoading }`

- [ ] **Step 1: Generate the types**

Start the API from plan 1A, then:

```bash
cd apps/web
pnpm add openapi-fetch@0.17.0
pnpm add -D openapi-typescript@7.13.0
pnpm exec openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts
cd ../..
```

Add to `apps/web/package.json`:

```json
{
  "scripts": {
    "generate:api": "openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts"
  }
}
```

- [ ] **Step 2: Write the failing test**

`apps/web/src/lib/api.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { fieldErrorFrom, toProblem } from './api'

const PROBLEM = {
  type: 'https://pigrocrm.dev/errors/validation_failed',
  title: 'Dati non validi',
  status: 422,
  detail: 'customer.partita_iva: deve essere di 11 cifre',
  code: 'validation_failed',
  entity: 'customer',
  field: 'partita_iva',
  reason: 'deve essere di 11 cifre',
  expected: '11 cifre numeriche',
}

describe('toProblem', () => {
  it('passes a problem document through', () => {
    expect(toProblem(PROBLEM).code).toBe('validation_failed')
  })

  it('turns an unknown failure into a readable Italian message', () => {
    const problem = toProblem(new Error('network down'))
    expect(problem.code).toBe('unknown')
    expect(problem.detail).toMatch(/errore/i)
  })

  it('never returns undefined for detail', () => {
    expect(toProblem(null).detail).toBeTruthy()
  })
})

describe('fieldErrorFrom', () => {
  it('extracts the offending field so the form can highlight it', () => {
    expect(fieldErrorFrom(toProblem(PROBLEM))).toEqual({
      field: 'partita_iva',
      message: 'deve essere di 11 cifre (atteso: 11 cifre numeriche)',
    })
  })

  it('returns null when the problem is not about a field', () => {
    expect(fieldErrorFrom(toProblem({ ...PROBLEM, code: 'conflict', field: undefined }))).toBeNull()
  })
})
```

- [ ] **Step 3: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/lib/api.test.ts`
Expected: FAIL — `Failed to resolve import "./api"`

- [ ] **Step 4: Write `lib/api.ts`**

```ts
import createClient from 'openapi-fetch'
import type { paths } from './api-types'

export const api = createClient<paths>({
  baseUrl: '/api',
  // The JWT lives in an httpOnly cookie: JavaScript never sees it, and every
  // request carries it automatically.
  credentials: 'include',
})

export interface ProblemDetail {
  type: string
  title: string
  status: number
  detail: string
  code: string
  entity?: string
  field?: string
  reason?: string
  expected?: string
  [key: string]: unknown
}

const GENERIC: ProblemDetail = {
  type: 'about:blank',
  title: 'Errore',
  status: 0,
  detail: 'Si è verificato un errore imprevisto. Riprova.',
  code: 'unknown',
}

export function toProblem(error: unknown): ProblemDetail {
  if (error && typeof error === 'object' && 'code' in error && 'detail' in error) {
    return error as ProblemDetail
  }
  return GENERIC
}

/** The API already decided what is wrong and why. The UI only points at it. */
export function fieldErrorFrom(problem: ProblemDetail): { field: string; message: string } | null {
  if (problem.code !== 'validation_failed' || !problem.field) return null
  const reason = problem.reason ?? problem.detail
  const message = problem.expected ? `${reason} (atteso: ${problem.expected})` : reason
  return { field: problem.field, message }
}

/** Throws the problem document itself, so every consumer gets structured data. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown }>,
): Promise<T> {
  const { data, error } = await promise
  if (error !== undefined) throw toProblem(error)
  return data as T
}
```

- [ ] **Step 5: Write `lib/query.ts`**

```ts
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // A 401 means the session expired; retrying just delays the redirect.
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status
        if (status === 401 || status === 403) return false
        return failureCount < 2
      },
    },
  },
})

export const queryKeys = {
  me: ['me'] as const,
  customers: (params?: unknown) => ['customers', params ?? {}] as const,
  customer: (id: string) => ['customer', id] as const,
  people: (params?: unknown) => ['people', params ?? {}] as const,
  person: (id: string) => ['person', id] as const,
  deals: (params?: unknown) => ['deals', params ?? {}] as const,
  deal: (id: string) => ['deal', id] as const,
  timeline: (entity: string, id: string) => ['timeline', entity, id] as const,
  fields: (entityType: string) => ['field-definitions', entityType] as const,
  schema: (entityType: string) => ['schema', entityType] as const,
  stages: ['pipeline-stages'] as const,
  users: ['users'] as const,
  tokens: ['tokens'] as const,
}
```

- [ ] **Step 6: Write `lib/auth.tsx`**

```tsx
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
        return await unwrap(api.GET('/auth/me'))
      } catch {
        return null // not authenticated is a normal state, not an error
      }
    },
    retry: false,
  })

  const loginMutation = useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      unwrap(api.POST('/auth/login', { body })),
    onSuccess: (user) => queryClient.setQueryData(queryKeys.me, user),
  })

  const logoutMutation = useMutation({
    mutationFn: () => unwrap(api.POST('/auth/logout')),
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
```

- [ ] **Step 7: Wire the providers into `main.tsx`**

Replace the render call:

```tsx
import { QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './lib/auth'
import { queryClient } from './lib/query'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
```

- [ ] **Step 8: Run the tests**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit`
Expected: PASS (5 passed), no type errors.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(web): generated API client, query layer and cookie-based session"
```

---

### Task 3: App shell, login page and route protection

**Files:**
- Create: `apps/web/src/components/AppShell.tsx`
- Create: `apps/web/src/routes/{login.tsx,_app.tsx,_app/index.tsx}`
- Modify: `apps/web/src/routes/index.tsx` (redirect to the app)
- Test: `apps/web/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: `useAuth`, `useIsAdmin` (Task 2)
- Produces: `AppShell` with collapsible sidebar; `/login`; the `_app` pathless layout route that redirects unauthenticated visitors to `/login`

- [ ] **Step 1: Write the failing test**

`apps/web/src/components/AppShell.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
  useRouterState: () => ({ location: { pathname: '/clienti' } }),
}))

const mockAuth = vi.hoisted(() => ({ ruolo: 'admin' as string }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { nome: 'Ivan', email: 'm@example.com', ruolo: mockAuth.ruolo }, logout: vi.fn() }),
  useIsAdmin: () => mockAuth.ruolo === 'admin',
}))

describe('AppShell', () => {
  it('shows the main navigation in Italian', () => {
    render(<AppShell><div /></AppShell>)
    for (const label of ['Dashboard', 'Clienti', 'Persone', 'Deal']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows Impostazioni to an admin', () => {
    mockAuth.ruolo = 'admin'
    render(<AppShell><div /></AppShell>)
    expect(screen.getByText('Impostazioni')).toBeInTheDocument()
  })

  it('hides Impostazioni from a non-admin', () => {
    mockAuth.ruolo = 'collaboratore'
    render(<AppShell><div /></AppShell>)
    expect(screen.queryByText('Impostazioni')).not.toBeInTheDocument()
  })

  it('renders its children', () => {
    render(<AppShell><p>contenuto</p></AppShell>)
    expect(screen.getByText('contenuto')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/components/AppShell.test.tsx`
Expected: FAIL — `Failed to resolve import "./AppShell"`

- [ ] **Step 3: Write `AppShell.tsx`**

```tsx
import { Link, useRouterState } from '@tanstack/react-router'
import { Building2, Handshake, LayoutDashboard, LogOut, Settings, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { useAuth, useIsAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/clienti', label: 'Clienti', icon: Building2 },
  { to: '/app/persone', label: 'Persone', icon: Users },
  { to: '/app/deal', label: 'Deal', icon: Handshake },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()

  const initials = (user?.nome ?? '?')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col border-r bg-card">
        <div className="px-5 py-6">
          <span className="text-xl font-semibold tracking-tight">
            Pigro<span className="text-[var(--color-watermelon)]">CRM</span>
          </span>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                location.pathname === to
                  ? 'bg-[var(--color-watermelon)] text-white'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          ))}

          {isAdmin && (
            <Link
              to="/app/impostazioni/campi"
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Settings className="size-4" />
              Impostazioni
            </Link>
          )}
        </nav>

        <Separator />
        <div className="flex items-center gap-3 p-4">
          <Avatar className="size-8">
            <AvatarFallback className="text-xs">{initials}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user?.nome}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.ruolo}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => void logout()} aria-label="Esci">
            <LogOut className="size-4" />
          </Button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
```

- [ ] **Step 4: Write the login route**

`apps/web/src/routes/login.tsx`:

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toProblem } from '@/lib/api'
import { useAuth } from '@/lib/auth'

function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await login(email, password)
      await navigate({ to: '/app' })
    } catch (error) {
      // The API deliberately does not say whether it was the email or the password.
      toast.error(toProblem(error).detail)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">
            Pigro<span className="text-[var(--color-watermelon)]">CRM</span>
          </CardTitle>
          <CardDescription>Il CRM che lavora al posto tuo.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? 'Accesso in corso…' : 'Accedi'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export const Route = createFileRoute('/login')({ component: LoginPage })
```

- [ ] **Step 5: Write the protected layout route**

`apps/web/src/routes/_app.tsx`:

```tsx
import { Outlet, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { AppShell } from '@/components/AppShell'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/auth'

function AppLayout() {
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!isLoading && !user) void navigate({ to: '/login' })
  }, [isLoading, user, navigate])

  if (isLoading) {
    return (
      <div className="space-y-4 p-8">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!user) return null

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

export const Route = createFileRoute('/_app')({ component: AppLayout })
```

`apps/web/src/routes/_app/index.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { useAuth } from '@/lib/auth'

function Dashboard() {
  const { user } = useAuth()
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Ciao {user?.nome}</h1>
      <p className="mt-2 text-muted-foreground">
        La dashboard con i grafici arriva nello slice 6. Per ora usa il menu a sinistra.
      </p>
    </div>
  )
}

export const Route = createFileRoute('/_app/')({ component: Dashboard })
```

Replace `apps/web/src/routes/index.tsx` with a redirect:

```tsx
import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: '/app' })
  },
})
```

Note: the file-based router maps `_app.tsx` to the URL prefix `/app`. Verify `routeTree.gen.ts`
regenerates with `/app`, `/app/`, and `/login` after `pnpm dev` runs once.

- [ ] **Step 6: Run the tests**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm build`
Expected: PASS (9 passed), clean types, successful build.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(web): app shell, login page and authenticated route layout"
```

---

# Phase 2 — The multiplier components

### Task 4: DynamicFieldRenderer and DynamicForm

The highest-leverage component in the frontend. Written once, it makes every custom field — present
and future — work in every form and every table with no further frontend work.

**Files:**
- Create: `apps/web/src/components/{DynamicFieldRenderer.tsx,DynamicForm.tsx}`
- Create: `apps/web/src/lib/schema.ts`
- Test: `apps/web/src/components/DynamicFieldRenderer.test.tsx`

**Interfaces:**
- Consumes: `api`, `queryKeys` (Task 2)
- Produces:
  - `FieldDefinition` type — `{ key, label, type, required, options }`
  - `useEntitySchema(entityType)` — `{ native_fields, custom_fields }`
  - `DynamicFieldRenderer({ field, value, onChange, error })` — the control
  - `renderFieldValue(field, value)` — the read-only cell
  - `DynamicForm({ fields, values, onChange, problem })` — a set of controls with server-side errors attached

- [ ] **Step 1: Write the failing test**

`apps/web/src/components/DynamicFieldRenderer.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DynamicFieldRenderer, renderFieldValue } from './DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'

const field = (over: Partial<FieldDefinition>): FieldDefinition => ({
  key: 'campo',
  label: 'Campo',
  type: 'text',
  required: false,
  options: [],
  ...over,
})

describe('DynamicFieldRenderer', () => {
  it('renders a text input with its label', () => {
    render(<DynamicFieldRenderer field={field({})} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toBeInTheDocument()
  })

  it('marks a required field', () => {
    render(<DynamicFieldRenderer field={field({ required: true })} value={null} onChange={vi.fn()} />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('renders a textarea for textarea fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'textarea' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo').tagName).toBe('TEXTAREA')
  })

  it('renders a numeric input for number fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'number' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toHaveAttribute('type', 'number')
  })

  it('renders a checkbox for checkbox fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'checkbox' })} value={false} onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('renders a date input for date fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'date' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toHaveAttribute('type', 'date')
  })

  it('offers every declared option for a select', async () => {
    render(
      <DynamicFieldRenderer
        field={field({ type: 'select', options: ['attivo', 'sospeso'] })}
        value={null}
        onChange={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('combobox'))
    expect(screen.getByText('attivo')).toBeInTheDocument()
    expect(screen.getByText('sospeso')).toBeInTheDocument()
  })

  it('reports edits through onChange', async () => {
    const onChange = vi.fn()
    render(<DynamicFieldRenderer field={field({})} value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Campo'), 'x')
    expect(onChange).toHaveBeenCalledWith('x')
  })

  it('shows the server-side error next to the input', () => {
    render(
      <DynamicFieldRenderer field={field({})} value={null} onChange={vi.fn()} error="deve essere di 11 cifre" />,
    )
    expect(screen.getByText('deve essere di 11 cifre')).toBeInTheDocument()
  })
})

describe('renderFieldValue', () => {
  it('shows an em dash for an empty value', () => {
    expect(renderFieldValue(field({}), null)).toBe('—')
  })

  it('formats currency in euros', () => {
    expect(renderFieldValue(field({ type: 'currency' }), '1234.56')).toContain('1.234,56')
  })

  it('formats dates in the Italian order', () => {
    expect(renderFieldValue(field({ type: 'date' }), '2026-08-06')).toBe('06/08/2026')
  })

  it('renders booleans as Sì / No', () => {
    expect(renderFieldValue(field({ type: 'checkbox' }), true)).toBe('Sì')
    expect(renderFieldValue(field({ type: 'checkbox' }), false)).toBe('No')
  })

  it('joins multiselect values', () => {
    expect(renderFieldValue(field({ type: 'multiselect' }), ['a', 'b'])).toBe('a, b')
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/components/DynamicFieldRenderer.test.tsx`
Expected: FAIL — `Failed to resolve import "./DynamicFieldRenderer"`

- [ ] **Step 3: Write `lib/schema.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './api'
import { queryKeys } from './query'

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
  | 'checkbox'
  | 'url'

export interface FieldDefinition {
  key: string
  label: string
  type: FieldType
  required: boolean
  options: string[]
}

export interface EntitySchema {
  entity_type: string
  native_fields: string[]
  custom_fields: FieldDefinition[]
}

/** Reads the live shape of an entity — the same document the MCP `describe_schema`
 *  tool returns, so the UI and an agent can never disagree about what exists. */
export function useEntitySchema(entityType: 'customer' | 'person' | 'deal') {
  return useQuery({
    queryKey: queryKeys.schema(entityType),
    queryFn: () =>
      unwrap(
        api.GET('/schema/{entity_type}', { params: { path: { entity_type: entityType } } }),
      ) as Promise<EntitySchema>,
  })
}
```

- [ ] **Step 4: Write `DynamicFieldRenderer.tsx`**

```tsx
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { FieldDefinition } from '@/lib/schema'
import { cn } from '@/lib/utils'

interface Props {
  field: FieldDefinition
  value: unknown
  onChange: (value: unknown) => void
  error?: string
}

const EMPTY = '—'

/** One definition in, the right control out. This is what makes a field added at
 *  runtime work in every form without touching the frontend. */
export function DynamicFieldRenderer({ field, value, onChange, error }: Props) {
  const id = `field-${field.key}`
  const invalid = Boolean(error)

  return (
    <div className="space-y-2">
      {field.type !== 'checkbox' && (
        <Label htmlFor={id}>
          {field.label}
          {field.required && <span className="ml-1 text-[var(--color-watermelon)]">*</span>}
        </Label>
      )}

      {(() => {
        switch (field.type) {
          case 'textarea':
            return (
              <Textarea
                id={id}
                rows={4}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'number':
          case 'currency':
            return (
              <Input
                id={id}
                type="number"
                step={field.type === 'currency' ? '0.01' : 'any'}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'date':
            return (
              <Input
                id={id}
                type="date"
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'url':
            return (
              <Input
                id={id}
                type="url"
                placeholder="https://"
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'checkbox':
            return (
              <div className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  checked={Boolean(value)}
                  onCheckedChange={(checked) => onChange(checked === true)}
                />
                <Label htmlFor={id} className="font-normal">
                  {field.label}
                  {field.required && <span className="ml-1 text-[var(--color-watermelon)]">*</span>}
                </Label>
              </div>
            )
          case 'select':
            return (
              <Select value={(value as string) ?? ''} onValueChange={onChange}>
                <SelectTrigger id={id} aria-invalid={invalid}>
                  <SelectValue placeholder="Seleziona…" />
                </SelectTrigger>
                <SelectContent>
                  {field.options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )
          case 'multiselect': {
            const selected = Array.isArray(value) ? (value as string[]) : []
            return (
              <div className="flex flex-wrap gap-3 rounded-md border p-3">
                {field.options.map((option) => (
                  <label key={option} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={selected.includes(option)}
                      onCheckedChange={(checked) =>
                        onChange(
                          checked === true
                            ? [...selected, option]
                            : selected.filter((item) => item !== option),
                        )
                      }
                    />
                    {option}
                  </label>
                ))}
              </div>
            )
          }
          default:
            return (
              <Input
                id={id}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
        }
      })()}

      {error && <p className={cn('text-sm', 'text-[var(--color-watermelon)]')}>{error}</p>}
    </div>
  )
}

/** The read-only counterpart, used by tables and detail panels. */
export function renderFieldValue(field: FieldDefinition, value: unknown): string {
  if (value === null || value === undefined || value === '') return EMPTY

  switch (field.type) {
    case 'currency':
      return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(
        Number(value),
      )
    case 'number':
      return new Intl.NumberFormat('it-IT').format(Number(value))
    case 'date':
      return new Intl.DateTimeFormat('it-IT').format(new Date(String(value)))
    case 'checkbox':
      return value ? 'Sì' : 'No'
    case 'multiselect':
      return Array.isArray(value) ? value.join(', ') : String(value)
    default:
      return String(value)
  }
}
```

- [ ] **Step 5: Write `DynamicForm.tsx`**

```tsx
import { DynamicFieldRenderer } from './DynamicFieldRenderer'
import { fieldErrorFrom, type ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

interface Props {
  fields: FieldDefinition[]
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  problem?: ProblemDetail | null
}

/** Errors come from the API's problem document, never from a client-side rule.
 *  Duplicating validation here is how the web app and the MCP server start
 *  disagreeing about what is valid. */
export function DynamicForm({ fields, values, onChange, problem }: Props) {
  const fieldError = problem ? fieldErrorFrom(problem) : null

  return (
    <div className="grid gap-5 sm:grid-cols-2">
      {fields.map((field) => (
        <DynamicFieldRenderer
          key={field.key}
          field={field}
          value={values[field.key] ?? null}
          onChange={(value) => onChange(field.key, value)}
          error={fieldError?.field === field.key ? fieldError.message : undefined}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/web && pnpm vitest run src/components/DynamicFieldRenderer.test.tsx`
Expected: PASS (14 passed)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(web): dynamic field renderer covering all nine field types"
```

---

### Task 5: EntityDetailLayout, DataTable and Timeline

**Files:**
- Create: `apps/web/src/components/{EntityDetailLayout.tsx,DataTable.tsx,Timeline.tsx}`
- Test: `apps/web/src/components/EntityDetailLayout.test.tsx`

**Interfaces:**
- Consumes: `renderFieldValue` (Task 4), `api`/`queryKeys` (Task 2)
- Produces:
  - `EntityDetailLayout({ title, subtitle, actions, overview, links, entityType, entityId })` — tabs *Panoramica · Timeline · Collegamenti*
  - `DataTable({ columns, data, isLoading, onRowClick, emptyMessage })`
  - `Timeline({ entityType, entityId })`

- [ ] **Step 1: Write the failing test**

`apps/web/src/components/EntityDetailLayout.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EntityDetailLayout } from './EntityDetailLayout'

vi.mock('./Timeline', () => ({ Timeline: () => <div>timeline-stub</div> }))

function renderLayout() {
  return render(
    <EntityDetailLayout
      title="ACME Srl"
      subtitle="Cliente"
      entityType="customer"
      entityId="abc"
      overview={<p>panoramica</p>}
      links={<p>collegamenti</p>}
    />,
  )
}

describe('EntityDetailLayout', () => {
  it('shows the title and subtitle', () => {
    renderLayout()
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
    expect(screen.getByText('Cliente')).toBeInTheDocument()
  })

  it('exposes the same three tabs for every entity', () => {
    renderLayout()
    for (const tab of ['Panoramica', 'Timeline', 'Collegamenti']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
    }
  })

  it('opens on Panoramica', () => {
    renderLayout()
    expect(screen.getByText('panoramica')).toBeInTheDocument()
  })

  it('switches to Collegamenti when asked', async () => {
    renderLayout()
    await userEvent.click(screen.getByRole('tab', { name: 'Collegamenti' }))
    expect(screen.getByText('collegamenti')).toBeInTheDocument()
  })

  it('switches to Timeline when asked', async () => {
    renderLayout()
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(screen.getByText('timeline-stub')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/components/EntityDetailLayout.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `Timeline.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query'
import { Bot, User } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { api, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

interface Entry {
  id: string
  kind: string
  actor_type: 'user' | 'mcp' | 'system'
  payload: Record<string, unknown>
  occurred_at: string
}

const KIND_LABELS: Record<string, string> = {
  created: 'Creato',
  updated: 'Modificato',
  deleted: 'Archiviato',
  restored: 'Ripristinato',
  stage_changed: 'Stato cambiato',
}

const PATHS = {
  customer: '/customers/{customer_id}/timeline',
  person: '/people/{person_id}/timeline',
  deal: '/deals/{deal_id}/timeline',
} as const

export function Timeline({
  entityType,
  entityId,
}: {
  entityType: keyof typeof PATHS
  entityId: string
}) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.timeline(entityType, entityId),
    queryFn: () =>
      unwrap(
        // The path parameter name differs per entity; the shape of the response does not.
        api.GET(PATHS[entityType] as never, {
          params: { path: { [`${entityType}_id`]: entityId } },
        } as never),
      ) as Promise<Entry[]>,
  })

  if (isLoading) return <Skeleton className="h-40 w-full" />
  if (!data?.length) return <p className="text-muted-foreground">Nessuna attività registrata.</p>

  return (
    <ol className="space-y-3">
      {data.map((entry) => (
        <li key={entry.id} className="flex items-start gap-3 rounded-md border p-3">
          <span className="mt-0.5 text-muted-foreground">
            {/* Whether a human or an agent did this is the first thing you want to
                know when something looks wrong. */}
            {entry.actor_type === 'mcp' ? <Bot className="size-4" /> : <User className="size-4" />}
          </span>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{KIND_LABELS[entry.kind] ?? entry.kind}</span>
              {entry.actor_type === 'mcp' && <Badge variant="secondary">AI</Badge>}
            </div>
            <p className="text-sm text-muted-foreground">
              {new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' }).format(
                new Date(entry.occurred_at),
              )}
            </p>
            {'changed' in entry.payload && (
              <p className="mt-1 text-sm">
                Campi: {(entry.payload.changed as string[]).join(', ')}
              </p>
            )}
            {'from' in entry.payload && (
              <p className="mt-1 text-sm">
                Da <strong>{String(entry.payload.from)}</strong> a{' '}
                <strong>{String(entry.payload.to)}</strong>
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
```

- [ ] **Step 4: Write `EntityDetailLayout.tsx`**

```tsx
import type { ReactNode } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Timeline } from './Timeline'

interface Props {
  title: string
  subtitle?: string
  actions?: ReactNode
  overview: ReactNode
  links?: ReactNode
  entityType: 'customer' | 'person' | 'deal'
  entityId: string
}

/** One layout for Customer, Person and Deal.
 *
 *  Three similar pages drift apart; one component cannot. Later slices add
 *  Documenti, Attività and Fatture as further tabs here, once, for all three. */
export function EntityDetailLayout({
  title,
  subtitle,
  actions,
  overview,
  links,
  entityType,
  entityId,
}: Props) {
  return (
    <div className="p-8">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
        </div>
        {actions && <div className="flex gap-2">{actions}</div>}
      </header>

      <Tabs defaultValue="panoramica">
        <TabsList>
          <TabsTrigger value="panoramica">Panoramica</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="collegamenti">Collegamenti</TabsTrigger>
        </TabsList>

        <TabsContent value="panoramica" className="mt-6">
          {overview}
        </TabsContent>
        <TabsContent value="timeline" className="mt-6">
          <Timeline entityType={entityType} entityId={entityId} />
        </TabsContent>
        <TabsContent value="collegamenti" className="mt-6">
          {links ?? <p className="text-muted-foreground">Nessun collegamento.</p>}
        </TabsContent>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 5: Write `DataTable.tsx`**

```tsx
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface Props<T> {
  columns: ColumnDef<T, unknown>[]
  data: T[]
  isLoading?: boolean
  onRowClick?: (row: T) => void
  emptyMessage?: string
}

export function DataTable<T>({
  columns,
  data,
  isLoading,
  onRowClick,
  emptyMessage = 'Nessun risultato.',
}: Props<T>) {
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  return (
    <div className="rounded-md border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                onClick={() => onRowClick?.(row.original)}
                className={onRowClick ? 'cursor-pointer' : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit`
Expected: PASS (19 passed), clean types.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(web): shared entity layout, data table and actor-aware timeline"
```

---

# Phase 3 — Feature pages

### Task 6: Customers — list and detail

**Files:**
- Create: `apps/web/src/features/customers/{queries.ts,columns.tsx,CustomerForm.tsx}`
- Create: `apps/web/src/routes/_app/{clienti.index.tsx,clienti.$customerId.tsx}`
- Test: `apps/web/src/features/customers/queries.test.ts`

**Interfaces:**
- Consumes: `api`, `queryKeys`, `useEntitySchema`, `DynamicForm`, `DataTable`, `EntityDetailLayout`
- Produces: `useCustomers(params)`, `useCustomer(id)`, `useCreateCustomer()`, `useUpdateCustomer(id)`, `useDeleteCustomer()`, `buildCustomerColumns(customFields)`, `CustomerForm`

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/customers/queries.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildCustomerColumns } from './columns'
import type { FieldDefinition } from '@/lib/schema'

describe('buildCustomerColumns', () => {
  it('always shows the core commercial columns', () => {
    const headers = buildCustomerColumns([]).map((column) => column.header)
    expect(headers).toEqual(['Ragione sociale', 'P.IVA', 'Comune', 'Email', 'Telefono'])
  })

  it('appends one column per custom field', () => {
    const fields: FieldDefinition[] = [
      { key: 'settore', label: 'Settore', type: 'text', required: false, options: [] },
    ]
    const headers = buildCustomerColumns(fields).map((column) => column.header)
    expect(headers).toContain('Settore')
  })

  it('does not add columns for archived fields, which are simply not returned', () => {
    expect(buildCustomerColumns([])).toHaveLength(5)
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/customers`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `features/customers/queries.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

export interface Customer {
  id: string
  ragione_sociale: string
  partita_iva: string | null
  codice_fiscale: string | null
  codice_sdi: string | null
  pec: string | null
  indirizzo: string | null
  cap: string | null
  comune: string | null
  provincia: string | null
  nazione: string
  email: string | null
  telefono: string | null
  sito_web: string | null
  stato: string | null
  note: string | null
  custom_fields: Record<string, unknown>
}

export interface CustomerPage {
  items: Customer[]
  next_cursor: string | null
}

export function useCustomers(params: { search?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.customers(params),
    queryFn: () =>
      unwrap(api.GET('/customers', { params: { query: params } })) as Promise<CustomerPage>,
  })
}

export function useCustomer(customerId: string) {
  return useQuery({
    queryKey: queryKeys.customer(customerId),
    queryFn: () =>
      unwrap(
        api.GET('/customers/{customer_id}', { params: { path: { customer_id: customerId } } }),
      ) as Promise<Customer>,
  })
}

export function useCreateCustomer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/customers', { body: body as never })) as Promise<Customer>,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['customers'] }),
  })
}

export function useUpdateCustomer(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/customers/{customer_id}', {
          params: { path: { customer_id: customerId } },
          body: body as never,
        }),
      ) as Promise<Customer>,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customer(customerId) })
      void queryClient.invalidateQueries({ queryKey: ['customers'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('customer', customerId) })
    },
  })
}

export function useDeleteCustomer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (customerId: string) =>
      unwrap(
        api.DELETE('/customers/{customer_id}', { params: { path: { customer_id: customerId } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['customers'] }),
  })
}
```

- [ ] **Step 4: Write `features/customers/columns.tsx`**

```tsx
import type { ColumnDef } from '@tanstack/react-table'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Customer } from './queries'

const EMPTY = '—'

/** Native columns first, then one per custom field — so a field defined at runtime
 *  shows up in the table with no code change. */
export function buildCustomerColumns(
  customFields: FieldDefinition[],
): ColumnDef<Customer, unknown>[] {
  const native: ColumnDef<Customer, unknown>[] = [
    { header: 'Ragione sociale', accessorKey: 'ragione_sociale' },
    { header: 'P.IVA', accessorFn: (row) => row.partita_iva ?? EMPTY, id: 'partita_iva' },
    { header: 'Comune', accessorFn: (row) => row.comune ?? EMPTY, id: 'comune' },
    { header: 'Email', accessorFn: (row) => row.email ?? EMPTY, id: 'email' },
    { header: 'Telefono', accessorFn: (row) => row.telefono ?? EMPTY, id: 'telefono' },
  ]

  const custom: ColumnDef<Customer, unknown>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
```

- [ ] **Step 5: Write `features/customers/CustomerForm.tsx`**

```tsx
import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'ragione_sociale', label: 'Ragione sociale', type: 'text', required: true, options: [] },
  { key: 'partita_iva', label: 'P.IVA', type: 'text', required: false, options: [] },
  { key: 'codice_fiscale', label: 'Codice fiscale', type: 'text', required: false, options: [] },
  { key: 'codice_sdi', label: 'Codice SDI', type: 'text', required: false, options: [] },
  { key: 'pec', label: 'PEC', type: 'text', required: false, options: [] },
  { key: 'indirizzo', label: 'Indirizzo', type: 'text', required: false, options: [] },
  { key: 'cap', label: 'CAP', type: 'text', required: false, options: [] },
  { key: 'comune', label: 'Comune', type: 'text', required: false, options: [] },
  { key: 'provincia', label: 'Provincia', type: 'text', required: false, options: [] },
  { key: 'email', label: 'Email', type: 'text', required: false, options: [] },
  { key: 'telefono', label: 'Telefono', type: 'text', required: false, options: [] },
  { key: 'sito_web', label: 'Sito web', type: 'url', required: false, options: [] },
  { key: 'note', label: 'Note', type: 'textarea', required: false, options: [] },
]

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  customFields: FieldDefinition[]
  initial?: Record<string, unknown>
  problem?: ProblemDetail | null
  busy?: boolean
  onSubmit: (values: Record<string, unknown>) => void
  title: string
}

export function CustomerForm({
  open,
  onOpenChange,
  customFields,
  initial,
  problem,
  busy,
  onSubmit,
  title,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(initial ?? {})

  function submit() {
    const custom: Record<string, unknown> = {}
    const native: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
      if (value === '' || value === null) continue
      if (customFields.some((field) => field.key === key)) custom[key] = value
      else native[key] = value
    }
    onSubmit({ ...native, custom_fields: custom })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <DynamicForm
          fields={[...NATIVE_FIELDS, ...customFields]}
          values={values}
          onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
          problem={problem}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? 'Salvataggio…' : 'Salva'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 6: Write the list route**

`apps/web/src/routes/_app/clienti.index.tsx`:

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CustomerForm } from '@/features/customers/CustomerForm'
import { buildCustomerColumns } from '@/features/customers/columns'
import { useCreateCustomer, useCustomers } from '@/features/customers/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function CustomersPage() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('customer')
  const customers = useCustomers({ search: search || undefined })
  const create = useCreateCustomer()

  const columns = buildCustomerColumns(schema.data?.custom_fields ?? [])

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Clienti</h1>
        {canWrite && (
          <Button onClick={() => { setProblem(null); setOpen(true) }}>
            <Plus className="mr-2 size-4" />
            Nuovo cliente
          </Button>
        )}
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per nome, P.IVA o email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <DataTable
        columns={columns}
        data={customers.data?.items ?? []}
        isLoading={customers.isLoading}
        onRowClick={(row) =>
          void navigate({ to: '/app/clienti/$customerId', params: { customerId: row.id } })
        }
        emptyMessage="Nessun cliente. Creane uno per iniziare."
      />

      <CustomerForm
        title="Nuovo cliente"
        open={open}
        onOpenChange={setOpen}
        customFields={schema.data?.custom_fields ?? []}
        problem={problem}
        busy={create.isPending}
        onSubmit={(values) => {
          setProblem(null)
          create.mutate(values, {
            onSuccess: () => {
              setOpen(false)
              toast.success('Cliente creato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/_app/clienti/')({ component: CustomersPage })
```

- [ ] **Step 7: Write the detail route**

`apps/web/src/routes/_app/clienti.$customerId.tsx`:

```tsx
import { createFileRoute, useNavigate, useParams } from '@tanstack/react-router'
import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { CustomerForm } from '@/features/customers/CustomerForm'
import { useCustomer, useDeleteCustomer, useUpdateCustomer } from '@/features/customers/queries'
import { usePeople } from '@/features/people/queries'
import { useDeals } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function CustomerDetail() {
  const { customerId } = useParams({ from: '/_app/clienti/$customerId' })
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [editing, setEditing] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('customer')
  const { data: customer, isLoading } = useCustomer(customerId)
  const update = useUpdateCustomer(customerId)
  const remove = useDeleteCustomer()
  const people = usePeople({ customer_id: customerId })
  const deals = useDeals({ customer_id: customerId })

  if (isLoading) return <Skeleton className="m-8 h-96" />
  if (!customer) return <p className="p-8">Cliente non trovato.</p>

  const custom = schema.data?.custom_fields ?? []
  const empty = '—'

  return (
    <>
      <EntityDetailLayout
        title={customer.ragione_sociale}
        subtitle="Cliente"
        entityType="customer"
        entityId={customerId}
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => { setProblem(null); setEditing(true) }}>
                <Pencil className="mr-2 size-4" />
                Modifica
              </Button>
              <Button
                variant="destructive"
                onClick={() =>
                  remove.mutate(customerId, {
                    onSuccess: () => {
                      toast.success('Cliente archiviato')
                      void navigate({ to: '/app/clienti' })
                    },
                    // A customer with active deals is refused, and the API says how many.
                    onError: (error) => toast.error(toProblem(error).detail),
                  })
                }
              >
                <Trash2 className="mr-2 size-4" />
                Archivia
              </Button>
            </>
          )
        }
        overview={
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Dati fiscali</h2>
                <Row label="P.IVA" value={customer.partita_iva ?? empty} />
                <Row label="Codice fiscale" value={customer.codice_fiscale ?? empty} />
                <Row label="Codice SDI" value={customer.codice_sdi ?? empty} />
                <Row label="PEC" value={customer.pec ?? empty} />
                <Row
                  label="Indirizzo"
                  value={
                    customer.indirizzo
                      ? `${customer.indirizzo}, ${customer.cap ?? ''} ${customer.comune ?? ''} (${customer.provincia ?? ''})`
                      : empty
                  }
                />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Contatti</h2>
                <Row label="Email" value={customer.email ?? empty} />
                <Row label="Telefono" value={customer.telefono ?? empty} />
                <Row label="Sito web" value={customer.sito_web ?? empty} />
              </CardContent>
            </Card>

            {custom.length > 0 && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Campi personalizzati</h2>
                  {custom.map((field) => (
                    <Row
                      key={field.key}
                      label={field.label}
                      value={renderFieldValue(field, customer.custom_fields[field.key])}
                    />
                  ))}
                </CardContent>
              </Card>
            )}

            {customer.note && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Note</h2>
                  <p className="whitespace-pre-wrap text-sm">{customer.note}</p>
                </CardContent>
              </Card>
            )}
          </div>
        }
        links={
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Persone ({people.data?.items.length ?? 0})</h2>
                {people.data?.items.map((person) => (
                  <Row
                    key={person.id}
                    label={`${person.nome} ${person.cognome ?? ''}`}
                    value={person.email ?? empty}
                  />
                )) ?? null}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Deal ({deals.data?.items.length ?? 0})</h2>
                {deals.data?.items.map((deal) => (
                  <Row
                    key={deal.id}
                    label={deal.nome}
                    value={deal.valore_previsto ? String(deal.valore_previsto) : empty}
                  />
                )) ?? null}
              </CardContent>
            </Card>
          </div>
        }
      />

      <CustomerForm
        title="Modifica cliente"
        open={editing}
        onOpenChange={setEditing}
        customFields={custom}
        initial={{ ...customer, ...customer.custom_fields }}
        problem={problem}
        busy={update.isPending}
        onSubmit={(values) => {
          setProblem(null)
          update.mutate(values, {
            onSuccess: () => {
              setEditing(false)
              toast.success('Cliente aggiornato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </>
  )
}

export const Route = createFileRoute('/_app/clienti/$customerId')({ component: CustomerDetail })
```

- [ ] **Step 8: Run the tests**

Run: `cd apps/web && pnpm vitest run src/features/customers`
Expected: PASS (3 passed). `pnpm tsc --noEmit` will still fail on the `usePeople`/`useDeals` imports
until Tasks 7 and 8 land — that is expected and is why those tasks come next.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(web): customers list and detail with runtime custom-field columns"
```

---

### Task 7: People — list and detail

**Files:**
- Create: `apps/web/src/features/people/{queries.ts,columns.tsx,PersonForm.tsx}`
- Create: `apps/web/src/routes/_app/{persone.index.tsx,persone.$personId.tsx}`
- Test: `apps/web/src/features/people/columns.test.ts`

**Interfaces:**
- Consumes: the same building blocks as Task 6
- Produces: `usePeople(params)`, `usePerson(id)`, `useCreatePerson()`, `useUpdatePerson(id)`, `useDeletePerson()`, `buildPersonColumns(customFields)`, `PersonForm`

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/people/columns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildPersonColumns } from './columns'

describe('buildPersonColumns', () => {
  it('shows the columns you need to call someone', () => {
    expect(buildPersonColumns([]).map((column) => column.header)).toEqual([
      'Nome',
      'Cognome',
      'Ruolo',
      'Email',
      'Telefono',
    ])
  })

  it('appends custom field columns', () => {
    const headers = buildPersonColumns([
      { key: 'seniority', label: 'Seniority', type: 'text', required: false, options: [] },
    ]).map((column) => column.header)
    expect(headers).toContain('Seniority')
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/people`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `features/people/queries.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

export interface Person {
  id: string
  nome: string
  cognome: string | null
  email: string | null
  telefono: string | null
  ruolo: string | null
  linkedin: string | null
  note: string | null
  customer_id: string | null
  custom_fields: Record<string, unknown>
}

export interface PersonPage {
  items: Person[]
  next_cursor: string | null
}

export function usePeople(params: { search?: string; customer_id?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.people(params),
    queryFn: () => unwrap(api.GET('/people', { params: { query: params } })) as Promise<PersonPage>,
  })
}

export function usePerson(personId: string) {
  return useQuery({
    queryKey: queryKeys.person(personId),
    queryFn: () =>
      unwrap(
        api.GET('/people/{person_id}', { params: { path: { person_id: personId } } }),
      ) as Promise<Person>,
  })
}

export function useCreatePerson() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/people', { body: body as never })) as Promise<Person>,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['people'] }),
  })
}

export function useUpdatePerson(personId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/people/{person_id}', {
          params: { path: { person_id: personId } },
          body: body as never,
        }),
      ) as Promise<Person>,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.person(personId) })
      void queryClient.invalidateQueries({ queryKey: ['people'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('person', personId) })
    },
  })
}

export function useDeletePerson() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (personId: string) =>
      unwrap(api.DELETE('/people/{person_id}', { params: { path: { person_id: personId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['people'] }),
  })
}
```

- [ ] **Step 4: Write `features/people/columns.tsx`**

```tsx
import type { ColumnDef } from '@tanstack/react-table'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Person } from './queries'

const EMPTY = '—'

export function buildPersonColumns(customFields: FieldDefinition[]): ColumnDef<Person, unknown>[] {
  const native: ColumnDef<Person, unknown>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    { header: 'Cognome', accessorFn: (row) => row.cognome ?? EMPTY, id: 'cognome' },
    { header: 'Ruolo', accessorFn: (row) => row.ruolo ?? EMPTY, id: 'ruolo' },
    { header: 'Email', accessorFn: (row) => row.email ?? EMPTY, id: 'email' },
    { header: 'Telefono', accessorFn: (row) => row.telefono ?? EMPTY, id: 'telefono' },
  ]

  const custom: ColumnDef<Person, unknown>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
```

- [ ] **Step 5: Write `features/people/PersonForm.tsx`**

```tsx
import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { useCustomers } from '@/features/customers/queries'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'nome', label: 'Nome', type: 'text', required: true, options: [] },
  { key: 'cognome', label: 'Cognome', type: 'text', required: false, options: [] },
  { key: 'email', label: 'Email', type: 'text', required: false, options: [] },
  { key: 'telefono', label: 'Telefono', type: 'text', required: false, options: [] },
  { key: 'ruolo', label: 'Ruolo', type: 'text', required: false, options: [] },
  { key: 'linkedin', label: 'LinkedIn', type: 'url', required: false, options: [] },
  { key: 'note', label: 'Note', type: 'textarea', required: false, options: [] },
]

const NO_CUSTOMER = '__nessuno__'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  customFields: FieldDefinition[]
  initial?: Record<string, unknown>
  problem?: ProblemDetail | null
  busy?: boolean
  onSubmit: (values: Record<string, unknown>) => void
  title: string
}

export function PersonForm({
  open,
  onOpenChange,
  customFields,
  initial,
  problem,
  busy,
  onSubmit,
  title,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(initial ?? {})
  const customers = useCustomers({ limit: 200 })

  function submit() {
    const custom: Record<string, unknown> = {}
    const native: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
      if (value === '' || value === null) continue
      if (key === 'customer_id') {
        // The association is optional by design; "nessuno" means detach.
        if (value !== NO_CUSTOMER) native.customer_id = value
        continue
      }
      if (customFields.some((field) => field.key === key)) custom[key] = value
      else native[key] = value
    }
    onSubmit({ ...native, custom_fields: custom })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="customer">Cliente</Label>
          <Select
            value={(values.customer_id as string) ?? NO_CUSTOMER}
            onValueChange={(value) => setValues((prev) => ({ ...prev, customer_id: value }))}
          >
            <SelectTrigger id="customer">
              <SelectValue placeholder="Nessun cliente" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CUSTOMER}>Nessun cliente</SelectItem>
              {customers.data?.items.map((customer) => (
                <SelectItem key={customer.id} value={customer.id}>
                  {customer.ragione_sociale}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <DynamicForm
          fields={[...NATIVE_FIELDS, ...customFields]}
          values={values}
          onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
          problem={problem}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? 'Salvataggio…' : 'Salva'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 6: Write the two routes**

`apps/web/src/routes/_app/persone.index.tsx` — identical structure to the customers list, with
`usePeople`, `buildPersonColumns`, `PersonForm`, heading `Persone`, button `Nuova persona`, search
placeholder `Cerca per nome, cognome o email…`, empty message `Nessuna persona.`, and row click
navigating to `/app/persone/$personId`.

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PersonForm } from '@/features/people/PersonForm'
import { buildPersonColumns } from '@/features/people/columns'
import { useCreatePerson, usePeople } from '@/features/people/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function PeoplePage() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('person')
  const people = usePeople({ search: search || undefined })
  const create = useCreatePerson()

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Persone</h1>
        {canWrite && (
          <Button onClick={() => { setProblem(null); setOpen(true) }}>
            <Plus className="mr-2 size-4" />
            Nuova persona
          </Button>
        )}
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per nome, cognome o email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <DataTable
        columns={buildPersonColumns(schema.data?.custom_fields ?? [])}
        data={people.data?.items ?? []}
        isLoading={people.isLoading}
        onRowClick={(row) =>
          void navigate({ to: '/app/persone/$personId', params: { personId: row.id } })
        }
        emptyMessage="Nessuna persona. Creane una per iniziare."
      />

      <PersonForm
        title="Nuova persona"
        open={open}
        onOpenChange={setOpen}
        customFields={schema.data?.custom_fields ?? []}
        problem={problem}
        busy={create.isPending}
        onSubmit={(values) => {
          setProblem(null)
          create.mutate(values, {
            onSuccess: () => {
              setOpen(false)
              toast.success('Persona creata')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/_app/persone/')({ component: PeoplePage })
```

`apps/web/src/routes/_app/persone.$personId.tsx`:

```tsx
import { createFileRoute, useNavigate, useParams } from '@tanstack/react-router'
import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCustomer } from '@/features/customers/queries'
import { PersonForm } from '@/features/people/PersonForm'
import { useDeletePerson, usePerson, useUpdatePerson } from '@/features/people/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

const EMPTY = '—'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function PersonDetail() {
  const { personId } = useParams({ from: '/_app/persone/$personId' })
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [editing, setEditing] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('person')
  const { data: person, isLoading } = usePerson(personId)
  const update = useUpdatePerson(personId)
  const remove = useDeletePerson()
  const customer = useCustomer(person?.customer_id ?? '')

  if (isLoading) return <Skeleton className="m-8 h-96" />
  if (!person) return <p className="p-8">Persona non trovata.</p>

  const custom = schema.data?.custom_fields ?? []

  return (
    <>
      <EntityDetailLayout
        title={`${person.nome} ${person.cognome ?? ''}`.trim()}
        subtitle={person.ruolo ?? 'Persona'}
        entityType="person"
        entityId={personId}
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => { setProblem(null); setEditing(true) }}>
                <Pencil className="mr-2 size-4" />
                Modifica
              </Button>
              <Button
                variant="destructive"
                onClick={() =>
                  remove.mutate(personId, {
                    onSuccess: () => {
                      toast.success('Persona archiviata')
                      void navigate({ to: '/app/persone' })
                    },
                    onError: (error) => toast.error(toProblem(error).detail),
                  })
                }
              >
                <Trash2 className="mr-2 size-4" />
                Archivia
              </Button>
            </>
          )
        }
        overview={
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Contatti</h2>
                <Row label="Email" value={person.email ?? EMPTY} />
                <Row label="Telefono" value={person.telefono ?? EMPTY} />
                <Row label="LinkedIn" value={person.linkedin ?? EMPTY} />
              </CardContent>
            </Card>

            {custom.length > 0 && (
              <Card>
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Campi personalizzati</h2>
                  {custom.map((field) => (
                    <Row
                      key={field.key}
                      label={field.label}
                      value={renderFieldValue(field, person.custom_fields[field.key])}
                    />
                  ))}
                </CardContent>
              </Card>
            )}

            {person.note && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Note</h2>
                  <p className="whitespace-pre-wrap text-sm">{person.note}</p>
                </CardContent>
              </Card>
            )}
          </div>
        }
        links={
          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-3 font-semibold">Cliente</h2>
              {person.customer_id ? (
                <Row label="Ragione sociale" value={customer.data?.ragione_sociale ?? '…'} />
              ) : (
                <p className="text-muted-foreground">Questa persona non è associata a un cliente.</p>
              )}
            </CardContent>
          </Card>
        }
      />

      <PersonForm
        title="Modifica persona"
        open={editing}
        onOpenChange={setEditing}
        customFields={custom}
        initial={{ ...person, ...person.custom_fields }}
        problem={problem}
        busy={update.isPending}
        onSubmit={(values) => {
          setProblem(null)
          update.mutate(values, {
            onSuccess: () => {
              setEditing(false)
              toast.success('Persona aggiornata')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </>
  )
}

export const Route = createFileRoute('/_app/persone/$personId')({ component: PersonDetail })
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/web && pnpm vitest run src/features/people`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(web): people list and detail with optional customer association"
```

---

### Task 8: Deals — Kanban, list and detail

**Files:**
- Create: `apps/web/src/features/deals/{queries.ts,columns.tsx,DealForm.tsx,KanbanBoard.tsx,KanbanCard.tsx}`
- Create: `apps/web/src/routes/_app/{deal.index.tsx,deal.lista.tsx,deal.$dealId.tsx}`
- Test: `apps/web/src/features/deals/KanbanBoard.test.tsx`

**Interfaces:**
- Consumes: `useEntitySchema`, `DataTable`, `EntityDetailLayout`, `DynamicForm`
- Produces: `useDeals(params)`, `useDeal(id)`, `useCreateDeal()`, `useUpdateDeal(id)`, `useMoveDeal()`, `useDeleteDeal()`, `useStages()`, `buildDealColumns(customFields)`, `KanbanBoard`, `DealForm`

- [ ] **Step 1: Install dnd-kit and write the failing test**

```bash
cd apps/web && pnpm add @dnd-kit/core@6.3.1 @dnd-kit/sortable@10.0.0 && cd ../..
```

`apps/web/src/features/deals/KanbanBoard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { KanbanBoard } from './KanbanBoard'
import type { Deal } from './queries'

const STAGES = [
  { id: 's1', nome: 'Lead', posizione: 0, probabilita_default: 10, tipo: 'open' as const },
  { id: 's2', nome: 'Offerta', posizione: 1, probabilita_default: 50, tipo: 'open' as const },
  { id: 's3', nome: 'Vinto', posizione: 2, probabilita_default: 100, tipo: 'won' as const },
]

const DEALS = [
  { id: 'd1', nome: 'Progetto A', pipeline_stage_id: 's1', valore_previsto: '1000.00', probabilita: 10 },
  { id: 'd2', nome: 'Progetto B', pipeline_stage_id: 's2', valore_previsto: '2500.50', probabilita: 50 },
] as unknown as Deal[]

describe('KanbanBoard', () => {
  it('renders one column per stage', () => {
    render(<KanbanBoard stages={STAGES} deals={DEALS} onMove={vi.fn()} onOpen={vi.fn()} />)
    for (const stage of ['Lead', 'Offerta', 'Vinto']) {
      expect(screen.getByText(stage)).toBeInTheDocument()
    }
  })

  it('places each deal in its own stage', () => {
    render(<KanbanBoard stages={STAGES} deals={DEALS} onMove={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByText('Progetto A')).toBeInTheDocument()
    expect(screen.getByText('Progetto B')).toBeInTheDocument()
  })

  it('shows the total value per column in euros', () => {
    render(<KanbanBoard stages={STAGES} deals={DEALS} onMove={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByText(/2\.500,50/)).toBeInTheDocument()
  })

  it('shows a per-column count', () => {
    render(<KanbanBoard stages={STAGES} deals={DEALS} onMove={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(2)
  })

  it('renders empty stages too, so the pipeline shape stays visible', () => {
    render(<KanbanBoard stages={STAGES} deals={[]} onMove={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getAllByText('Nessun deal')).toHaveLength(3)
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/deals`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `features/deals/queries.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

export interface Deal {
  id: string
  nome: string
  customer_id: string
  pipeline_stage_id: string
  valore_previsto: string | null
  probabilita: number
  data_chiusura_prevista: string | null
  note: string | null
  ore_preventivate: string | null
  valore_preventivato: string | null
  custom_fields: Record<string, unknown>
}

export interface DealPage {
  items: Deal[]
  next_cursor: string | null
}

export interface Stage {
  id: string
  nome: string
  posizione: number
  probabilita_default: number
  tipo: 'open' | 'won' | 'lost'
}

export function useStages() {
  return useQuery({
    queryKey: queryKeys.stages,
    queryFn: () => unwrap(api.GET('/pipeline-stages')) as Promise<Stage[]>,
  })
}

export function useDeals(params: { search?: string; customer_id?: string; stage_id?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.deals(params),
    queryFn: () => unwrap(api.GET('/deals', { params: { query: params } })) as Promise<DealPage>,
  })
}

export function useDeal(dealId: string) {
  return useQuery({
    queryKey: queryKeys.deal(dealId),
    queryFn: () =>
      unwrap(api.GET('/deals/{deal_id}', { params: { path: { deal_id: dealId } } })) as Promise<Deal>,
  })
}

export function useCreateDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/deals', { body: body as never })) as Promise<Deal>,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['deals'] }),
  })
}

export function useUpdateDeal(dealId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/deals/{deal_id}', {
          params: { path: { deal_id: dealId } },
          body: body as never,
        }),
      ) as Promise<Deal>,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.deal(dealId) })
      void queryClient.invalidateQueries({ queryKey: ['deals'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('deal', dealId) })
    },
  })
}

/** Optimistic: dragging a card and then watching a spinner is the kind of friction
 *  that makes a CRM unpleasant. On failure the board snaps back and says why. */
export function useMoveDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ dealId, stageId }: { dealId: string; stageId: string }) =>
      unwrap(
        api.PATCH('/deals/{deal_id}/stage', {
          params: { path: { deal_id: dealId } },
          body: { stage_id: stageId },
        }),
      ) as Promise<Deal>,
    onMutate: async ({ dealId, stageId }) => {
      await queryClient.cancelQueries({ queryKey: ['deals'] })
      const snapshot = queryClient.getQueriesData<DealPage>({ queryKey: ['deals'] })
      for (const [key, page] of snapshot) {
        if (!page) continue
        queryClient.setQueryData<DealPage>(key, {
          ...page,
          items: page.items.map((deal) =>
            deal.id === dealId ? { ...deal, pipeline_stage_id: stageId } : deal,
          ),
        })
      }
      return { snapshot }
    },
    onError: (_error, _variables, context) => {
      for (const [key, page] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, page)
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['deals'] }),
  })
}

export function useDeleteDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (dealId: string) =>
      unwrap(api.DELETE('/deals/{deal_id}', { params: { path: { deal_id: dealId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['deals'] }),
  })
}
```

- [ ] **Step 4: Write `KanbanCard.tsx` and `KanbanBoard.tsx`**

`apps/web/src/features/deals/KanbanCard.tsx`:

```tsx
import { useDraggable } from '@dnd-kit/core'
import { Card, CardContent } from '@/components/ui/card'
import type { Deal } from './queries'

const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' })

export function KanbanCard({ deal, onOpen }: { deal: Deal; onOpen: (id: string) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: deal.id })

  return (
    <Card
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={() => onOpen(deal.id)}
      style={
        transform
          ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 50 }
          : undefined
      }
      className={`cursor-grab active:cursor-grabbing ${isDragging ? 'opacity-60 shadow-lg' : ''}`}
    >
      <CardContent className="space-y-1 p-3">
        <p className="text-sm font-medium">{deal.nome}</p>
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{deal.valore_previsto ? euro.format(Number(deal.valore_previsto)) : '—'}</span>
          <span>{deal.probabilita}%</span>
        </div>
      </CardContent>
    </Card>
  )
}
```

`apps/web/src/features/deals/KanbanBoard.tsx`:

```tsx
import { DndContext, PointerSensor, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import { Badge } from '@/components/ui/badge'
import { KanbanCard } from './KanbanCard'
import type { Deal, Stage } from './queries'

const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' })

function Column({
  stage,
  deals,
  onOpen,
}: {
  stage: Stage
  deals: Deal[]
  onOpen: (id: string) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id })
  const total = deals.reduce((sum, deal) => sum + Number(deal.valore_previsto ?? 0), 0)

  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold">{stage.nome}</h2>
          <Badge variant="secondary">{deals.length}</Badge>
        </div>
        <span className="text-xs text-muted-foreground">{euro.format(total)}</span>
      </div>

      <div
        ref={setNodeRef}
        className={`min-h-40 flex-1 space-y-2 rounded-md border border-dashed p-2 transition-colors ${
          isOver ? 'border-[var(--color-watermelon)] bg-muted' : ''
        }`}
      >
        {deals.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Nessun deal</p>
        ) : (
          deals.map((deal) => <KanbanCard key={deal.id} deal={deal} onOpen={onOpen} />)
        )}
      </div>
    </div>
  )
}

interface Props {
  stages: Stage[]
  deals: Deal[]
  onMove: (dealId: string, stageId: string) => void
  onOpen: (dealId: string) => void
}

export function KanbanBoard({ stages, deals, onMove, onOpen }: Props) {
  // A small activation distance keeps a click on a card from registering as a drag.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  function handleDragEnd(event: DragEndEvent) {
    const stageId = event.over?.id
    if (!stageId || typeof stageId !== 'string') return
    const deal = deals.find((item) => item.id === event.active.id)
    if (!deal || deal.pipeline_stage_id === stageId) return
    onMove(deal.id, stageId)
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className="flex gap-4 overflow-x-auto pb-4">
        {[...stages]
          .sort((a, b) => a.posizione - b.posizione)
          .map((stage) => (
            <Column
              key={stage.id}
              stage={stage}
              deals={deals.filter((deal) => deal.pipeline_stage_id === stage.id)}
              onOpen={onOpen}
            />
          ))}
      </div>
    </DndContext>
  )
}
```

- [ ] **Step 5: Write `columns.tsx` and `DealForm.tsx`**

`apps/web/src/features/deals/columns.tsx`:

```tsx
import type { ColumnDef } from '@tanstack/react-table'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Deal } from './queries'

const EMPTY = '—'
const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' })

export function buildDealColumns(customFields: FieldDefinition[]): ColumnDef<Deal, unknown>[] {
  const native: ColumnDef<Deal, unknown>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    {
      header: 'Valore previsto',
      id: 'valore_previsto',
      accessorFn: (row) => (row.valore_previsto ? euro.format(Number(row.valore_previsto)) : EMPTY),
    },
    { header: 'Probabilità', id: 'probabilita', accessorFn: (row) => `${row.probabilita}%` },
    {
      header: 'Chiusura prevista',
      id: 'data_chiusura_prevista',
      accessorFn: (row) =>
        row.data_chiusura_prevista
          ? new Intl.DateTimeFormat('it-IT').format(new Date(row.data_chiusura_prevista))
          : EMPTY,
    },
  ]

  const custom: ColumnDef<Deal, unknown>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
```

`apps/web/src/features/deals/DealForm.tsx` — same shape as `CustomerForm`, with a required customer
selector and these native fields:

```tsx
import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCustomers } from '@/features/customers/queries'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'nome', label: 'Nome', type: 'text', required: true, options: [] },
  { key: 'valore_previsto', label: 'Valore previsto', type: 'currency', required: false, options: [] },
  { key: 'probabilita', label: 'Probabilità (%)', type: 'number', required: false, options: [] },
  {
    key: 'data_chiusura_prevista',
    label: 'Chiusura prevista',
    type: 'date',
    required: false,
    options: [],
  },
  { key: 'ore_preventivate', label: 'Ore preventivate', type: 'number', required: false, options: [] },
  {
    key: 'valore_preventivato',
    label: 'Valore preventivato',
    type: 'currency',
    required: false,
    options: [],
  },
  { key: 'note', label: 'Note', type: 'textarea', required: false, options: [] },
]

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  customFields: FieldDefinition[]
  initial?: Record<string, unknown>
  problem?: ProblemDetail | null
  busy?: boolean
  onSubmit: (values: Record<string, unknown>) => void
  title: string
  lockCustomer?: boolean
}

export function DealForm({
  open,
  onOpenChange,
  customFields,
  initial,
  problem,
  busy,
  onSubmit,
  title,
  lockCustomer,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(initial ?? {})
  const customers = useCustomers({ limit: 200 })

  function submit() {
    const custom: Record<string, unknown> = {}
    const native: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
      if (value === '' || value === null) continue
      if (customFields.some((field) => field.key === key)) custom[key] = value
      else native[key] = value
    }
    onSubmit({ ...native, custom_fields: custom })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {!lockCustomer && (
          <div className="space-y-2">
            <Label htmlFor="deal-customer">
              Cliente<span className="ml-1 text-[var(--color-watermelon)]">*</span>
            </Label>
            <Select
              value={(values.customer_id as string) ?? ''}
              onValueChange={(value) => setValues((prev) => ({ ...prev, customer_id: value }))}
            >
              <SelectTrigger id="deal-customer">
                <SelectValue placeholder="Seleziona un cliente…" />
              </SelectTrigger>
              <SelectContent>
                {customers.data?.items.map((customer) => (
                  <SelectItem key={customer.id} value={customer.id}>
                    {customer.ragione_sociale}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <DynamicForm
          fields={[...NATIVE_FIELDS, ...customFields]}
          values={values}
          onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
          problem={problem}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? 'Salvataggio…' : 'Salva'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 6: Write the three routes**

`apps/web/src/routes/_app/deal.index.tsx` — the Kanban:

```tsx
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { List, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DealForm } from '@/features/deals/DealForm'
import { KanbanBoard } from '@/features/deals/KanbanBoard'
import { useCreateDeal, useDeals, useMoveDeal, useStages } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function DealsKanban() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('deal')
  const stages = useStages()
  const deals = useDeals({})
  const move = useMoveDeal()
  const create = useCreateDeal()

  if (stages.isLoading || deals.isLoading) return <Skeleton className="m-8 h-96" />

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Deal</h1>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link to="/app/deal/lista">
              <List className="mr-2 size-4" />
              Vista lista
            </Link>
          </Button>
          {canWrite && (
            <Button onClick={() => { setProblem(null); setOpen(true) }}>
              <Plus className="mr-2 size-4" />
              Nuovo deal
            </Button>
          )}
        </div>
      </header>

      <KanbanBoard
        stages={stages.data ?? []}
        deals={deals.data?.items ?? []}
        onOpen={(dealId) => void navigate({ to: '/app/deal/$dealId', params: { dealId } })}
        onMove={(dealId, stageId) =>
          move.mutate({ dealId, stageId }, { onError: (error) => toast.error(toProblem(error).detail) })
        }
      />

      <DealForm
        title="Nuovo deal"
        open={open}
        onOpenChange={setOpen}
        customFields={schema.data?.custom_fields ?? []}
        problem={problem}
        busy={create.isPending}
        onSubmit={(values) => {
          setProblem(null)
          create.mutate(values, {
            onSuccess: () => {
              setOpen(false)
              toast.success('Deal creato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/_app/deal/')({ component: DealsKanban })
```

`apps/web/src/routes/_app/deal.lista.tsx`:

```tsx
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { LayoutGrid, Search } from 'lucide-react'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { buildDealColumns } from '@/features/deals/columns'
import { useDeals } from '@/features/deals/queries'
import { useEntitySchema } from '@/lib/schema'

function DealsList() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const schema = useEntitySchema('deal')
  const deals = useDeals({ search: search || undefined })

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Deal — lista</h1>
        <Button variant="outline" asChild>
          <Link to="/app/deal">
            <LayoutGrid className="mr-2 size-4" />
            Vista Kanban
          </Link>
        </Button>
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per nome…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <DataTable
        columns={buildDealColumns(schema.data?.custom_fields ?? [])}
        data={deals.data?.items ?? []}
        isLoading={deals.isLoading}
        onRowClick={(row) => void navigate({ to: '/app/deal/$dealId', params: { dealId: row.id } })}
        emptyMessage="Nessun deal."
      />
    </div>
  )
}

export const Route = createFileRoute('/_app/deal/lista')({ component: DealsList })
```

`apps/web/src/routes/_app/deal.$dealId.tsx`:

```tsx
import { createFileRoute, useNavigate, useParams } from '@tanstack/react-router'
import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCustomer } from '@/features/customers/queries'
import { DealForm } from '@/features/deals/DealForm'
import { useDeal, useDeleteDeal, useStages, useUpdateDeal } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

const EMPTY = '—'
const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' })

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function DealDetail() {
  const { dealId } = useParams({ from: '/_app/deal/$dealId' })
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [editing, setEditing] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('deal')
  const { data: deal, isLoading } = useDeal(dealId)
  const stages = useStages()
  const update = useUpdateDeal(dealId)
  const remove = useDeleteDeal()
  const customer = useCustomer(deal?.customer_id ?? '')

  if (isLoading) return <Skeleton className="m-8 h-96" />
  if (!deal) return <p className="p-8">Deal non trovato.</p>

  const custom = schema.data?.custom_fields ?? []
  const stage = stages.data?.find((item) => item.id === deal.pipeline_stage_id)

  return (
    <>
      <EntityDetailLayout
        title={deal.nome}
        subtitle={customer.data?.ragione_sociale ?? 'Deal'}
        entityType="deal"
        entityId={dealId}
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => { setProblem(null); setEditing(true) }}>
                <Pencil className="mr-2 size-4" />
                Modifica
              </Button>
              <Button
                variant="destructive"
                onClick={() =>
                  remove.mutate(dealId, {
                    onSuccess: () => {
                      toast.success('Deal archiviato')
                      void navigate({ to: '/app/deal' })
                    },
                    onError: (error) => toast.error(toProblem(error).detail),
                  })
                }
              >
                <Trash2 className="mr-2 size-4" />
                Archivia
              </Button>
            </>
          )
        }
        overview={
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="font-semibold">Stato</h2>
                  {stage && (
                    <Badge variant={stage.tipo === 'open' ? 'secondary' : 'default'}>
                      {stage.nome}
                    </Badge>
                  )}
                </div>
                <Row
                  label="Valore previsto"
                  value={deal.valore_previsto ? euro.format(Number(deal.valore_previsto)) : EMPTY}
                />
                <Row label="Probabilità" value={`${deal.probabilita}%`} />
                <Row
                  label="Chiusura prevista"
                  value={
                    deal.data_chiusura_prevista
                      ? new Intl.DateTimeFormat('it-IT').format(
                          new Date(deal.data_chiusura_prevista),
                        )
                      : EMPTY
                  }
                />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Preventivo</h2>
                <Row label="Ore preventivate" value={deal.ore_preventivate ?? EMPTY} />
                <Row
                  label="Valore preventivato"
                  value={
                    deal.valore_preventivato ? euro.format(Number(deal.valore_preventivato)) : EMPTY
                  }
                />
                <p className="mt-3 text-xs text-muted-foreground">
                  Il confronto preventivo/consuntivo arriva nello slice 4, insieme al time tracking.
                </p>
              </CardContent>
            </Card>

            {custom.length > 0 && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Campi personalizzati</h2>
                  {custom.map((field) => (
                    <Row
                      key={field.key}
                      label={field.label}
                      value={renderFieldValue(field, deal.custom_fields[field.key])}
                    />
                  ))}
                </CardContent>
              </Card>
            )}

            {deal.note && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Note</h2>
                  <p className="whitespace-pre-wrap text-sm">{deal.note}</p>
                </CardContent>
              </Card>
            )}
          </div>
        }
        links={
          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-3 font-semibold">Cliente</h2>
              <Row label="Ragione sociale" value={customer.data?.ragione_sociale ?? '…'} />
              <Row label="P.IVA" value={customer.data?.partita_iva ?? EMPTY} />
            </CardContent>
          </Card>
        }
      />

      <DealForm
        title="Modifica deal"
        open={editing}
        onOpenChange={setEditing}
        customFields={custom}
        initial={{ ...deal, ...deal.custom_fields }}
        problem={problem}
        busy={update.isPending}
        lockCustomer
        onSubmit={(values) => {
          setProblem(null)
          update.mutate(values, {
            onSuccess: () => {
              setEditing(false)
              toast.success('Deal aggiornato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </>
  )
}

export const Route = createFileRoute('/_app/deal/$dealId')({ component: DealDetail })
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm build`
Expected: PASS (26 passed), clean types, successful build.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(web): deals Kanban with optimistic drag, list view and detail"
```

---

### Task 9: Settings — fields, pipeline, users and tokens

**Files:**
- Create: `apps/web/src/features/settings/{FieldsPanel.tsx,PipelinePanel.tsx,UsersPanel.tsx,TokensPanel.tsx}`
- Create: `apps/web/src/routes/_app/impostazioni.{campi,pipeline,utenti,token}.tsx`
- Create: `apps/web/src/routes/_app/impostazioni.tsx` (tabbed layout)
- Test: `apps/web/src/features/settings/TokensPanel.test.tsx`

**Interfaces:**
- Consumes: `api`, `queryKeys`, `useIsAdmin`
- Produces: the four admin panels

- [ ] **Step 1: Write the failing test**

`apps/web/src/features/settings/TokensPanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TokensPanel } from './TokensPanel'

vi.mock('@/lib/api', () => ({
  api: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() },
  unwrap: vi.fn().mockResolvedValue([
    { id: 't1', nome: 'Claude', prefix: 'pgc_abc12345', last_used_at: null, revoked_at: null, created_at: '2026-08-06T10:00:00Z' },
  ]),
  toProblem: (error: unknown) => error,
}))

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TokensPanel />
    </QueryClientProvider>,
  )
}

describe('TokensPanel', () => {
  it('explains what the tokens are for', () => {
    renderPanel()
    expect(screen.getByText(/MCP/i)).toBeInTheDocument()
  })

  it('shows only the prefix of an existing token', async () => {
    renderPanel()
    expect(await screen.findByText('pgc_abc12345')).toBeInTheDocument()
  })

  it('offers a way to create a new token', () => {
    renderPanel()
    expect(screen.getByRole('button', { name: /nuovo token/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/web && pnpm vitest run src/features/settings`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `TokensPanel.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, toProblem, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

interface Token {
  id: string
  nome: string
  prefix: string
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export function TokensPanel() {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [nome, setNome] = useState('')
  const [issued, setIssued] = useState<string | null>(null)

  const tokens = useQuery({
    queryKey: queryKeys.tokens,
    queryFn: () => unwrap(api.GET('/tokens')) as Promise<Token[]>,
  })

  const create = useMutation({
    mutationFn: (body: { nome: string }) =>
      unwrap(api.POST('/tokens', { body })) as Promise<Token & { token: string }>,
    onSuccess: (data) => {
      // Shown exactly once: the server stores only a hash.
      setIssued(data.token)
      setCreating(false)
      setNome('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.tokens })
    },
    onError: (error) => toast.error(toProblem(error).detail),
  })

  const revoke = useMutation({
    mutationFn: (tokenId: string) =>
      unwrap(api.DELETE('/tokens/{token_id}', { params: { path: { token_id: tokenId } } })),
    onSuccess: () => {
      toast.success('Token revocato')
      void queryClient.invalidateQueries({ queryKey: queryKeys.tokens })
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Token di accesso</h2>
          <p className="text-sm text-muted-foreground">
            Servono a far usare PigroCRM a Claude tramite il server MCP. Imposta il token nella
            variabile d&apos;ambiente <code>PIGROCRM_TOKEN</code>.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="mr-2 size-4" />
          Nuovo token
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead>Prefisso</TableHead>
            <TableHead>Ultimo uso</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {tokens.data?.map((token) => (
            <TableRow key={token.id}>
              <TableCell>{token.nome}</TableCell>
              <TableCell><code>{token.prefix}</code></TableCell>
              <TableCell>
                {token.last_used_at
                  ? new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium' }).format(
                      new Date(token.last_used_at),
                    )
                  : 'mai'}
              </TableCell>
              <TableCell className="text-right">
                {!token.revoked_at && (
                  <Button variant="ghost" size="icon" onClick={() => revoke.mutate(token.id)}>
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo token</DialogTitle>
            <DialogDescription>Dai un nome riconoscibile, es. &quot;Claude sul portatile&quot;.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="token-nome">Nome</Label>
            <Input id="token-nome" value={nome} onChange={(event) => setNome(event.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreating(false)}>Annulla</Button>
            <Button onClick={() => create.mutate({ nome })} disabled={!nome || create.isPending}>
              Crea
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(issued)} onOpenChange={() => setIssued(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Token creato</DialogTitle>
            <DialogDescription>
              Copialo adesso: non sarà più visibile. Il server ne conserva solo l&apos;hash.
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2">
            <Input readOnly value={issued ?? ''} className="font-mono text-xs" />
            <Button
              variant="outline"
              size="icon"
              onClick={() => {
                void navigator.clipboard.writeText(issued ?? '')
                toast.success('Copiato')
              }}
            >
              <Copy className="size-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setIssued(null)}>Fatto</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 4: Write `FieldsPanel.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, toProblem, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'
import type { FieldType } from '@/lib/schema'

const ENTITIES = [
  { value: 'customer', label: 'Cliente' },
  { value: 'person', label: 'Persona' },
  { value: 'deal', label: 'Deal' },
] as const

const TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Testo' },
  { value: 'textarea', label: 'Testo lungo' },
  { value: 'number', label: 'Numero' },
  { value: 'currency', label: 'Valuta' },
  { value: 'date', label: 'Data' },
  { value: 'select', label: 'Selezione singola' },
  { value: 'multiselect', label: 'Selezione multipla' },
  { value: 'checkbox', label: 'Sì / No' },
  { value: 'url', label: 'URL' },
]

const NEEDS_OPTIONS = new Set<FieldType>(['select', 'multiselect'])

interface Definition {
  id: string
  entity_type: string
  key: string
  label: string
  field_type: FieldType
  options: string[]
  required: boolean
  position: number
  archived: boolean
}

export function FieldsPanel() {
  const queryClient = useQueryClient()
  const [entityType, setEntityType] = useState<string>('customer')
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [fieldType, setFieldType] = useState<FieldType>('text')
  const [optionsText, setOptionsText] = useState('')
  const [required, setRequired] = useState(false)

  const fields = useQuery({
    queryKey: queryKeys.fields(entityType),
    queryFn: () =>
      unwrap(
        api.GET('/field-definitions', { params: { query: { entity_type: entityType } } }),
      ) as Promise<Definition[]>,
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.fields(entityType) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.schema(entityType) })
  }

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/field-definitions', { body: body as never })),
    onSuccess: () => {
      toast.success('Campo creato')
      setOpen(false)
      setKey('')
      setLabel('')
      setOptionsText('')
      setRequired(false)
      invalidate()
    },
    onError: (error) => toast.error(toProblem(error).detail),
  })

  const archive = useMutation({
    mutationFn: (fieldId: string) =>
      unwrap(
        api.POST('/field-definitions/{field_id}/archive', {
          params: { path: { field_id: fieldId } },
        }),
      ),
    onSuccess: () => {
      toast.success('Campo archiviato')
      invalidate()
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-2">
          <Label htmlFor="entity">Entità</Label>
          <Select value={entityType} onValueChange={setEntityType}>
            <SelectTrigger id="entity" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENTITIES.map((entity) => (
                <SelectItem key={entity.value} value={entity.value}>
                  {entity.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 size-4" />
          Nuovo campo
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Etichetta</TableHead>
            <TableHead>Chiave</TableHead>
            <TableHead>Tipo</TableHead>
            <TableHead>Obbligatorio</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {fields.data?.map((field) => (
            <TableRow key={field.id}>
              <TableCell>{field.label}</TableCell>
              <TableCell><code>{field.key}</code></TableCell>
              <TableCell>{TYPES.find((t) => t.value === field.field_type)?.label}</TableCell>
              <TableCell>{field.required ? 'Sì' : 'No'}</TableCell>
              <TableCell className="text-right">
                <Button variant="ghost" size="icon" onClick={() => archive.mutate(field.id)}>
                  <Archive className="size-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo campo</DialogTitle>
            <DialogDescription>
              Il tipo non è modificabile dopo la creazione: per cambiarlo, archivia il campo e
              creane uno nuovo. I valori già inseriti restano leggibili.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="field-label">Etichetta</Label>
              <Input
                id="field-label"
                value={label}
                onChange={(event) => {
                  setLabel(event.target.value)
                  // The API slugifies anyway; pre-filling makes the result predictable.
                  if (!key) setKey(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_'))
                }}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="field-key">Chiave</Label>
              <Input id="field-key" value={key} onChange={(event) => setKey(event.target.value)} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="field-type">Tipo</Label>
              <Select value={fieldType} onValueChange={(value) => setFieldType(value as FieldType)}>
                <SelectTrigger id="field-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {NEEDS_OPTIONS.has(fieldType) && (
              <div className="space-y-2">
                <Label htmlFor="field-options">Opzioni (una per riga)</Label>
                <textarea
                  id="field-options"
                  rows={4}
                  className="w-full rounded-md border p-2 text-sm"
                  value={optionsText}
                  onChange={(event) => setOptionsText(event.target.value)}
                />
              </div>
            )}

            <div className="flex items-center gap-2">
              <Checkbox
                id="field-required"
                checked={required}
                onCheckedChange={(checked) => setRequired(checked === true)}
              />
              <Label htmlFor="field-required" className="font-normal">Obbligatorio</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>Annulla</Button>
            <Button
              disabled={!key || !label || create.isPending}
              onClick={() =>
                create.mutate({
                  entity_type: entityType,
                  key,
                  label,
                  field_type: fieldType,
                  options: NEEDS_OPTIONS.has(fieldType)
                    ? optionsText.split('\n').map((line) => line.trim()).filter(Boolean)
                    : [],
                  required,
                  position: fields.data?.length ?? 0,
                })
              }
            >
              Crea
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

Editing an existing definition is deliberately not offered for `field_type`: the API rejects it with
`409 immutable_field`, so exposing the control would only produce an error the user cannot act on.

- [ ] **Step 5: Write `PipelinePanel.tsx` and `UsersPanel.tsx`**

`apps/web/src/features/settings/PipelinePanel.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Stage } from '@/features/deals/queries'
import { api, toProblem, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

const TYPES = [
  { value: 'open', label: 'Aperto' },
  { value: 'won', label: 'Vinto' },
  { value: 'lost', label: 'Perso' },
] as const

export function PipelinePanel() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [nome, setNome] = useState('')
  const [probabilita, setProbabilita] = useState('0')
  const [tipo, setTipo] = useState<'open' | 'won' | 'lost'>('open')

  const stages = useQuery({
    queryKey: queryKeys.stages,
    queryFn: () => unwrap(api.GET('/pipeline-stages')) as Promise<Stage[]>,
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.stages })
  }

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/pipeline-stages', { body: body as never })),
    onSuccess: () => {
      toast.success('Stato creato')
      setOpen(false)
      setNome('')
      invalidate()
    },
    onError: (error) => toast.error(toProblem(error).detail),
  })

  const seed = useMutation({
    mutationFn: () => unwrap(api.POST('/pipeline-stages/seed')),
    onSuccess: () => {
      toast.success('Stati predefiniti ripristinati')
      invalidate()
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Stati della pipeline</h2>
          <p className="text-sm text-muted-foreground">
            Il tipo dice al sistema cosa significa uno stato: le dashboard riconoscono
            &quot;vinto&quot; dal tipo, non dal nome, così puoi rinominarlo liberamente.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => seed.mutate()}>
            <RotateCcw className="mr-2 size-4" />
            Ripristina predefiniti
          </Button>
          <Button onClick={() => setOpen(true)}>
            <Plus className="mr-2 size-4" />
            Nuovo stato
          </Button>
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Posizione</TableHead>
            <TableHead>Nome</TableHead>
            <TableHead>Probabilità</TableHead>
            <TableHead>Tipo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stages.data?.map((stage) => (
            <TableRow key={stage.id}>
              <TableCell>{stage.posizione}</TableCell>
              <TableCell>{stage.nome}</TableCell>
              <TableCell>{stage.probabilita_default}%</TableCell>
              <TableCell>
                <Badge variant={stage.tipo === 'open' ? 'secondary' : 'default'}>
                  {TYPES.find((type) => type.value === stage.tipo)?.label}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo stato</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="stage-nome">Nome</Label>
              <Input id="stage-nome" value={nome} onChange={(event) => setNome(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="stage-prob">Probabilità predefinita (%)</Label>
              <Input
                id="stage-prob"
                type="number"
                min={0}
                max={100}
                value={probabilita}
                onChange={(event) => setProbabilita(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="stage-tipo">Tipo</Label>
              <Select value={tipo} onValueChange={(value) => setTipo(value as typeof tipo)}>
                <SelectTrigger id="stage-tipo">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>Annulla</Button>
            <Button
              disabled={!nome || create.isPending}
              onClick={() =>
                create.mutate({
                  nome,
                  posizione: stages.data?.length ?? 0,
                  probabilita_default: Number(probabilita),
                  tipo,
                })
              }
            >
              Crea
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

`apps/web/src/features/settings/UsersPanel.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, toProblem, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'
import type { SessionUser } from '@/lib/auth'

const ROLES = [
  { value: 'admin', label: 'Amministratore' },
  { value: 'collaboratore', label: 'Collaboratore' },
  { value: 'readonly', label: 'Sola lettura' },
] as const

export function UsersPanel() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [nome, setNome] = useState('')
  const [password, setPassword] = useState('')
  const [ruolo, setRuolo] = useState<SessionUser['ruolo']>('collaboratore')

  const users = useQuery({
    queryKey: queryKeys.users,
    queryFn: () => unwrap(api.GET('/users')) as Promise<SessionUser[]>,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/users', { body: body as never })),
    onSuccess: () => {
      toast.success('Utente creato')
      setOpen(false)
      setEmail('')
      setNome('')
      setPassword('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.users })
    },
    onError: (error) => toast.error(toProblem(error).detail),
  })

  const toggleActive = useMutation({
    mutationFn: ({ id, attivo }: { id: string; attivo: boolean }) =>
      unwrap(
        api.PATCH('/users/{user_id}', {
          params: { path: { user_id: id } },
          body: { attivo } as never,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.users }),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Utenti</h2>
          <p className="text-sm text-muted-foreground">
            Non esiste registrazione pubblica: gli utenti li crei tu. Il cambio password non è
            disponibile in questa versione — disattiva e ricrea l&apos;utente se serve.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 size-4" />
          Nuovo utente
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Ruolo</TableHead>
            <TableHead>Stato</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.data?.map((user) => (
            <TableRow key={user.id}>
              <TableCell>{user.nome}</TableCell>
              <TableCell>{user.email}</TableCell>
              <TableCell>{ROLES.find((role) => role.value === user.ruolo)?.label}</TableCell>
              <TableCell>
                <Badge variant={user.attivo ? 'default' : 'secondary'}>
                  {user.attivo ? 'Attivo' : 'Disattivato'}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggleActive.mutate({ id: user.id, attivo: !user.attivo })}
                >
                  {user.attivo ? 'Disattiva' : 'Riattiva'}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo utente</DialogTitle>
            <DialogDescription>
              La password deve avere almeno 10 caratteri. Comunicala tu all&apos;utente: il sistema
              non invia email in questa versione.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="user-nome">Nome</Label>
              <Input id="user-nome" value={nome} onChange={(event) => setNome(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-email">Email</Label>
              <Input
                id="user-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-password">Password</Label>
              <Input
                id="user-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-ruolo">Ruolo</Label>
              <Select value={ruolo} onValueChange={(value) => setRuolo(value as typeof ruolo)}>
                <SelectTrigger id="user-ruolo">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((role) => (
                    <SelectItem key={role.value} value={role.value}>
                      {role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>Annulla</Button>
            <Button
              disabled={!email || !nome || password.length < 10 || create.isPending}
              onClick={() => create.mutate({ email, nome, password, ruolo })}
            >
              Crea
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 6: Write the tabbed settings layout**

`apps/web/src/routes/_app/impostazioni.tsx`:

```tsx
import { Link, Outlet, createFileRoute, useNavigate, useRouterState } from '@tanstack/react-router'
import { useEffect } from 'react'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIsAdmin } from '@/lib/auth'

const TABS = [
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'utenti', label: 'Utenti' },
  { value: 'token', label: 'Token' },
] as const

function SettingsLayout() {
  const isAdmin = useIsAdmin()
  const navigate = useNavigate()
  const { location } = useRouterState()

  useEffect(() => {
    if (!isAdmin) void navigate({ to: '/app' })
  }, [isAdmin, navigate])

  const active = TABS.find((tab) => location.pathname.endsWith(tab.value))?.value ?? 'campi'

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Impostazioni</h1>
      <Tabs value={active}>
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} asChild>
              <Link to={`/app/impostazioni/${tab.value}`}>{tab.label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="mt-6">
        <Outlet />
      </div>
    </div>
  )
}

export const Route = createFileRoute('/_app/impostazioni')({ component: SettingsLayout })
```

Then four thin routes, each rendering its panel — for example
`apps/web/src/routes/_app/impostazioni.token.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { TokensPanel } from '@/features/settings/TokensPanel'

export const Route = createFileRoute('/_app/impostazioni/token')({ component: TokensPanel })
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm build`
Expected: PASS (29 passed), clean types, successful build.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(web): admin settings for custom fields, pipeline, users and MCP tokens"
```

---

# Phase 4 — Verification and deployment

### Task 10: End-to-end tests

**Files:**
- Create: `apps/web/playwright.config.ts`, `apps/web/e2e/{auth.spec.ts,crm.spec.ts}`
- Create: `scripts/e2e-setup.sh`

**Interfaces:**
- Consumes: the full stack (API from 1A, web from this plan)
- Produces: Playwright covering the critical paths from spec §11

- [ ] **Step 1: Install Playwright and write the config**

```bash
cd apps/web && pnpm add -D @playwright/test@1.62.1 && pnpm exec playwright install chromium && cd ../..
```

`apps/web/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // one database, shared state
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: 'http://localhost:5173', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
```

- [ ] **Step 2: Write the setup script**

`scripts/e2e-setup.sh`:

```bash
#!/usr/bin/env bash
# Brings up a disposable database, migrates it, and seeds the admin the E2E specs log in as.
set -euo pipefail

export PIGROCRM_DATABASE_URL="postgresql+psycopg://pigrocrm:pigrocrm@localhost:55433/pigrocrm_e2e"
export PIGROCRM_JWT_SECRET="e2e-secret-not-for-production"

docker rm -f pigrocrm-e2e >/dev/null 2>&1 || true
docker run --rm -d --name pigrocrm-e2e \
  -e POSTGRES_PASSWORD=pigrocrm -e POSTGRES_USER=pigrocrm -e POSTGRES_DB=pigrocrm_e2e \
  -p 55433:5432 postgres:17-alpine

until docker exec pigrocrm-e2e pg_isready -U pigrocrm >/dev/null 2>&1; do sleep 1; done

(cd packages/core && uv run alembic upgrade head)

uv run python - <<'PY'
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.pipeline.service import PipelineService

engine = create_engine_from_settings(get_settings())
with session_factory(engine)() as session:
    UserService(session).create(
        UserCreate(email="e2e@pigro.it", password="supersegreta1", nome="E2E", ruolo="admin"),
        Actor.system(),
    )
    PipelineService(session).seed_defaults()
print("seed completato")
PY

uv run uvicorn pigrocrm_api.main:app --port 8000 &
echo $! > /tmp/pigrocrm-e2e-api.pid
sleep 3
echo "stack pronto su :8000"
```

Make it executable: `chmod +x scripts/e2e-setup.sh`

- [ ] **Step 3: Write the auth spec**

`apps/web/e2e/auth.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

const EMAIL = 'e2e@pigro.it'
const PASSWORD = 'supersegreta1'

test('an unauthenticated visitor is sent to the login page', async ({ page }) => {
  await page.goto('/app/clienti')
  await expect(page).toHaveURL(/\/login/)
})

test('a wrong password is rejected without saying which field was wrong', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill('sbagliata')
  await page.getByRole('button', { name: 'Accedi' }).click()

  await expect(page.getByText(/credenziali non valide/i)).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('a correct login reaches the dashboard and logout returns to login', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Accedi' }).click()

  await expect(page).toHaveURL(/\/app/)
  await expect(page.getByText('Ciao E2E')).toBeVisible()

  await page.getByRole('button', { name: 'Esci' }).click()
  await expect(page).toHaveURL(/\/login/)
})
```

- [ ] **Step 4: Write the CRM spec**

`apps/web/e2e/crm.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill('e2e@pigro.it')
  await page.getByLabel('Password').fill('supersegreta1')
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page).toHaveURL(/\/app/)
})

test('a custom field defined in settings appears in the customer form', async ({ page }) => {
  // Spec success criterion 1, end to end: define a field, then use it, with no deploy.
  await page.goto('/app/impostazioni/campi')
  await page.getByRole('button', { name: /nuovo campo/i }).click()
  await page.getByLabel('Chiave').fill('settore')
  await page.getByLabel('Etichetta').fill('Settore')
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText('Settore')).toBeVisible()

  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await expect(page.getByLabel('Settore')).toBeVisible()
})

test('creating a customer, a person and a deal, then moving it across the board', async ({ page }) => {
  const name = `ACME ${Date.now()}`

  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await page.getByLabel('Ragione sociale').fill(name)
  await page.getByLabel('P.IVA').fill('12345678901')
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText(name)).toBeVisible()

  await page.goto('/app/persone')
  await page.getByRole('button', { name: /nuova persona/i }).click()
  await page.getByLabel('Nome').fill('Mario')
  await page.getByLabel('Cognome').fill('Rossi')
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText('Rossi')).toBeVisible()

  await page.goto('/app/deal')
  await page.getByRole('button', { name: /nuovo deal/i }).click()
  await page.getByLabel(/^Cliente/).click()
  await page.getByRole('option', { name }).click()
  await page.getByLabel('Nome').fill('Progetto E2E')
  await page.getByRole('button', { name: 'Salva' }).click()

  const card = page.getByText('Progetto E2E')
  await expect(card).toBeVisible()

  // Drag from Lead to Offerta and confirm the move survives a reload.
  const target = page.locator('div').filter({ hasText: /^Offerta/ }).first()
  await card.hover()
  await page.mouse.down()
  await target.hover()
  await page.mouse.up()

  await page.reload()
  await expect(page.getByText('Progetto E2E')).toBeVisible()
})

test('an invalid VAT number surfaces the API message on the field', async ({ page }) => {
  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await page.getByLabel('Ragione sociale').fill('Test IVA')
  await page.getByLabel('P.IVA').fill('123')
  await page.getByRole('button', { name: 'Salva' }).click()

  // The message comes from the API's problem document, not from a client-side rule.
  await expect(page.getByText(/11 cifre/)).toBeVisible()
})

test('the timeline records what happened', async ({ page }) => {
  const name = `Timeline ${Date.now()}`
  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await page.getByLabel('Ragione sociale').fill(name)
  await page.getByRole('button', { name: 'Salva' }).click()

  await page.getByText(name).click()
  await page.getByRole('tab', { name: 'Timeline' }).click()
  await expect(page.getByText('Creato')).toBeVisible()
})
```

- [ ] **Step 5: Run the E2E suite**

```bash
./scripts/e2e-setup.sh
cd apps/web && pnpm exec playwright test
kill "$(cat /tmp/pigrocrm-e2e-api.pid)" && docker rm -f pigrocrm-e2e
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test(e2e): Playwright coverage for login, CRM lifecycle and the Kanban move"
```

---

### Task 11: Docker Compose and the deployment pipeline

**Files:**
- Create: `Dockerfile.api`, `Dockerfile.web`, `docker-compose.yml`, `deploy/nginx/pigrocrm.conf`, `deploy/setup-server.sh`, `.env.example`
- Create: `.github/workflows/ci-deploy.yml`

**Interfaces:**
- Consumes: everything above
- Produces: `docker compose up` runs the full stack; pushing to `main` runs the gates and deploys

- [ ] **Step 1: Write `Dockerfile.api`**

```dockerfile
FROM python:3.13-slim-bookworm

# Pandoc and Typst are not needed until slice 2; do not install them here.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/mcp/pyproject.toml apps/mcp/
RUN uv sync --frozen --no-dev --no-install-project

COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/mcp ./apps/mcp
RUN uv sync --frozen --no-dev

EXPOSE 8000
# Migrations run at start-up: one instance, so there is no concurrent-migration risk.
CMD ["sh", "-c", "cd packages/core && uv run alembic upgrade head && cd /app && uv run uvicorn pigrocrm_api.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 2: Write `Dockerfile.web`**

```dockerfile
FROM node:22-bookworm-slim AS build

RUN corepack enable && corepack prepare pnpm@10.12.4 --activate
WORKDIR /app

COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web ./
RUN pnpm build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`deploy/nginx/spa.conf`:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # Client-side routing: unknown paths are routes, not missing files.
    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://api:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 3: Write `docker-compose.yml` and `.env.example`**

```yaml
services:
  db:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-pigrocrm}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?serve una password}
      POSTGRES_DB: ${POSTGRES_DB:-pigrocrm}
    volumes:
      - pigrocrm-db:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U ${POSTGRES_USER:-pigrocrm}']
      interval: 5s
      retries: 10

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      PIGROCRM_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-pigrocrm}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-pigrocrm}
      PIGROCRM_JWT_SECRET: ${PIGROCRM_JWT_SECRET:?serve un secret}

  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    restart: unless-stopped
    depends_on: [api]
    ports:
      - '127.0.0.1:8080:80'

volumes:
  pigrocrm-db:
```

`.env.example`:

```bash
# Never commit the real .env.
POSTGRES_USER=pigrocrm
POSTGRES_PASSWORD=
POSTGRES_DB=pigrocrm
# Generate with: openssl rand -hex 32
PIGROCRM_JWT_SECRET=
```

- [ ] **Step 4: Write the CI/CD workflow**

`.github/workflows/ci-deploy.yml`:

```yaml
name: CI & Deploy (PigroCRM)

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          version: '0.9.24'
          enable-cache: true
      - run: uv sync --frozen
      - name: Lint
        run: uv run ruff check . && uv run ruff format --check .
      - name: Type check
        run: uv run mypy packages/core/src apps/api/src apps/mcp/src
      - name: Test
        # testcontainers starts PostgreSQL itself; no service container needed.
        run: uv run pytest -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 10.12.4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: apps/web/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm eslint .
      - run: pnpm tsc --noEmit
      - run: pnpm vitest run
      - run: pnpm build

  deploy:
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    steps:
      - uses: actions/checkout@v4

      - name: Configure SSH
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.PIGROCRM_SSH_PRIVATE_KEY }}" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
          ssh-keyscan -H "${{ secrets.PIGROCRM_HOST }}" >> ~/.ssh/known_hosts

      - name: Sync sources
        env:
          DEPLOY_HOST: ${{ secrets.PIGROCRM_HOST }}
          DEPLOY_USER: ${{ secrets.PIGROCRM_USER }}
          DEPLOY_PATH: ${{ secrets.PIGROCRM_DEPLOY_PATH }}
        run: |
          ssh "${DEPLOY_USER}@${DEPLOY_HOST}" "mkdir -p \"${DEPLOY_PATH}\""
          rsync -az --delete \
            --exclude '.git' --exclude '.github' \
            --exclude '.env' --exclude 'the reference copy' \
            --exclude 'node_modules' --exclude 'dist' --exclude '.venv' \
            ./ "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}"

      - name: Deploy
        env:
          DEPLOY_HOST: ${{ secrets.PIGROCRM_HOST }}
          DEPLOY_USER: ${{ secrets.PIGROCRM_USER }}
          DEPLOY_PATH: ${{ secrets.PIGROCRM_DEPLOY_PATH }}
        run: |
          ssh "${DEPLOY_USER}@${DEPLOY_HOST}" "DEPLOY_PATH='${DEPLOY_PATH}' bash -s" <<'SSH'
            set -e
            cd "${DEPLOY_PATH}"
            if docker compose version >/dev/null 2>&1; then
              COMPOSE="docker compose"
            elif command -v docker-compose >/dev/null 2>&1; then
              COMPOSE="docker-compose"
            else
              echo "Docker Compose non trovato" >&2
              exit 1
            fi
            $COMPOSE up -d --build
          SSH

      - name: Configure nginx
        env:
          DEPLOY_HOST: ${{ secrets.PIGROCRM_HOST }}
          DEPLOY_USER: ${{ secrets.PIGROCRM_USER }}
          DEPLOY_PATH: ${{ secrets.PIGROCRM_DEPLOY_PATH }}
        run: ssh "${DEPLOY_USER}@${DEPLOY_HOST}" "bash \"${DEPLOY_PATH}/deploy/setup-server.sh\""
```

Required GitHub secrets: `PIGROCRM_HOST`, `PIGROCRM_USER`, `PIGROCRM_DEPLOY_PATH`,
`PIGROCRM_SSH_PRIVATE_KEY`. The server must already hold its own `.env` — the pipeline never copies
one, which is what the `--exclude '.env'` above guarantees.

- [ ] **Step 5: Write the server-side nginx script**

`deploy/setup-server.sh`:

```bash
#!/usr/bin/env bash
# Idempotent: safe to run on every deploy.
set -euo pipefail

DOMAIN="${PIGROCRM_DOMAIN:-pigrocrm.humancraft.tech}"
CONF="/etc/nginx/sites-available/${DOMAIN}"

cat > "$CONF" <<CONFEOF
server {
    listen 80;
    server_name ${DOMAIN};
    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
CONFEOF

ln -sf "$CONF" "/etc/nginx/sites-enabled/${DOMAIN}"
nginx -t
systemctl reload nginx
echo "nginx configurato per ${DOMAIN}"
```

`chmod +x deploy/setup-server.sh`

Note on HTTPS: cookies are issued with `Secure`, so **the browser will not store them over plain
HTTP**. Run `certbot --nginx -d "$DOMAIN"` once on the server before first real use, or login will
appear to succeed and then immediately fail.

- [ ] **Step 6: Verify the stack locally**

```bash
cp .env.example .env
# fill POSTGRES_PASSWORD and PIGROCRM_JWT_SECRET (openssl rand -hex 32)
docker compose up --build -d
sleep 10
curl -fsS http://localhost:8080/api/health
docker compose exec api uv run pigrocrm createadmin --email admin@pigro.it --nome Admin
```

Expected: `{"status":"ok"}`, then the admin is created. Open `http://localhost:8080` and log in.

- [ ] **Step 7: Tear down and commit**

```bash
docker compose down
git add -A
git commit -m "feat: Docker Compose stack, nginx config and CI/CD pipeline with test gates"
```

---

## Definition of done for slice 1

- [ ] `uv run pytest` green; `pnpm vitest run` green; `pnpm exec playwright test` green
- [ ] `ruff`, `mypy`, `eslint` and `tsc --noEmit` all clean
- [ ] **Criterion 1** — a user logs in, defines a custom field from the UI, creates a customer using it, attaches a person and a deal, and drags the deal across the Kanban
- [ ] **Criterion 2** — Claude performs the same operations over MCP, discovering the custom field via `describe_schema` (proved in plan 1A)
- [ ] **Criterion 3** — the timeline shows both sequences and distinguishes `user` from `mcp`
- [ ] **Criterion 4** — `test_core_never_imports_from_adapters` passes
- [ ] **Criterion 5** — CI runs the suite against real PostgreSQL and the deploy succeeds

Next: slice 2 — documents and templates (`{{}}` engine with loops and conditionals, Pandoc + Typst
PDF rendering, pluggable storage with local and Google Drive backends, and the Attio importer).
