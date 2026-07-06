from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import encrypt_secret
from app.models import Base, GmailAccount
from app.services import sync as sync_service


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


class DummyClient:
    def logout(self):
        return None


def test_sync_account_uses_limit_override(monkeypatch):
    db = _db()
    account = GmailAccount(
        email="user@gmail.com",
        status="active",
        encrypted_app_password=encrypt_secret("app-password"),
        initial_sync_limit=200,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    seen = {}

    monkeypatch.setattr(sync_service, "connect_imap", lambda email, password, proxy: DummyClient())

    def fake_fetch_uids(client, last_uid, days, limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(sync_service, "fetch_uids", fake_fetch_uids)

    job = sync_service.sync_account(db, account.id, limit_override=1)

    assert job.status == "success"
    assert seen["limit"] == 1
