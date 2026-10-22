import base64

import pytest

from app.core.encryption import (
    AesGcmKeyringEncryptor,
    EncryptionError,
    parse_keyring,
)

K1 = base64.b64encode(b"a" * 32).decode()
K2 = base64.b64encode(b"b" * 32).decode()


def enc(active="k1", raw=None):
    return AesGcmKeyringEncryptor(parse_keyring(raw or f"k1:{K1},k2:{K2}", active))


def test_roundtrip_and_format():
    e = enc()
    token = e.encrypt("123456789012", context="ctx")
    assert token.startswith("v1:k1:") and "123456789012" not in token
    assert e.decrypt(token, context="ctx") == "123456789012"


def test_nonce_is_random():
    e = enc()
    assert e.encrypt("same", context="c") != e.encrypt("same", context="c")


def test_wrong_context_and_tampering_fail():
    e = enc()
    token = e.encrypt("secret", context="a")
    with pytest.raises(EncryptionError):
        e.decrypt(token, context="b")
    with pytest.raises(EncryptionError):
        e.decrypt(token[:-4] + "AAAA", context="a")
    with pytest.raises(EncryptionError):
        e.decrypt("garbage", context="a")


def test_old_key_still_decrypts_after_rotation():
    old = enc("k1").encrypt("secret", context="c")
    assert enc("k2").decrypt(old, context="c") == "secret"


def test_unknown_key_id_fails():
    token = enc("k2").encrypt("secret", context="c")
    only_k1 = AesGcmKeyringEncryptor(parse_keyring(f"k1:{K1}", "k1"))
    with pytest.raises(EncryptionError):
        only_k1.decrypt(token, context="c")


@pytest.mark.parametrize(
    "raw,active",
    [
        (None, None),
        ("", "k1"),
        (f"k1:{K1}", None),
        (f"k1:{K1}", "k2"),
        ("k1:not-base64!!", "k1"),
        (f"k1:{base64.b64encode(b'short').decode()}", "k1"),
        (f"k1:{K1},k1:{K2}", "k1"),
        (f"nocolon", "k1"),
    ],
)
def test_bad_keyrings_fail_closed(raw, active):
    with pytest.raises(EncryptionError):
        parse_keyring(raw, active)
