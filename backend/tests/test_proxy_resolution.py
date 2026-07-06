from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, GmailAccount, ProxyConfig
from app.services.proxy import resolve_proxy


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_direct_account_proxy_mode_bypasses_pool_and_global_proxies():
    db = _db()
    db.add(ProxyConfig(name="Pool", type="socks5", host="127.0.0.1", port=1080, enabled=True, is_global=False))
    db.add(ProxyConfig(name="Global", type="socks5", host="127.0.0.2", port=1080, enabled=True, is_global=True))
    account = GmailAccount(email="user@gmail.com", proxy_mode="direct")
    db.add(account)
    db.commit()
    db.refresh(account)

    assert resolve_proxy(db, account) is None


def test_fixed_account_proxy_wins_over_pool_proxy():
    db = _db()
    pool = ProxyConfig(name="Pool", type="socks5", host="127.0.0.1", port=1080, enabled=True, is_global=False)
    fixed = ProxyConfig(name="Fixed", type="socks5", host="127.0.0.2", port=1081, enabled=True, is_global=False)
    db.add(pool)
    db.add(fixed)
    db.commit()
    account = GmailAccount(email="user@gmail.com", proxy_mode="fixed", proxy_id=fixed.id)
    db.add(account)
    db.commit()
    db.refresh(account)

    assert resolve_proxy(db, account).id == fixed.id
