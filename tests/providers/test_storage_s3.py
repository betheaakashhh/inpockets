import boto3
import pytest
from moto import mock_aws

from app.core.config import get_settings
from app.providers.factory import get_document_storage
from app.providers.storage_development import DevelopmentDocumentStorage
from app.providers.storage_s3 import S3DocumentStorage, safe_key_hint

BUCKET = "inpockets-test-docs"
PDF = b"%PDF-1.7\nhello"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        yield client


def storage(s3, **kw):
    return S3DocumentStorage(bucket=BUCKET, client=s3, **kw)


async def test_round_trip_preserves_bytes_and_type(s3):
    st = storage(s3)
    stored = await st.put(PDF, "application/pdf", "kfs-v1")
    got = await st.get(stored.storage_ref)
    assert got.content == PDF and got.content_type == "application/pdf"
    assert stored.size_bytes == len(PDF)
    assert await st.exists(stored.storage_ref)


async def test_objects_are_encrypted_and_private(s3):
    stored = await storage(s3, kms_key_id=None).put(PDF, "application/pdf", "x")
    head = s3.head_object(Bucket=BUCKET, Key=stored.storage_ref)
    assert head["ServerSideEncryption"] == "AES256"
    assert head["Metadata"]["sha256"] == stored.checksum
    grants = s3.get_object_acl(Bucket=BUCKET, Key=stored.storage_ref)["Grants"]
    assert all(g["Grantee"].get("URI") is None for g in grants)  # no public/AllUsers grant


async def test_kms_key_is_used_when_configured(s3):
    st = storage(s3, kms_key_id="alias/inpockets-docs")
    stored = await st.put(PDF, "application/pdf", "x")
    head = s3.head_object(Bucket=BUCKET, Key=stored.storage_ref)
    assert head["ServerSideEncryption"] == "aws:kms"


async def test_put_is_idempotent_and_never_overwrites(s3):
    st = storage(s3)
    a = await st.put(PDF, "application/pdf", "same")
    etag = s3.head_object(Bucket=BUCKET, Key=a.storage_ref)["ETag"]
    b = await st.put(PDF, "application/pdf", "same")
    assert a == b
    assert s3.head_object(Bucket=BUCKET, Key=a.storage_ref)["ETag"] == etag


async def test_prefix_is_applied_but_ref_stays_prefix_free(s3):
    st = storage(s3, prefix="prod/docs/")
    stored = await st.put(PDF, "application/pdf", "x")
    assert "/" not in stored.storage_ref
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert keys == [f"prod/docs/{stored.storage_ref}"]
    assert (await st.get(stored.storage_ref)).content == PDF


async def test_missing_object_behaviour(s3):
    st = storage(s3)
    assert await st.exists("nope-abc") is False
    with pytest.raises(FileNotFoundError):
        await st.get("nope-abc")


async def test_delete_removes_object(s3):
    st = storage(s3)
    stored = await st.put(PDF, "application/pdf", "x")
    await st.delete(stored.storage_ref)
    assert await st.exists(stored.storage_ref) is False


@pytest.mark.parametrize("ref", ["../etc/passwd", "a/b", "a\\b", "", "x" * 500, "a..b"])
async def test_unsafe_refs_are_never_used_as_keys(s3, ref):
    st = storage(s3)
    assert await st.exists(ref) is False
    with pytest.raises(FileNotFoundError):
        await st.get(ref)


def test_hostile_key_hints_are_flattened():
    assert "/" not in safe_key_hint("../../etc/passwd")
    assert ".." not in safe_key_hint("../../etc/passwd")
    assert safe_key_hint("///") == "document"


def test_bucket_is_required():
    with pytest.raises(RuntimeError, match="BUCKET"):
        S3DocumentStorage(bucket="", client=object())


def test_factory_selects_s3_and_guards_production(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_provider", "s3")
    monkeypatch.setattr(settings, "document_storage_s3_bucket", BUCKET)
    monkeypatch.setattr(settings, "document_storage_s3_region", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    assert isinstance(get_document_storage(), S3DocumentStorage)

    monkeypatch.setattr(settings, "document_storage_provider", "development")
    assert isinstance(get_document_storage(), DevelopmentDocumentStorage)
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="not allowed in production"):
        get_document_storage()
