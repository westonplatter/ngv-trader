"""ORM round-trip — catches SQLAlchemy/psycopg2 breakage on dependency bumps."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Account


def test_account_round_trip(db_session: Session) -> None:
    db_session.add(Account(account="U1234567", alias="test account"))
    db_session.flush()

    loaded = db_session.execute(select(Account).where(Account.account == "U1234567")).scalar_one()
    assert loaded.alias == "test account"
    assert loaded.id is not None
