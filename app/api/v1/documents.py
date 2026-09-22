from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, Response, status
from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.document import DocumentListResponse, DocumentResponse
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