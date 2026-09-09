# Time tracking: a running timer and a register beside the grid

Date: 2026-09-09. Status: implemented the same day. Supersedes the «Timer / cronometro»
row of slice 4 §13 (`2026-08-20-slice-4-time-tracking-e-pl-design.md`), which argued
against a stopwatch; the grid that row defended stays.

## Why

Ivan asked for `/app/ore` to be revised with Toggl and Clockify as the reference. Both
products share one shape: a bar at the top that either runs a clock or takes a manual
line, and under it the day's entries as a list of *what* was done, each one continuable
with a click. The grid slice 4 built answers a different question ("which day did I not
enter?") and remains the second view.

## The clock is a row on the server

One table, `time_timers`, one row per user (unique index on `user_id`): what this person
is doing right now. Nullable `deal_id`, a description, `fatturabile`, `started_at`.

Stopping does not write an hour of its own. `TimerService.stop` builds a
`TimeEntryCreate` from the row -- `ore` is the elapsed time rounded to hundredths and
clamped into `[ORE_MIN, ORE_MAX]`, `data` is the caller's day or `today_local()` -- and
hands it to `TimeEntryService.create`, so the frozen rate, the period lock, the future
check, the closed-deal warning and the activity row are the ordinary ones. The timer row
is then deleted. Discarding deletes it and writes nothing.

A deal is required at stop, not at start: Toggl lets a clock run before the project is
chosen, and forcing the choice up front is what makes people not start the clock. Without
one, `stop` answers 422 naming `deal_id` and the timer keeps running.

Two devices see the same row; a closed browser loses nothing. That is the whole recovery
story slice 4 §13 costed at three mechanisms.

## Surface

- API, under `/api/time-entries`: `GET /timer` (200 with `null` when none), `POST
  /timer/start`, `PATCH /timer`, `POST /timer/stop` (201 with the `TimeEntryRead` it
  became), `DELETE /timer`. Declared before `/{entry_id}` so the literal wins.
- MCP: `get_running_timer`, `start_timer`, `update_timer`, `stop_timer`,
  `discard_timer`. The clock is the token owner's; an actor without an id (system) has
  none and `start_timer` refuses it.
- Web, `/app/ore` (`features/time/TimePage.tsx`): one header with the week controls and
  two tabs. «Registro»: `TimerBar` (description, deal, fatturabile, Avvia/Stop with the
  elapsed time, or hours + date + Aggiungi in manual mode) and `TimeRegister` (the week
  grouped by day, latest first, day totals, week total with the billable share, per
  entry: Continua as a new timer, Modifica in the existing dialog, Elimina). «Settimana»:
  `WeekGrid`, now the table alone -- the page owns the week and the two reads, so the
  tabs share them.

## What it does not do

No idle detection, no reminders, no calendar view, no tags: the deal is the project and
the description is the tag. No per-user timezone: the stop sends the browser's own day,
the MCP stop defaults to the emitter's zone.
