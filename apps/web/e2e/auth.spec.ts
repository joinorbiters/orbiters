import { expect, test } from '@playwright/test'

// Seeded by apps/web/scripts/e2e-setup.sh -- an admin, deliberately, so later specs
// in this same run (e2e/crm.spec.ts, e2e/custom-fields.spec.ts, e2e/kanban.spec.ts)
// can reach Settings through it too.
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
