from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.otp as otp_service
from app.main import app
from app.models.document import Document
from app.repositories.document import DocumentRepository


client = TestClient(app)


def authenticate_test_user(
    monkeypatch,
    phone_number: str,
    otp: str = "123456",
) -> str:
    monkeypatch.setattr(
        otp_service,
        "generate_otp",
        lambda: otp,
    )

    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert response.status_code == 200

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": otp,
        },
    )

    assert response.status_code == 200

    return response.json()["access_token"]


def auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
    }


async def create_document(
    db_session: AsyncSession,
    owner_id,
    *,
    document_type: str = "IDENTITY_PROOF",
    storage_ref: str | None = None,
    checksum: str | None = None,
) -> Document:
    repository = DocumentRepository(db_session)

    return await repository.create(
        document_type=document_type,
        owner_type="USER",
        owner_id=owner_id,
        storage_ref=storage_ref or f"documents/{uuid4()}",
        checksum=checksum or uuid4().hex + "0" * 32,
        content_type="application/pdf",
        size_bytes=1024,
        version=1,
        is_immutable=True,
    )


@pytest.mark.asyncio
async def test_list_documents_requires_authentication() -> None:
    response = client.get("/api/v1/documents")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_documents_returns_empty_list_for_new_user(
    monkeypatch,
) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.get(
        "/api/v1/documents",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.asyncio
async def test_list_documents_returns_customer_documents(
    monkeypatch,
    db_session: AsyncSession,
) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_headers(token),
    )

    assert me_response.status_code == 200

    user_id = me_response.json()["id"]

    document = await create_document(
        db_session,
        user_id,
        document_type="PAN",
    )
    await db_session.commit()

    response = client.get(
        "/api/v1/documents",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data["items"]) == 1

    item = data["items"][0]

    assert item["id"] == str(document.id)
    assert item["document_type"] == "PAN"
    assert item["owner_type"] == "USER"
    assert item["owner_id"] == str(user_id)
    assert item["content_type"] == "application/pdf"
    assert item["size_bytes"] == 1024
    assert item["version"] == 1
    assert item["is_immutable"] is True
    assert "created_at" in item


@pytest.mark.asyncio
async def test_list_documents_does_not_expose_storage_details(
    monkeypatch,
    db_session: AsyncSession,
) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_headers(token),
    )

    assert me_response.status_code == 200

    user_id = me_response.json()["id"]

    await create_document(
        db_session,
        user_id,
        document_type="KYC_DOCUMENT",
        storage_ref="private/storage/ref",
        checksum="a" * 64,
    )
    await db_session.commit()

    response = client.get(
        "/api/v1/documents",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    item = response.json()["items"][0]

    assert "storage_ref" not in item
    assert "checksum" not in item


@pytest.mark.asyncio
async def test_list_documents_does_not_return_another_users_documents(
    monkeypatch,
    db_session: AsyncSession,
) -> None:
    first_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    first_me = client.get(
        "/api/v1/auth/me",
        headers=auth_headers(first_token),
    )

    assert first_me.status_code == 200

    first_user_id = first_me.json()["id"]

    await create_document(
        db_session,
        first_user_id,
        document_type="PRIVATE_DOCUMENT",
    )
    await db_session.commit()

    second_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.get(
        "/api/v1/documents",
        headers=auth_headers(second_token),
    )

    assert response.status_code == 200
    assert response.json() == {"items": []}