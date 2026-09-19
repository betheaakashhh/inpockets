"""
Dev/test stand-in for S3. Writes under a temp directory; storage_ref is a
`local://<filename>` URI so it's visibly distinct from a real
`s3://bucket/key` reference and can't be mistaken for one.

NOT encrypted at rest, NOT access-controlled - fine for local dev and tests,
not something to point at real documents with. A real S3 adapter (server-
side encryption via KMS, bucket policy, presigned URLs) implements the same
DocumentStorage interface and is swapped in via app/core/verification.py
once AWS infrastructure exists - no other file needs to change.
"""

import hashlib
import tempfile
import uuid
from pathlib import Path

from app.providers.storage import DocumentStorage, StoredDocument


class LocalDocumentStorage(DocumentStorage):
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(tempfile.gettempdir()) / "inpockets_documents"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        checksum = hashlib.sha256(content).hexdigest()
        filename = f"{uuid.uuid4().hex}_{key_hint}"
        path = self.base_dir / filename
        path.write_bytes(content)

        return StoredDocument(
            storage_ref=f"local://{filename}",
            checksum=checksum,
            size_bytes=len(content),
        )
