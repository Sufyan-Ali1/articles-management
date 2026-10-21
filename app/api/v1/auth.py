from fastapi import APIRouter, Request

from app.api.dependencies import Actor, Session
from app.core.middleware import client_ip
from app.schemas.common import Data
from app.schemas.users import Login, Token, UserResponse
from app.services.auth import login

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Data[Token])
async def authenticate(data: Login, request: Request, session: Session) -> Data[Token]:
    token = await login(
        session,
        data,
        request.app.state.settings,
        request.app.state.limiter,
        request.app.state.dummy_hash,
        client_ip(request.scope),
    )
    return Data(data=token)


@router.get("/me", response_model=Data[UserResponse])
async def me(actor: Actor) -> Data[UserResponse]:
    return Data(data=UserResponse.model_validate(actor))
