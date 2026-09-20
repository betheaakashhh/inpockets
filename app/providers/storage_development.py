import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.providers.storage import DocumentStorage, StoredDocument


class DevelopmentDocumentStorage(DocumentStorage):
    """Local development adapter; production must use private object storage."""

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        checksum = hashlib.sha256(content).hexdigest()
        root = Path(get_settings().document_storage_path)
        root.mkdir(parents=True, exist_ok=True)

        safe_hint = key_hint.replace("/", "_").replace("\\", "_")
        storage_ref = f"{safe_hint}-{checksum}"
        path = root / storage_ref

        if not path.exists():
            path.write_bytes(content)

        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )
