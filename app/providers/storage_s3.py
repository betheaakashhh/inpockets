from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from typing import Any

from app.providers.storage import (
    DocumentStorage,
    StoredDocument,
    StoredDocumentContent,
)

_SAFE_HINT = re.compile(r"[^A-Za-z0-9._-]+")
_VALID_REF = re.compile(r"^[A-Za-z0-9._-]{1,400}$")


def safe_key_hint(key_hint: str) -> str:
    """Flatten a caller-supplied hint into a safe, slash-free key segment."""
    cleaned = _SAFE_HINT.sub("_", key_hint).strip("._")
    return cleaned[:300] or "document"


class S3DocumentStorage(DocumentStorage):
    """Private, encrypted S3 object storage for controlled documents.

    - Objects are content-addressed (`<hint>-<sha256>`), so a retry writes the
      same key with the same bytes and an existing object is never replaced.
    - SSE-KMS (or SSE-S3 when no key is configured) on every write.
    - S3 verifies the SHA-256 we send, so corruption in transit is rejected.
    - No ACLs are ever set; the bucket must have Block Public Access enabled.
    - Credentials come from the AWS default credential chain only.
    - Clients never receive storage credentials or object URLs.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        kms_key_id: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        client: Any | None = None,
    ):
        if not bucket:
            raise RuntimeError("DOCUMENT_STORAGE_S3_BUCKET is required for s3 storage")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.kms_key_id = kms_key_id
        if client is None:
            import boto3

            client = boto3.client(
                "s3", region_name=region, endpoint_url=endpoint_url
            )
        self.client = client

    # ------------------------------------------------------------------

    def _key(self, storage_ref: str) -> str:
        if not _VALID_REF.match(storage_ref) or ".." in storage_ref:
            raise ValueError("Invalid storage reference")
        return f"{self.prefix}/{storage_ref}" if self.prefix else storage_ref

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        error = getattr(exc, "response", {}).get("Error", {})
        return error.get("Code") in {"404", "NoSuchKey", "NotFound"}

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        digest = hashlib.sha256(content)
        checksum = digest.hexdigest()
        storage_ref = f"{safe_key_hint(key_hint)}-{checksum}"
        key = self._key(storage_ref)

        def _put() -> None:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return  # content-addressed: already stored, never overwrite
            except Exception as exc:  # noqa: BLE001 - botocore ClientError
                if not self._is_missing(exc):
                    raise

            extra: dict[str, Any] = {
                "ServerSideEncryption": "aws:kms" if self.kms_key_id else "AES256"
            }
            if self.kms_key_id:
                extra["SSEKMSKeyId"] = self.kms_key_id
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ChecksumSHA256=base64.b64encode(digest.digest()).decode(),
                Metadata={"sha256": checksum},
                **extra,
            )

        await asyncio.to_thread(_put)
        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )

    async def get(self, storage_ref: str) -> StoredDocumentContent:
        try:
            key = self._key(storage_ref)
        except ValueError as exc:
            raise FileNotFoundError(
                f"Document not found in object storage: {storage_ref}"
            ) from exc

        def _get() -> StoredDocumentContent:
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                if self._is_missing(exc):
                    raise FileNotFoundError(
                        f"Document not found in object storage: {storage_ref}"
                    ) from exc
                raise
            body = response["Body"].read()
            return StoredDocumentContent(
                content=body,
                content_type=response.get("ContentType", "application/octet-stream"),
            )

        return await asyncio.to_thread(_get)

    async def exists(self, storage_ref: str) -> bool:
        try:
            key = self._key(storage_ref)
        except ValueError:
            return False  # an unsafe reference can never name a stored object

        def _exists() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception as exc:  # noqa: BLE001
                if self._is_missing(exc):
                    return False
                raise

        return await asyncio.to_thread(_exists)

    async def delete(self, storage_ref: str) -> None:
        key = self._key(storage_ref)
        await asyncio.to_thread(
            self.client.delete_object, Bucket=self.bucket, Key=key
        )
