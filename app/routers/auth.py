from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.services import auth_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201, summary="Register a user or merchant")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = auth_service.register_user(db, payload)
    return auth_service.user_out(db, user)


@router.post("/login", response_model=TokenOut, summary="Log in and receive a 30 minute JWT")
def login(payload: LoginRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    token = auth_service.login_user(db, payload)
    commit_and_dispatch(db, background_tasks)  # sends the login alert e-mail after the response
    return token


@router.get("/me", response_model=UserOut, summary="Current user profile")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return auth_service.user_out(db, user)
