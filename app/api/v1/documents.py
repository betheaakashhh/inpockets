from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentVersionListResponse,
)
from app.services.document import DocumentService


router = APIRouter()


def get_document_service(
    session: AsyncSession = Depends(get_db_session),
) -> DocumentService:
    return DocumentService(session)


@router.get("", response_model=DocumentListResponse)
async def list_customer_documents(
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    documents = await service.list_documents(
        owner_type="USER",
        owner_id=current_user.id,
    )

    return DocumentListResponse(
        items=[
            DocumentResponse.model_validate(document)
            for document in documents
        ]
    )


@router.get(
    "/family/{document_family_id}/versions",
    response_model=DocumentVersionListResponse,
)
async def list_document_versions(
    document_family_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentVersionListResponse:
    versions = await service.list_versions(
        document_family_id=document_family_id,
    )

    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document family not found",
        )

    first_version = versions[0]

    if (
        first_version.owner_type != "USER"
        or first_version.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document family not found",
        )

    return DocumentVersionListResponse(
        document_family_id=document_family_id,
        items=[
            DocumentResponse.model_validate(document)
            for document in versions
        ],
    )


@router.post(
    "/family/{document_family_id}/versions",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_version(
    document_family_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    versions = await service.list_versions(
        document_family_id=document_family_id,
    )

    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document family not found",
        )

    latest = versions[-1]

    if (
        latest.owner_type != "USER"
        or latest.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document family not found",
        )

    content = await file.read()

    try:
        document = await service.create_document_version(
            document_family_id=document_family_id,
            content=content,
            content_type=file.content_type or "",
            immutable=False,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> Response:
    try:
        document, content = await service.get_document_for_owner(
            document_id=document_id,
            owner_type="USER",
            owner_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return Response(
        content=content.content,
        media_type=document.content_type,
    )