"""An account whose FlexQuery snapshot shows no open positions.

Before, an empty report returned early: the account's last ``positions`` rows,
and any tags on them, lived on. Now an affirmatively empty ``OpenPositions``
section clears the account, while a missing statement or section changes
nothing -- that is the guard against wiping positions on a bad report.
"""

from __future__ import annotations

from datetime import date, timedelta

from defusedxml import ElementTree as ET
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Position, Tag, TagLink
from src.services.position_sync_flexquery import _confirmed_flat_as_of, sync_flex_positions
from tests.trade_group_factories import ACCOUNT_MAIN, CON_CL, make_account, make_position

TO_DATE = date(2026, 6, 19)


def _report(statement: str) -> CustomFlexReport:
    report = CustomFlexReport()
    report.root = ET.fromstring(f"<FlexQueryResponse><FlexStatements>{statement}</FlexStatements></FlexQueryResponse>")
    return report


def _statement(account: str, body: str) -> str:
    return f'<FlexStatement accountId="{account}" fromDate="20260619" toDate="20260619">{body}</FlexStatement>'


FLAT = _statement(ACCOUNT_MAIN, "<AccountInformation /><OpenPositions />")


def test_flat_requires_the_account_statement_and_an_empty_section() -> None:
    assert _confirmed_flat_as_of(_report(FLAT), ACCOUNT_MAIN) == TO_DATE
    # Section missing (query not configured for positions): no evidence.
    assert _confirmed_flat_as_of(_report(_statement(ACCOUNT_MAIN, "<AccountInformation />")), ACCOUNT_MAIN) is None
    # Another account's statement only.
    assert _confirmed_flat_as_of(_report(FLAT), "U7654321") is None
    # Rows present that the parser filtered out (e.g. SUMMARY only): not flat.
    summary = _statement(ACCOUNT_MAIN, '<OpenPositions><OpenPosition accountId="x" levelOfDetail="SUMMARY" /></OpenPositions>')
    assert _confirmed_flat_as_of(_report(summary), ACCOUNT_MAIN) is None


def test_flat_account_clears_positions_and_ends_their_tags(db_session: Session) -> None:
    account = make_account(db_session)
    make_position(db_session, account=account, con_id=CON_CL, as_of_date=TO_DATE - timedelta(days=3))
    tag = Tag(value="oil", normalized_value="oil", created_by="user")
    db_session.add(tag)
    db_session.flush()
    db_session.add(TagLink(tag_id=tag.id, entity_type="position", account_id=account.id, con_id=CON_CL, created_by="user"))
    db_session.flush()
    # Assigned before the flat snapshot's date, so the date guard lets it end.
    link = db_session.execute(select(TagLink)).scalar_one()
    link.assigned_at = link.assigned_at.replace(year=2026, month=6, day=1)
    db_session.flush()

    # The session's connection stands in for the engine; its commit stays inside
    # the test transaction, which is rolled back afterwards.
    result = sync_flex_positions(db_session.connection(), account_code=ACCOUNT_MAIN, report=_report(FLAT))  # type: ignore[arg-type]

    assert result["deleted_count"] == 1
    assert result["as_of_date"] == TO_DATE
    db_session.expire_all()
    assert db_session.execute(select(Position).where(Position.account_id == account.id)).first() is None
    assert db_session.execute(select(TagLink.ended_at)).scalar_one() is not None


def test_report_without_the_section_leaves_positions_alone(db_session: Session) -> None:
    account = make_account(db_session)
    make_position(db_session, account=account, con_id=CON_CL)

    result = sync_flex_positions(
        db_session.connection(),  # type: ignore[arg-type]
        account_code=ACCOUNT_MAIN,
        report=_report(_statement(ACCOUNT_MAIN, "<AccountInformation />")),
    )

    assert result["upserted_count"] == 0 and "deleted_count" not in result
    assert db_session.execute(select(Position).where(Position.account_id == account.id)).first() is not None
