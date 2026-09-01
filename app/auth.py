from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from app.constants import UserRole
from app.models import User


def get_session(request: Request) -> Session:
    with Session(request.app.state.db.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def require_user(request: Request, session: SessionDep) -> User:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    user = session.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


CurrentUser = Annotated[User, Depends(require_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentAdmin = Annotated[User, Depends(require_admin)]
