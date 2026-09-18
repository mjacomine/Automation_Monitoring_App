"""Client for the UiPath Orchestrator OData API.

Encapsulates everything about *talking to Orchestrator*: building the OData
``$filter`` and issuing the authenticated request. Callers get back the raw
decoded JSON; turning that into insight is the analytics layer's job, not this
one's. This separation means the API shape can change here without rippling
into reporting.

Every request goes through :meth:`OrchestratorClient._get`, which paces calls
and retries HTTP 429 honouring ``Retry-After``. Orchestrator rate-limits under
sustained polling — the paged QueueItems walk met it at roughly 100 rapid
requests — so that handling belongs at the transport level rather than in any
one caller.
"""

from __future__ import annotations

import email.utils
import sys
import time
from datetime import datetime, timezone

import requests

from .config import ClientConfig, Settings

# Hard server cap on the QueueItems endpoint: $top=100 succeeds and $top=101
# already returns HTTP 400, so pages cannot be made larger. Note the failure is
# not always loud — some oversized values come back 400 with an empty body,
# which reads like "no new data" if the status code is not checked.
QUEUE_PAGE_SIZE = 100

# A first run against an empty table never meets a known key, so it would walk
# the entire queue history (~80k items = ~800 requests for one live tenant).
# This bounds that walk; hitting it is reported rather than passing silently.
QUEUE_MAX_PAGES = 200



