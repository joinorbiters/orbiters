import { DynamicFieldRenderer } from './DynamicFieldRenderer'
import { fieldErrorFrom, type ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'
import { cn } from '@/lib/utils'

interface Props {
  fields: FieldDefinition[]
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  problem?: ProblemDetail | null
}

/** Errors come from the API's problem document, never from a client-side rule.
 *  Duplicating validation here is how the web app and the MCP server start
 *  disagreeing about what is valid. `fieldErrorFrom` is the one place that decides
 *  which field a problem document is about; this component only asks it and
 *  attaches the answer to the matching control — at most one field is ever
 *  highlighted, because a single request can only fail on one field at a time. */
export function DynamicForm({ fields, values, onChange, problem }: Props) {
  const fieldError = problem ? fieldErrorFrom(problem) : null

  return (
    <div className="grid gap-5 sm:grid-cols-2">
      {fields.map((field) => (
        <div
          key={field.key}
          className={cn((field.type === 'textarea' || field.type === 'multiselect') && 'sm:col-span-2')}
        >
          <DynamicFieldRenderer
            field={field}
            value={values[field.key] ?? null}
            onChange={(value) => onChange(field.key, value)}
            error={fieldError?.field === field.key ? fieldError.message : undefined}
          />
        </div>
      ))}
    </div>
  )
}
