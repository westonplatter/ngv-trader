"""Shared factory for `FlexClient` so all sync paths use the same retry/backoff.

Large date ranges (multi-month reimports) push IBKR's statement generation past
the default retry budget. Bump max_retries, base/max delays, and the initial
poll wait so 180-day pulls survive without manual reruns.
"""

from __future__ import annotations

from ngv_reports_ibkr.flex_client import FlexClient


def make_flex_client() -> FlexClient:
    return FlexClient(
        max_retries=10,
        base_retry_delay=2.0,
        max_retry_delay=120.0,
        statement_poll_delay=5.0,
    )
