import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: () => <div className="p-8 text-2xl font-semibold">PigroCRM</div>,
})
