from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, GmailAccount, Message
from app.schemas import AliasGenerateRequest
from app.services.aliases import find_alias_for_headers, generate_aliases, refresh_alias_stats, render_alias_tag


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_generate_plus_aliases_and_match_headers():
    db = _db()
    account = GmailAccount(email="user@gmail.com", encrypted_refresh_token="secret")
    db.add(account)
    db.commit()
    db.refresh(account)

    aliases = generate_aliases(db, account, AliasGenerateRequest(pattern="shop-{n}", count=3))

    assert [alias.alias_address for alias in aliases] == [
        "user+shop-1@gmail.com",
        "user+shop-2@gmail.com",
        "user+shop-3@gmail.com",
    ]
    match = find_alias_for_headers(db, account.id, {"to": "User <user+shop-2@gmail.com>"})
    assert match is not None
    assert match.alias_address == "user+shop-2@gmail.com"


def test_alias_stats_count_messages():
    db = _db()
    account = GmailAccount(email="user@gmail.com", encrypted_refresh_token="secret")
    db.add(account)
    db.commit()
    db.refresh(account)
    alias = generate_aliases(db, account, AliasGenerateRequest(pattern="inbox-{n}", count=1))[0]
    db.add(Message(account_id=account.id, alias_id=alias.id, gmail_message_id="m1"))
    db.commit()

    refresh_alias_stats(db, account.id)
    db.refresh(alias)

    assert alias.message_count == 1


def test_render_alias_pattern_with_zero_padded_counter():
    assert render_alias_tag("shop-{n:00}", 1) == "shop-01"
    assert render_alias_tag("shop-{n:000}", 12) == "shop-012"


def test_generate_random_alias_pattern():
    db = _db()
    account = GmailAccount(email="user@gmail.com", encrypted_refresh_token="secret")
    db.add(account)
    db.commit()
    db.refresh(account)

    aliases = generate_aliases(db, account, AliasGenerateRequest(pattern="promo-{rand:5}", count=3))

    assert len(aliases) == 3
    assert len({alias.alias_address for alias in aliases}) == 3
    for alias in aliases:
        local = alias.alias_address.split("@", 1)[0]
        assert local.startswith("user+promo-")
        assert len(local.replace("user+promo-", "")) == 5
