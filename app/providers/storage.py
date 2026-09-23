from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredDocument:
    storage_ref: str
    checksum: str
    size_bytes: int


@dataclass(frozen=True)
class StoredDocumentContent:
    content: bytes
    content_type: str


class DocumentStorage(ABC):
    @abstractmethod
    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        storage_ref: str,
    ) -> StoredDocumentContent:
        raise NotImplementedError

    @abstractmethod
    async def exists(
        self,
        storage_ref: str,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def delete(
        self,
        storage_ref: str,
    ) -> None:
        raise NotImplementedError