from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredDocument:
    storage_ref: str
    checksum: str
    size_bytes: int


class DocumentStorage(ABC):
    @abstractmethod
    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        raise NotImplementedError
