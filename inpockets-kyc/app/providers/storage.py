from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
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
        """Store content and return a reference to it. Never returns or
        logs the content itself.
        """
        raise NotImplementedError
