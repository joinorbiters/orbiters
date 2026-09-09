import { Link, useSearch } from '@tanstack/react-router'
import { Check } from 'lucide-react'

export function Thanks() {
  const { chi } = useSearch({ from: '/public/grazie' })
  const azienda = chi === 'azienda'
  return (
    <div className="mx-auto max-w-xl space-y-6 text-center">
      <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-foreground text-background">
        <Check className="size-6" aria-hidden="true" />
      </span>
      <h1 className="text-3xl font-semibold tracking-tight">
        {azienda ? 'Grazie, ci siamo.' : 'Grazie, sei dentro.'}
      </h1>
      <p className="text-muted-foreground">
        {azienda
          ? 'Abbiamo la tua richiesta. Ti scriviamo noi entro qualche giorno con le persone che possono fare al caso tuo.'
          : 'Abbiamo il tuo profilo e il tuo CV. Ti scriviamo noi: appena c’è un progetto che ti somiglia, o anche solo per conoscerci.'}
      </p>
      <p className="text-sm text-muted-foreground">
        Nel frattempo, se lavori in proprio,{' '}
        <a
          className="underline underline-offset-2"
          href="https://pigro.joinorbiters.com/app/registrati"
        >
          PigroCRM è tuo, gratis
        </a>
        .
      </p>
      <Link to="/" className="text-sm underline underline-offset-2">
        Torna all’inizio
      </Link>
    </div>
  )
}
