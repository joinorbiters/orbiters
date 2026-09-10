import { useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import './site-controls.css'

/**
 * One question per screen, the shape Typeform and Tally made familiar: a progress bar,
 * the question large, one control, Enter to go on, Back always there, a review at the
 * end. The engine knows nothing about what is asked -- a step is a render function,
 * a validator and a name for the review -- so the two wizards share every keystroke
 * and differ only in their steps.
 */
export interface Step<T> {
  id: string
  /** The question, as a sentence to the person. */
  title: string
  hint?: string
  /** `true` for a step whose empty answer is fine; the review says «—» for it. */
  optional?: boolean
  render: (props: StepRenderProps<T>) => ReactNode
  /** A sentence when the answer cannot go on, `null` when it can. Runs on «Avanti» and
   *  on Enter, never on every keystroke: nobody wants to be told they are wrong while
   *  they are still typing. */
  validate: (value: T) => string | null
  /** What the review shows for this step. */
  summary: (value: T) => string
}

export interface StepRenderProps<T> {
  value: T
  set: (patch: Partial<T>) => void
  /** Hands the step's own submit (a multi-line control, a file picker) to the engine. */
  next: () => void
  error: string | null
  autoFocus: boolean
}

export function Wizard<T>({
  title,
  steps,
  value,
  set,
  onSubmit,
  submitting,
  submitError,
  submitLabel,
}: {
  title: string
  steps: Step<T>[]
  value: T
  set: (patch: Partial<T>) => void
  onSubmit: () => void
  submitting: boolean
  /** An error from the server, shown on the review screen; when it names a step by id
   *  the engine jumps back to that step and shows it there. */
  submitError: { message: string; step?: string } | null
  submitLabel: string
}) {
  const [index, setIndex] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const review = index === steps.length
  const step = steps[index]
  const [handled, setHandled] = useState<string | null>(null)

  // A server error that names a step sends the person back to it, once per error. State
  // adjusted during render, the way React asks for "state that follows a prop", rather
  // than in an effect that would paint the review first and jump a frame later.
  if (submitError?.step && handled !== submitError.message) {
    const at = steps.findIndex((candidate) => candidate.id === submitError.step)
    if (at >= 0) {
      setHandled(submitError.message)
      setIndex(at)
      setError(submitError.message)
    }
  }

  function next() {
    if (!step) return
    const problem = step.validate(value)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setIndex((current) => current + 1)
  }

  function back() {
    setError(null)
    setIndex((current) => Math.max(0, current - 1))
  }

  const progress = Math.round((Math.min(index, steps.length) / steps.length) * 100)

  return (
    <div
      className="mx-auto flex w-full max-w-2xl flex-col gap-8"
      onKeyDown={(event) => {
        // Enter goes on, except inside a textarea (where it is a newline) or on a
        // button (where it is a click). Shift+Enter always means a newline.
        if (event.key !== 'Enter' || event.shiftKey || review) return
        const target = event.target as HTMLElement
        if (target.tagName === 'TEXTAREA' || target.tagName === 'BUTTON') return
        event.preventDefault()
        next()
      }}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{title}</span>
          <span aria-live="polite">
            {review ? 'Riepilogo' : `${index + 1} di ${steps.length}`}
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Avanzamento"
          className="h-2 w-full overflow-hidden border-(length:--landing-border-width)"
        >
          <div
            className="h-full bg-(--landing-ink) transition-[width] duration-300"
            style={{ width: `${review ? 100 : progress}%` }}
          />
        </div>
      </div>

      {review ? (
        <section className="space-y-6" aria-label="Riepilogo">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Tutto giusto?</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Rileggi le risposte: puoi tornare indietro su qualsiasi punto.
            </p>
          </div>
          <dl className="divide-y rounded-2xl border bg-card">
            {steps.map((candidate, at) => (
              <div key={candidate.id} className="flex items-start gap-4 px-4 py-3 text-sm">
                <dt className="w-40 shrink-0 text-muted-foreground">{candidate.title}</dt>
                <dd className="min-w-0 flex-1 break-words font-medium">
                  {candidate.summary(value) || '—'}
                </dd>
                <button
                  type="button"
                  className="shrink-0 text-xs text-muted-foreground underline-offset-2 hover:underline"
                  onClick={() => {
                    setError(null)
                    setIndex(at)
                  }}
                >
                  Modifica
                </button>
              </div>
            ))}
          </dl>
          {submitError && !submitError.step && (
            <p role="alert" className="text-sm text-destructive">
              {submitError.message}
            </p>
          )}
          <div className="flex items-center justify-between">
            <Button type="button" variant="outline" onClick={back} disabled={submitting}>
              Indietro
            </Button>
            <Button type="button" onClick={onSubmit} disabled={submitting}>
              {submitting ? 'Invio…' : submitLabel}
            </Button>
          </div>
        </section>
      ) : step ? (
        <section key={step.id} className="space-y-6" aria-labelledby={`step-${step.id}`}>
          <div>
            <h2 id={`step-${step.id}`} className="text-2xl font-semibold tracking-tight">
              {step.title}
              {step.optional && (
                <span className="ml-2 text-base font-normal text-muted-foreground">
                  (facoltativo)
                </span>
              )}
            </h2>
            {step.hint && <p className="mt-1 text-sm text-muted-foreground">{step.hint}</p>}
          </div>
          <div>{step.render({ value, set, next, error, autoFocus: true })}</div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              onClick={back}
              className={cn(index === 0 && 'invisible')}
            >
              Indietro
            </Button>
            <div className="flex items-center gap-3">
              <span className="hidden text-xs text-muted-foreground sm:inline">
                Invio ↵ per continuare
              </span>
              <Button type="button" onClick={next}>
                {index === steps.length - 1 ? 'Rivedi' : 'Avanti'}
              </Button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
