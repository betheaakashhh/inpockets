"""Field-level encryption for sensitive values stored in PostgreSQL.

Design (to be confirmed against the approved security design / KMS plan):
  * AES-256-GCM, random 96-bit nonce per value.
  * Versioned keyring so keys can rotate: encrypt with the active key,
    decrypt with any listed key. The key id is embedded in the ciphertext.
  * Associated data binds a ciphertext to its record ("context"), so a
    ciphertext copied to another row fails to decrypt.
  * Keys come from the environment/secrets manager, never from code. With no
    keys configured every operation refuses (fail closed).
  * `FieldEncryptor` is an interface, so a KMS envelope implementation can
    replace the local keyring without touching callers.

Ciphertext format:  v1:<key_id>:<base64url(nonce || ciphertext+tag)>
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings

_VERSION = "v1"


class EncryptionError(Exception):
    """Encryption is misconfigured or a value cannot be decrypted."""


class FieldEncryptor(ABC):
    @property
    @abstractmethod
    def active_key_id(self) -> str: ...

    @abstractmethod
    def encrypt(self, plaintext: str, *, context: str) -> str: ...

    @abstractmethod
    def decrypt(self, token: str, *, context: str) -> str: ...

    @staticmethod
    def key_id_of(token: str) -> str:
        parts = token.split(":", 2)
        if len(parts) != 3 or parts[0] != _VERSION:
            raise EncryptionError("unrecognised ciphertext format")
        return parts[1]


@dataclass(frozen=True)
class _Keyring:
    keys: dict[str, bytes]
    active: str


def _b64decode_key(raw: str) -> bytes:
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EncryptionError("encryption key is not valid base64") from exc
    if len(key) != 32:
        raise EncryptionError("encryption keys must be exactly 32 bytes")
    return key


def parse_keyring(raw: str | None, active: str | None) -> _Keyring:
    if not raw or not active:
        raise EncryptionError("field encryption is not configured")
    keys: dict[str, bytes] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        kid, sep, material = item.partition(":")
        kid = kid.strip()
        if not sep or not kid or ":" in kid:
            raise EncryptionError("malformed encryption keyring entry")
        if kid in keys:
            raise EncryptionError("duplicate encryption key id")
        keys[kid] = _b64decode_key(material)
    if active not in keys:
        raise EncryptionError("active encryption key is not in the keyring")
    return _Keyring(keys=keys, active=active)


class AesGcmKeyringEncryptor(FieldEncryptor):
    def __init__(self, keyring: _Keyring):
        self._ring = keyring

    @property
    def active_key_id(self) -> str:
        return self._ring.active

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(12)
        sealed = AESGCM(self._ring.keys[self._ring.active]).encrypt(
            nonce, plaintext.encode(), context.encode()
        )
        blob = base64.urlsafe_b64encode(nonce + sealed).decode()
        return f"{_VERSION}:{self._ring.active}:{blob}"

    def decrypt(self, token: str, *, context: str) -> str:
        kid = self.key_id_of(token)
        key = self._ring.keys.get(kid)
        if key is None:
            raise EncryptionError("ciphertext key is not in the keyring")
        try:
            raw = base64.urlsafe_b64decode(token.split(":", 2)[2])
            return AESGCM(key).decrypt(raw[:12], raw[12:], context.encode()).decode()
        except (InvalidTag, binascii.Error, ValueError) as exc:
            # Deliberately vague: never reveal why.
            raise EncryptionError("could not decrypt value") from exc


def get_field_encryptor(settings: Settings | None = None) -> FieldEncryptor:
    s = settings or get_settings()
    return AesGcmKeyringEncryptor(
        parse_keyring(s.field_encryption_keys, s.field_encryption_active_key_id)
    )


def keyed_fingerprint(value: str, *, settings: Settings | None = None) -> str:
    """Deterministic keyed hash (HMAC-SHA256) for equality lookups.

    Unlike a plain hash it cannot be brute-forced from a database leak
    without the key.
    """
    s = settings or get_settings()
    if not s.bank_fingerprint_key:
        raise EncryptionError("fingerprint key is not configured")
    key = _b64decode_key_min(s.bank_fingerprint_key)
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _b64decode_key_min(raw: str) -> bytes:
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EncryptionError("fingerprint key is not valid base64") from exc
    if len(key) < 32:
        raise EncryptionError("fingerprint key must be at least 32 bytes")
    return key
