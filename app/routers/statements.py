from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.services import statement_service

router = APIRouter(prefix="/statements", tags=["Statements"])


@router.get("", summary="Monthly statement as a password-protected PDF or CSV")
def get_statement(
    month: str = Query(..., description="YYYY-MM, e.g. 2026-10"),
    fmt: str = Query("pdf", alias="format", description="pdf or csv"),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    path, media_type, filename, headers = statement_service.build_statement(db, user, month, fmt)
    return FileResponse(path, media_type=media_type, filename=filename, headers=headers)
