from fastapi import APIRouter, Request, Response

from app.api.dependencies import Actor, Session
from app.core.middleware import client_ip
from app.schemas.common import Data
from app.schemas.users import Login, Token, UserResponse
from app.services.auth import login
from app.services.sessions import issue, protect, refresh, revoke

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Data[Token])
async def authenticate(
    data: Login, request: Request, response: Response, session: Session
) -> Data[Token]:
    protect(request)
    user = await login(
        session,
        data,
        request.app.state.settings,
        request.app.state.limiter,
        request.app.state.dummy_hash,
        client_ip(request.scope),
    )
    return Data(data=await issue(session, user, request, response))


@router.get("/me", response_model=Data[UserResponse])
async def me(actor: Actor) -> Data[UserResponse]:
    return Data(data=UserResponse.model_validate(actor))


@router.post("/refresh", response_model=Data[Token])
async def refresh_session(request: Request, response: Response, session: Session) -> Data[Token]:
    return Data(data=await refresh(session, request, response))


@router.post("/logout", status_code=204)
async def logout(request: Request, session: Session) -> Response:
    response = Response(status_code=204)
    await revoke(session, request, response)
    return response
