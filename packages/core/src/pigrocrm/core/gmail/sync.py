"""The incremental cycle.

No daemon: the sync runs on request -- a button, `POST /api/gmail/sync`, or a
`docker compose run` from cron installed by the operator, the same scheme already
documented for the MCP server. This project has no worker process, and adding a queue
for one job is complexity that does not pay for itself today -- the same reasoning that
made slice 2's PDF render synchronous.

Three properties this module exists to hold:

* **Every listing carries an address filter.** Not by convention: the queries come from
  `build_list_queries`, which is fed the roster and nothing else, and the URL can only
  be built by `messages_list_url`, which refuses a `q` without an address clause. An
  empty roster therefore issues no request at all -- not one unfiltered request.
* **A conversation is stored whole.** The listing finds *which* threads are relevant;
  the thread endpoint then supplies all of their messages, including the ones from
  people the CRM has never heard of. A thread read halfway is worse than one not read:
  if the client writes, a colleague answers in copy and the client confirms, keeping
  only the first and the third produces a thread that lies. The addresses met that way
  do **not** enter the roster (spec 4.3), or relevance would widen by itself on every
  cycle.
* **Re-running is free.** The watermark is rolled back by the configured overlap on
  every cycle, so each run deliberately re-reads a day of stored mail; the unique
  constraint on `(google_account_id, gmail_message_id)` is what makes that cost one
  refused insert instead of a duplicate.

Nothing here logs, and no message body, subject or address is put into an exception. A
failure carries the counters and Google's own status, which is all a caller can act on.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from pigrocrm.core.activities.service import ActivityService
from pigrocrm.core.actor import Actor
from pigrocrm.core.config import Settings, decode_google_token_key, require_gmail_configured
from pigrocrm.core.errors import Conflict
from pigrocrm.core.gmail.crypto import unseal
from pigrocrm.core.gmail.models import GmailMessage, GoogleAccount
from pigrocrm.core.gmail.parse import ParsedMessage, parse_message
from pigrocrm.core.gmail.query import build_list_queries, messages_list_url, thread_get_url
from pigrocrm.core.gmail.repository import GmailRepository
from pigrocrm.core.gmail.roster import AddressRoster, EntityRef
from pigrocrm.core.gmail.schemas import SyncReport
from pigrocrm.core.gmail.tokens import GoogleTokenClient
from pigrocrm.core.gmail.transport import GmailTransport

# How far back the first cycle looks when there is no watermark yet.
_FIRST_CYCLE_DAYS = 30

_SYNC_ACTION = "sincronizzare Gmail"
_WHAT_LIST = "elenco dei messaggi"
_WHAT_THREAD = "lettura di una conversazione"


class GmailSyncService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        transport: GmailTransport,
        tokens: GoogleTokenClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.transport = transport
        self.tokens = tokens
        self.repo = GmailRepository(session)
        self.roster = AddressRoster(session)
        self.activities = ActivityService(session)

    def sync(self, actor: Actor) -> SyncReport:
        require_gmail_configured(self.settings)
        actor.require_write(_SYNC_ACTION)
        account = self._account(actor)
        started_at = datetime.now(UTC)

        if not self.repo.try_sync_lock(account.id):
            # A cron every fifteen minutes and a human pressing the button is not a
            # hypothetical. Not an error and not a wait: the second caller gets a report
            # that says what is happening and since when, and spends nothing -- no token
            # refresh, no listing, no thread fetch.
            return SyncReport(
                started_at=started_at,
                already_running=True,
                running_since=self.repo.sync_started_at(account.id),
            )
        try:
            return self._run_cycle(account, actor, started_at)
        finally:
            # `finally`, so a raised cycle does not leak the lock. A leaked advisory lock
            # travels back into the connection pool with its connection and makes every
            # later sync for this mailbox answer "already running" for the life of the
            # process, which is indistinguishable from a hung job.
            self.repo.release_sync_lock(account.id)

    def _run_cycle(self, account: GoogleAccount, actor: Actor, started_at: datetime) -> SyncReport:
        """One whole cycle, holding the mailbox's lock from the first statement to the
        commit. Never called except through `sync`, which owns that lock."""
        report = SyncReport(started_at=started_at)

        report.states_pruned = self.repo.prune_states(started_at)

        addresses = self.roster.known_addresses()
        queries = (
            build_list_queries(
                addresses,
                after_epoch=int(self._window_start(account).timestamp()),
                batch_size=self.settings.gmail_sync_address_batch_size,
            )
            if addresses
            else ()
        )
        report.queries_issued = len(queries)

        if queries:
            # The token is fetched here and not above it: an empty roster must produce
            # no request to Google at all, and a refresh is a request.
            token = self._access_token(account)
            for thread_id in self._relevant_threads(queries, token):
                report.threads_fetched += 1
                self._store_thread(account, thread_id, token, report, actor)

        account.last_sync_at = started_at
        # The watermark is rolled back by the configured overlap on every cycle. It is
        # free because the unique constraint makes re-insertion idempotent, and it is
        # what absorbs a message that arrived across the boundary of two runs.
        account.sync_watermark = started_at - timedelta(
            hours=self.settings.gmail_watermark_overlap_hours
        )
        # Last, deliberately: `ActivityService.record` flushes into the caller's
        # transaction and its docstring forbids anything that commits on its own behalf
        # from running after it. Everything below this line is the commit itself.
        #
        # Only the counters go in. There is no subject, no address and no body in a
        # `SyncReport`, which is what makes this entry safe to show and to hand to an
        # agent -- the cycle is recorded, not its contents.
        self.activities.record(
            "google_account",
            account.id,
            "gmail.sync_eseguito",
            actor,
            {
                "queries_issued": report.queries_issued,
                "threads_fetched": report.threads_fetched,
                "messages_stored": report.messages_stored,
                "messages_skipped": report.messages_skipped,
                "links_created": report.links_created,
            },
        )
        self.session.commit()
        return report

    # ---- internals ---------------------------------------------------------------

    def _account(self, actor: Actor) -> GoogleAccount:
        if actor.id is None:
            raise Conflict("google_account", "solo un utente può sincronizzare una casella")
        account = self.repo.account_for_user(actor.id)
        if account is None:
            raise Conflict("google_account", "nessuna casella Google collegata")
        return account

    def _access_token(self, account: GoogleAccount) -> str:
        refresh_token = unseal(
            account.refresh_token_ciphertext,
            account.refresh_token_nonce,
            decode_google_token_key(self.settings),
        )
        return self.tokens.access_token(
            account_id=account.id,
            email_address=account.email_address,
            refresh_token=refresh_token,
        )

    def _window_start(self, account: GoogleAccount) -> datetime:
        if account.sync_watermark is not None:
            return account.sync_watermark
        return datetime.now(UTC) - timedelta(days=_FIRST_CYCLE_DAYS)

    def _relevant_threads(self, queries: tuple[str, ...], token: str) -> list[str]:
        """The thread ids the address filter found, deduplicated in order.

        Deduplicated because two addresses of the same customer routinely appear in one
        conversation, and fetching that thread twice would double the cost of the
        cycle for nothing.
        """
        thread_ids: list[str] = []
        seen: set[str] = set()
        for query in queries:
            for entry in self._list_all(query, token):
                thread_id = str(entry.get("threadId") or "")
                if thread_id and thread_id not in seen:
                    seen.add(thread_id)
                    thread_ids.append(thread_id)
        return thread_ids

    def _list_all(self, query: str, token: str) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        page_token: str | None = None
        while True:
            payload = self.transport.json(
                "GET",
                messages_list_url(query, page_token=page_token),
                token=token,
                what=_WHAT_LIST,
            )
            entries.extend(
                entry for entry in (payload.get("messages") or []) if isinstance(entry, dict)
            )
            next_token = payload.get("nextPageToken")
            # A page token that repeats itself would loop forever against a broken or
            # hostile server, so the loop advances only on a *new* one.
            page_token = str(next_token) if next_token and str(next_token) != page_token else None
            if page_token is None:
                return entries

    def _store_thread(
        self,
        account: GoogleAccount,
        thread_id: str,
        token: str,
        report: SyncReport,
        actor: Actor,
    ) -> None:
        payload = self.transport.json(
            "GET", thread_get_url(thread_id), token=token, what=_WHAT_THREAD
        )
        raw_messages = [raw for raw in (payload.get("messages") or []) if isinstance(raw, dict)]
        parsed_messages = [
            parse_message(
                raw,
                body_max_bytes=self.settings.gmail_body_max_bytes,
                store_bodies=account.gmail_store_bodies,
            )
            for raw in raw_messages
        ]
        thread_refs = self._thread_refs(parsed_messages)
        # One membership query for the whole conversation: after the first cycle almost
        # every thread comes back entirely known, and asking that per message would
        # spend a round trip apiece to learn nothing.
        present = self.repo.message_ids_present(
            account.id, [parsed.gmail_message_id for parsed in parsed_messages]
        )
        for parsed in parsed_messages:
            if not parsed.gmail_message_id or parsed.gmail_message_id in present:
                report.messages_skipped += 1
                continue
            row = self._store(account, parsed)
            if row is None:
                report.messages_skipped += 1
                continue
            report.messages_stored += 1
            self._file(account, parsed, row, thread_refs, actor, report)

    def _thread_refs(self, parsed_messages: list[ParsedMessage]) -> list[EntityRef]:
        """Every CRM entity the *conversation* touches, in the order it was met.

        Computed once for the thread and not per message, which is the whole of spec
        4.3 in one place: a sibling message from somebody nobody registered is filed
        against the same customer as the rest of the exchange, because it is part of
        that exchange. A per-message resolution would file half the thread and leave the
        other half invisible, which is the conversation that lies.

        Resolving does not widen relevance: `AddressRoster.resolve` only ever answers
        with entities that already exist, and an address met inside a thread still does
        not join `known_addresses`.
        """
        refs: list[EntityRef] = []
        for parsed in parsed_messages:
            for address in [parsed.from_address, *parsed.to_addresses, *parsed.cc_addresses]:
                for ref in self.roster.resolve(address):
                    if ref not in refs:
                        refs.append(ref)
        return refs

    def _file(
        self,
        account: GoogleAccount,
        parsed: ParsedMessage,
        row: GmailMessage,
        thread_refs: list[EntityRef],
        actor: Actor,
        report: SyncReport,
    ) -> None:
        """Links one stored message to the thread's entities, and puts an inbound one on
        their timelines.

        Only inbound: `gmail.messaggio_ricevuto` is a claim about direction, and an
        entry written for our own reply would tell the user their message had arrived.

        The payload carries the subject and the sender and stops there. That is the case
        `activities/sanitize.py` names in its own docstring -- "recording, say, an
        inbound email's subject line" -- and it is also the limit: a body in a timeline
        entry is published to the UI, to the REST timeline route and to `get_timeline`.
        """
        for ref in thread_refs:
            if self.repo.add_link(row.id, ref):
                report.links_created += 1
        if not parsed.direction_is_inbound(account.email_address):
            return
        for ref in thread_refs:
            self.activities.record(
                ref.entity_type,
                ref.entity_id,
                "gmail.messaggio_ricevuto",
                actor,
                {
                    "subject": parsed.subject,
                    "from_address": parsed.from_address,
                    "gmail_message_id": parsed.gmail_message_id,
                    "gmail_thread_id": parsed.gmail_thread_id,
                },
            )

    def _store(self, account: GoogleAccount, parsed: ParsedMessage) -> GmailMessage | None:
        """Returns the stored row, or `None` when the constraint refused it. A duplicate
        is not an error: it is the overlap doing its job, or a second cycle running at
        the same time.

        The row and not a flag, because the caller has to file it: a link needs the
        primary key the insert has just assigned.

        The `message_ids_present` check above never replaces the constraint -- two
        overlapping cycles both pass it, and only the database can arbitrate -- which is
        why the insert itself answers rather than raising.
        """
        row = GmailMessage(
            google_account_id=account.id,
            gmail_message_id=parsed.gmail_message_id,
            gmail_thread_id=parsed.gmail_thread_id,
            message_id_header=parsed.message_id_header[:998],
            in_reply_to=parsed.in_reply_to[:998],
            references=parsed.references,
            direction=(
                "inbound" if parsed.direction_is_inbound(account.email_address) else "outbound"
            ),
            from_address=parsed.from_address,
            to_addresses=list(parsed.to_addresses),
            cc_addresses=list(parsed.cc_addresses),
            subject=parsed.subject[:998],
            snippet=parsed.snippet[:500],
            internal_date=parsed.internal_date,
            body_text=parsed.body_text,
            body_truncated=parsed.body_truncated,
            body_html_scartato=parsed.body_html_scartato,
            attachments=[
                {"filename": a.filename, "mime": a.mime, "size": a.size} for a in parsed.attachments
            ],
        )
        return row if self.repo.add_message_if_absent(row) else None
