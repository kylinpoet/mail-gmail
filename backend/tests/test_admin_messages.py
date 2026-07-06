from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.admin import delete_admin_message, delete_admin_messages_batch
from app.models import Attachment, Base, GmailAccount, Message
from app.schemas import MessageBatchRequest


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_delete_admin_message_removes_local_row_and_cached_attachment(tmp_path):
    db = _db()
    account = GmailAccount(email="user@gmail.com")
    db.add(account)
    db.commit()
    db.refresh(account)

    cached_file = tmp_path / "attachment.txt"
    cached_file.write_text("payload", encoding="utf-8")
    message = Message(account_id=account.id, gmail_message_id="uid-1", subject="Hello")
    db.add(message)
    db.commit()
    db.refresh(message)
    db.add(
        Attachment(
            message_id=message.id,
            gmail_attachment_id="uid-1:1",
            filename="attachment.txt",
            cached_path=str(cached_file),
        )
    )
    db.commit()

    result = delete_admin_message(message.id, db)

    assert result["ok"] is True
    assert result["deleted_id"] == message.id
    assert result["removed_cached_files"] == 1
    assert not cached_file.exists()
    assert db.query(Message).filter(Message.id == message.id).first() is None
    assert db.query(Attachment).filter(Attachment.message_id == message.id).first() is None


def test_batch_delete_admin_messages_removes_local_rows_and_cached_attachments(tmp_path):
    db = _db()
    account = GmailAccount(email="user@gmail.com")
    db.add(account)
    db.commit()
    db.refresh(account)

    message_ids = []
    cached_files = []
    for index in range(2):
        cached_file = tmp_path / ("attachment-%s.txt" % index)
        cached_file.write_text("payload", encoding="utf-8")
        cached_files.append(cached_file)
        message = Message(account_id=account.id, gmail_message_id="uid-%s" % index, subject="Hello")
        db.add(message)
        db.commit()
        db.refresh(message)
        message_ids.append(message.id)
        db.add(
            Attachment(
                message_id=message.id,
                gmail_attachment_id="uid-%s:1" % index,
                filename="attachment-%s.txt" % index,
                cached_path=str(cached_file),
            )
        )
    db.commit()

    result = delete_admin_messages_batch(MessageBatchRequest(ids=message_ids), db)

    assert result["ok"] is True
    assert result["deleted_count"] == 2
    assert result["deleted_ids"] == message_ids
    assert result["removed_cached_files"] == 2
    assert all(not path.exists() for path in cached_files)
    assert db.query(Message).count() == 0
    assert db.query(Attachment).count() == 0
