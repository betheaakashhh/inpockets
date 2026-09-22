import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.providers.storage import (
    DocumentStorage,
    StoredDocument,
    StoredDocumentContent,
)


class DevelopmentDocumentStorage(DocumentStorage):
    """Local development adapter; production must use private object storage."""

    def _root(self) -> Path:
        return Path(get_settings().document_storage_path)

    def _path_for(self, storage_ref: str) -> Path:
        return self._root() / storage_ref

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        checksum = hashlib.sha256(content).hexdigest()

        root = self._root()
        root.mkdir(parents=True, exist_ok=True)

        safe_hint = key_hint.replace("/", "_").replace("\\", "_")
        storage_ref = f"{safe_hint}-{checksum}"
        path = self._path_for(storage_ref)

        if not path.exists():
            path.write_bytes(content)

        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )

    async def get(
        self,
        storage_ref: str,
    ) -> StoredDocumentContent:
        path = self._path_for(storage_ref)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found in development storage: {storage_ref}"
            )

        return StoredDocumentContent(
            content=path.read_bytes(),
            content_type="application/octet-stream",
        )

    async def exists(
        self,
        storage_ref: str,
    ) -> bool:
        return self._path_for(storage_ref).exists()

    async def delete(
        self,
        storage_ref: str,
    ) -> None:
        path = self._path_for(storage_ref)

        if path.exists():
            path.unlink()