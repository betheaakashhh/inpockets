from pathlib import Path

import pytest

from app.providers.storage_development import DevelopmentDocumentStorage


@pytest.mark.asyncio
async def test_put_and_get_preserves_content_type(
    tmp_path: Path,
    monkeypatch,
):
    class FakeSettings:
        document_storage_path = str(tmp_path)

    monkeypatch.setattr(
        "app.providers.storage_development.get_settings",
        lambda: FakeSettings(),
    )

    storage = DevelopmentDocumentStorage()

    content = b"%PDF-1.7\nstorage-test"

    stored = await storage.put(
        content=content,
        content_type="application/pdf",
        key_hint="test-document",
    )

    result = await storage.get(stored.storage_ref)

    assert result.content == content
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_delete_removes_document_and_metadata(
    tmp_path: Path,
    monkeypatch,
):
    class FakeSettings:
        document_storage_path = str(tmp_path)

    monkeypatch.setattr(
        "app.providers.storage_development.get_settings",
        lambda: FakeSettings(),
    )

    storage = DevelopmentDocumentStorage()

    stored = await storage.put(
        content=b"%PDF-1.7\ndelete-test",
        content_type="application/pdf",
        key_hint="delete-document",
    )

    document_path = tmp_path / stored.storage_ref
    metadata_path = tmp_path / f"{stored.storage_ref}.meta"

    assert document_path.exists()
    assert metadata_path.exists()
    assert await storage.exists(stored.storage_ref)

    await storage.delete(stored.storage_ref)

    assert not document_path.exists()
    assert not metadata_path.exists()
    assert not await storage.exists(stored.storage_ref)