class OrchestratorClient:
    """Thin, authenticated wrapper over one client's Orchestrator Jobs endpoint."""

    def __init__(
        self, settings: Settings, client: ClientConfig, access_token: str
    ) -> None:
        self._settings = settings
        self._client = client
        self._access_token = access_token
        # Monotonic timestamp of the last request, used to pace the next one.
        # Per-instance, so each configured client gets its own budget.
        self._last_request_at = 0.0

    # --- Request plumbing --------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    def _retry_after_seconds(self, response: requests.Response, attempt: int) -> float:
        """How long to wait before retrying a 429.

        Prefers the server's ``Retry-After``, which may be either a number of
        seconds or an HTTP-date. Falls back to exponential backoff when the
        header is absent or unparseable, and clamps the result so a large or
        malformed value cannot stall the run indefinitely.
        """
        raw = (response.headers.get("Retry-After") or "").strip()
        wait: float | None = None
        if raw:
            try:
                wait = float(raw)
            except ValueError:
                # HTTP-date form: wait until that moment.
                try:
                    parsed = email.utils.parsedate_to_datetime(raw)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    wait = (parsed - datetime.now(timezone.utc)).total_seconds()
        if wait is None or wait < 0:
            wait = 2.0 ** attempt  # 1, 2, 4, 8, ...
        return max(0.0, min(wait, self._settings.rate_limit_max_wait))

    def _get(self, url: str, params: dict | None = None) -> dict:
        """Issue a paced, 429-aware GET and return the decoded JSON.

        Every Orchestrator call routes through here so pacing and retry apply
        uniformly. Requests are spaced by ``min_request_interval`` measured
        from the previous call, so an occasional request waits not at all and
        only a tight loop is throttled. A 429 is retried up to
        ``rate_limit_retries`` times honouring ``Retry-After``; any other
        non-2xx is raised at once, since only rate limiting is worth waiting
        out.

        Raises:
            requests.HTTPError: on a non-2xx response, including a 429 that
                survived every retry.
        """
        for attempt in range(self._settings.rate_limit_retries + 1):
            gap = self._settings.min_request_interval - (
                time.monotonic() - self._last_request_at
            )
            if gap > 0:
                time.sleep(gap)

            response = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self._settings.request_timeout,
            )
            self._last_request_at = time.monotonic()

            if response.status_code != 429:
                response.raise_for_status()
                return response.json()

            if attempt == self._settings.rate_limit_retries:
                break
            wait = self._retry_after_seconds(response, attempt)
            print(
                f"  Rate limited (429); retrying in {wait:.0f}s "
                f"(attempt {attempt + 1}/{self._settings.rate_limit_retries}).",
                file=sys.stderr,
            )
            time.sleep(wait)

        # Retries exhausted — surface the 429 to the caller.
        response.raise_for_status()
        return response.json()  # pragma: no cover - raise_for_status raises

    def build_filter(self) -> str:
        """Build the OData ``$filter`` expression from configuration."""
        clauses = [f"CreationTime gt {self._settings.creation_time}"]
        if self._settings.source_type:
            clauses.append(f"Type eq '{self._settings.source_type}'")
        return "(" + " and ".join(clauses) + ")"

    def get_jobs(self) -> dict:
        """Call the Get Jobs endpoint and return the decoded OData payload.

        Raises:
            requests.HTTPError: on a non-2xx response.
        """
        return self._get(
            self._client.jobs_url(self._settings.base_url),
            {"$filter": self.build_filter()},
        )

    # Only these fields are stored in f_queue_item_metrics, so only these are
    # requested. Narrowing $select keeps SpecificContent — which can carry
    # sensitive payload data — out of the response entirely.
    QUEUE_ITEM_FIELDS = ("UniqueKey", "Status", "EndProcessing", "QueueDefinitionId")

    def build_queue_filter(self) -> str:
        """Build the OData ``$filter`` for the QueueItems query.

        Only ``Status`` is filtered server-side. Unlike the Jobs endpoint,
        Orchestrator's QueueItems endpoint rejects a ``$filter`` on any
        datetime field: ``CreationTime``, ``EndProcessing``, ``StartProcessing``
        and ``DueDate`` all return "Invalid OData query options", in every
        literal form tried (bare ISO, trailing ``Z``, explicit offset,
        ``datetime'...'``, ``cast(...)``, and ``ge`` as well as ``gt``). The
        incremental window is therefore applied client-side, in
        :meth:`get_queue_items_until_known`.

        Excluding ``New`` drops items that have not been picked up yet. It does
        *not* guarantee a non-NULL ``EndProcessing``: ``Deleted`` items were
        never processed and ``InProgress`` items have not finished, and both
        pass this filter.
        """
        return "Status ne 'New'"

    def get_queue_items(self, params: dict | None = None) -> dict:
        """Call the QueueItems endpoint and return the decoded OData payload.

        Sends the incremental ``$filter`` from :meth:`build_queue_filter` and a
        ``$select`` limited to :data:`QUEUE_ITEM_FIELDS`. Both are defaults:
        anything supplied in ``params`` wins, so callers can still issue an
        ad-hoc query.

        Args:
            params: OData query options that override the defaults, e.g.
                ``{"$top": 10}`` or a different ``$filter``.

        Raises:
            requests.HTTPError: on a non-2xx response.
        """
        query = {
            "$filter": self.build_queue_filter(),
            "$select": ",".join(self.QUEUE_ITEM_FIELDS),
        }
        query.update(params or {})
        return self._get(
            self._client.queue_items_url(self._settings.base_url), query
        )

    # The queue dimension needs only the identifier and display name; $select
    # keeps the several JSON-schema blobs the endpoint also returns out of the
    # response.
    QUEUE_DEFINITION_FIELDS = ("Id", "Name")

    def get_queue_definitions(self) -> dict:
        """Call the QueueDefinitions endpoint and return the decoded payload.

        Queue definitions are a small dimension (a handful per tenant), so this
        is a single unpaged request with no incremental window — each run
        refreshes the full set.

        Raises:
            requests.HTTPError: on a non-2xx response.
        """
        return self._get(
            self._client.queue_definitions_url(self._settings.base_url),
            {"$select": ",".join(self.QUEUE_DEFINITION_FIELDS)},
        )

    def get_queue_items_until_known(
        self, is_known, max_pages: int = QUEUE_MAX_PAGES
    ) -> dict:
        """Fetch queue items newest-first, stopping at the first one we stored.

        Returns an OData-shaped ``{"value": [...]}`` payload.

        The endpoint will not filter on a datetime (see
        :meth:`build_queue_filter`) but it will order by ``EndProcessing``, so
        the incremental window is walked instead of queried. Because items are
        ordered by completion time and a completing item always takes the top
        of that order, everything below the first already-stored key has been
        seen before — so the walk can stop there.

        Using the stored keys rather than a timestamp makes the walk
        self-correcting: it does not depend on the poll cursor being accurate,
        and re-running it is harmless.

        ``EndProcessing`` can be NULL despite the ``Status ne 'New'`` filter —
        ``Deleted`` items never processed at all, and ``InProgress`` items have
        not finished yet. Both sort to the bottom under a descending order, so
        reaching one means the dated records are exhausted. They are skipped,
        not stored; an ``InProgress`` item reappears at the top of the ordering
        once it completes.

        Args:
            is_known: Callable taking a list of ``UniqueKey`` values and
                returning the subset already persisted. Injected so this class
                stays free of database concerns.
            max_pages: Safety bound on the walk.
        """
        collected: list[dict] = []
        skip = 0
        pages = 0
        stopped_early = False

        while pages < max_pages:
            page = self.get_queue_items(
                {
                    "$orderby": "EndProcessing desc",
                    "$top": QUEUE_PAGE_SIZE,
                    "$skip": skip,
                }
            ).get("value", [])
            pages += 1
            if not page:
                stopped_early = True
                break

            keys = [i.get("UniqueKey") for i in page if i.get("UniqueKey")]
            known = is_known(keys)

            for item in page:
                key = item.get("UniqueKey")
                if key and key in known:
                    stopped_early = True
                    break
                if not item.get("EndProcessing"):
                    # Deleted / InProgress: nothing dated remains below here.
                    stopped_early = True
                    break
                collected.append(item)

            if stopped_early or len(page) < QUEUE_PAGE_SIZE:
                stopped_early = True
                break
            skip += QUEUE_PAGE_SIZE

        if not stopped_early:
            print(
                f"  WARNING: QueueItems walk hit the {max_pages}-page limit "
                f"({len(collected)} item(s) collected) without reaching a "
                "known item; some history may not have been retrieved.",
                file=sys.stderr,
            )
        return {"value": collected}
