/**
 * The two panels a new space sees above its dashboard (spec 2026-09-12 §6.7): the
 * assistant first, because it is what the landing sells and what a space is for, then
 * the four first steps. Both read their state from the data (`useFirstSteps`) and
 * disappear on their own: the card when a token exists, the list at four of four or on
 * «Nascondi», which is the one preference kept, and kept in the browser.
 */
import { Link } from '@tanstack/react-router'
import { Bot, Check, ChevronRight, Circle } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CONNECT_ASSISTANT_TO, hide, isHidden, useFirstSteps } from './newSpace'

export function NewSpacePanels() {
  const state = useFirstSteps()
  const [hidden, setHidden] = useState(isHidden)
  if (state.loading) return null
  const showAssistant = !state.assistantConnected
  const showSteps = !state.allDone && !hidden
  if (!showAssistant && !showSteps) return null
  return (
    <div className="mb-6 space-y-4" data-testid="new-space-panels">
      {showAssistant && <AssistantCard />}
      {showSteps && (
        <FirstStepsList
          steps={state.steps}
          doneCount={state.doneCount}
          onHide={() => {
            hide()
            setHidden(true)
          }}
        />
      )}
    </div>
  )
}

function AssistantCard() {
  return (
    <Card className="border-foreground border-2">
      <CardHeader className="flex flex-row items-start gap-4">
        <Bot className="mt-1 size-8 shrink-0 text-[var(--color-watermelon)]" aria-hidden />
        <div className="space-y-1.5">
          <CardTitle className="text-xl">Il CRM che lavora al posto tuo</CardTitle>
          <CardDescription className="text-base">
            Collega Claude al tuo spazio e chiedigli di registrare le ore, preparare
            un&apos;offerta, riassumere la settimana. Tutto quello che fai qui lo può fare lui.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <Button asChild size="lg">
          <Link to={CONNECT_ASSISTANT_TO}>
            Collega l&apos;assistente
            <ChevronRight className="ml-1 size-4" aria-hidden />
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}

function FirstStepsList({
  steps,
  doneCount,
  onHide,
}: {
  steps: ReturnType<typeof useFirstSteps>['steps']
  doneCount: number
  onHide: () => void
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Primi passi</CardTitle>
          <CardDescription>
            {doneCount} di {steps.length}. Nell&apos;ordine in cui il CRM li chiede.
          </CardDescription>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onHide}>
          Nascondi
        </Button>
      </CardHeader>
      <CardContent>
        <ol className="divide-y">
          {steps.map((step) => (
            <li key={step.id} className="flex items-start gap-3 py-3">
              {step.done ? (
                <Check className="mt-0.5 size-5 shrink-0 text-emerald-600" aria-label="fatto" />
              ) : (
                <Circle className="text-muted-foreground mt-0.5 size-5 shrink-0" aria-label="da fare" />
              )}
              <div className="min-w-0 flex-1">
                {step.done ? (
                  <p className="text-muted-foreground line-through">{step.title}</p>
                ) : (
                  <Link to={step.to} className="font-medium underline-offset-4 hover:underline">
                    {step.title}
                  </Link>
                )}
                {!step.done && <p className="text-muted-foreground text-sm">{step.hint}</p>}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
