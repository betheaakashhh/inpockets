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

    def _confined(self, name: str) -> Path:
        root = self._root().resolve()
        path = (root / name).resolve()
        if root != path.parent:
            raise ValueError("Invalid storage reference")
        return path

    def _path_for(self, storage_ref: str) -> Path:
        return self._confined(storage_ref)

    def _metadata_path_for(self, storage_ref: str) -> Path:
        return self._confined(f"{storage_ref}.meta")

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
        metadata_path = self._metadata_path_for(storage_ref)

        if not path.exists():
            path.write_bytes(content)

        if not metadata_path.exists():
            metadata_path.write_text(
                content_type,
                encoding="utf-8",
            )

        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )

    async def get(
        self,
        storage_ref: str,
    ) -> StoredDocumentContent:
        try:
            path = self._path_for(storage_ref)
            metadata_path = self._metadata_path_for(storage_ref)
        except ValueError as exc:
            raise FileNotFoundError(
                f"Document not found in development storage: {storage_ref}"
            ) from exc

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found in development storage: {storage_ref}"
            )

        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Document metadata not found in development storage: {storage_ref}"
            )

        return StoredDocumentContent(
            content=path.read_bytes(),
            content_type=metadata_path.read_text(
                encoding="utf-8",
            ),
        )

    async def exists(
        self,
        storage_ref: str,
    ) -> bool:
        try:
            return self._path_for(storage_ref).exists()
        except ValueError:
            return False  # an unsafe reference can never name a stored object

    async def delete(
        self,
        storage_ref: str,
    ) -> None:
        try:
            path = self._path_for(storage_ref)
            metadata_path = self._metadata_path_for(storage_ref)
        except ValueError:
            return

        if path.exists():
            path.unlink()

        if metadata_path.exists():
            metadata_path.unlink()