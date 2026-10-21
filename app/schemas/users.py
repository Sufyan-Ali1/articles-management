from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator

from app.schemas.common import Input, Output, Role

Email = Annotated[EmailStr, Field(max_length=255)]


def password_policy(value: SecretStr) -> SecretStr:
    if not 12 <= len(value.get_secret_value()) <= 128:
        raise ValueError("Password must contain 12 to 128 characters")
    return value


class Login(Input):
    email: Email
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserCreate(Input):
    name: str = Field(min_length=1, max_length=150)
    email: Email
    password: SecretStr
    role: Role = "author"
    is_active: bool = True
    _password = field_validator("password")(password_policy)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    email: Email | None = None
    password: SecretStr | None = None
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def no_nulls(self) -> "UserUpdate":
        if any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("User fields cannot be null")
        if self.password:
            password_policy(self.password)
        if self.email:
            self.email = self.email.lower()
        return self


class UserResponse(Output):
    id: UUID
    name: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AuthorResponse(Output):
    id: UUID
    name: str


class Token(Output):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
