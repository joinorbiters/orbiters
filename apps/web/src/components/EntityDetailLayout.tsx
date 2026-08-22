import type { ReactNode } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { TimelineEntityType } from '@/lib/schema'
import { Timeline } from './Timeline'

interface EntityDetailLayoutProps {
  title: string
  subtitle?: string
  actions?: ReactNode
  overview: ReactNode
  links?: ReactNode
  /**
   * The Documenti tab's contents. Optional because Person has no documents: a
   * document belongs to a customer or to a deal, never to a contact. When absent the
   * tab is not rendered at all rather than rendered empty -- an empty tab invites the
   * user to look for something that does not exist for this entity.
   */
  documents?: ReactNode
  /** Optional, like `documents`: only customers and deals have invoices, and a person
   *  never will. An absent prop means the tab is not rendered at all, rather than a tab
   *  that opens onto an empty explanation of why it is empty. */
  invoices?: ReactNode
  entityType: TimelineEntityType
  entityId: string
  /**
   * Forwarded to `Timeline` untouched -- see that component's own docstring for
   * why it exists and what the backend bounds it to (1-200, default 50).
   * Optional, because most callers want the default; exposed here rather than
   * only on `Timeline` itself because this layout is what actually mounts the
   * Timeline tab -- no page renders `Timeline` directly, so this is the only
   * place a real caller could ever reach the prop.
   */
  timelineLimit?: number
}

/**
 * One layout for Customer, Person and Deal: the same *Panoramica · Timeline ·
 * Collegamenti* shape for all three, so the product is predictable to learn.
 * Three similar pages drift apart from each other over time; one shared
 * component cannot. Later slices add Documenti, Attività and Fatture as further
 * tabs here, once, for all three entities at once -- never as a fourth near-copy
 * of this file.
 */
export function EntityDetailLayout({
  title,
  subtitle,
  actions,
  overview,
  links,
  documents,
  invoices,
  entityType,
  entityId,
  timelineLimit,
}: EntityDetailLayoutProps) {
  return (
    <div className="p-8">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-muted-foreground">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
      </header>

      <Tabs defaultValue="panoramica">
        <TabsList>
          <TabsTrigger value="panoramica">Panoramica</TabsTrigger>
          {documents && <TabsTrigger value="documenti">Documenti</TabsTrigger>}
          {invoices && <TabsTrigger value="fatture">Fatture</TabsTrigger>}
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="collegamenti">Collegamenti</TabsTrigger>
        </TabsList>

        <TabsContent value="panoramica" className="mt-6">
          {overview}
        </TabsContent>
        {documents && (
          <TabsContent value="documenti" className="mt-6">
            {documents}
          </TabsContent>
        )}
        {invoices && (
          <TabsContent value="fatture" className="mt-6">
            {invoices}
          </TabsContent>
        )}
        <TabsContent value="timeline" className="mt-6">
          <Timeline entityType={entityType} entityId={entityId} limit={timelineLimit} />
        </TabsContent>
        <TabsContent value="collegamenti" className="mt-6">
          {links ?? <p className="text-muted-foreground">Nessun collegamento.</p>}
        </TabsContent>
      </Tabs>
    </div>
  )
}
