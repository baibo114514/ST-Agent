from __future__ import annotations


from unittest.mock import AsyncMock
import pytest
from types import SimpleNamespace

from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from fastapi import HTTPException
from app.api.v1 import auth as auth_api
from app.models.user import User
from app.schemas.auth import UserCreate
from app.utils import auth as auth_utils
from app.utils.sanitization import sanitize_email
from conftest import run_async


VALID_EMAIL = "user01@example.com"
MIXED_CASE_EMAIL = "User01@Example.com"
VALID_PASSWORD = "Valid@123"


def make_user(user_id: int = 1, email: str = VALID_EMAIL, password: str = VALID_PASSWORD) -> User:
    return User(id=user_id, email=email, hashed_password=User.hash_password(password))


def credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_st_auth_001_register_valid_user(monkeypatch):
    user = make_user()
    monkeypatch.setattr(auth_api.database_service,
                        "get_user_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(auth_api.database_service,
                        "create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(auth_api.settings, "PLATFORM_ADMIN_EMAILS", [])

    response = run_async(auth_api.register(
        UserCreate(email=VALID_EMAIL, password=VALID_PASSWORD)))

    assert response.id == 1
    assert response.email == VALID_EMAIL
    assert response.token.token_type == "bearer"
    assert auth_utils.verify_token(response.token.access_token) == "1"
    assert response.is_admin is False
    assert user.hashed_password != VALID_PASSWORD
    assert user.verify_password(VALID_PASSWORD)


def test_st_auth_002_reject_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password=VALID_PASSWORD)


def test_st_auth_003_reject_password_shorter_than_eight():
    with pytest.raises(ValidationError):
        UserCreate(email=VALID_EMAIL, password="Aa1@abc")


def test_st_auth_004_reject_password_longer_than_sixty_four():
    password = "Aa1@" + "x" * 61
    assert len(password) == 65
    with pytest.raises(ValidationError):
        UserCreate(email=VALID_EMAIL, password=password)


def test_st_auth_005_reject_password_without_uppercase():
    with pytest.raises(ValidationError, match="uppercase"):
        UserCreate(email=VALID_EMAIL, password="valid@123")


def test_st_auth_006_reject_password_without_lowercase():
    with pytest.raises(ValidationError, match="lowercase"):
        UserCreate(email=VALID_EMAIL, password="VALID@123")


def test_st_auth_007_reject_password_without_number():
    with pytest.raises(ValidationError, match="number"):
        UserCreate(email=VALID_EMAIL, password="Valid@Test")


def test_st_auth_008_reject_password_without_special_character():
    with pytest.raises(ValidationError, match="special"):
        UserCreate(email=VALID_EMAIL, password="Valid1234")


def test_st_auth_009_reject_duplicate_email(monkeypatch):
    monkeypatch.setattr(auth_api.database_service,
                        "get_user_by_email", AsyncMock(return_value=make_user()))
    create_mock = AsyncMock()
    monkeypatch.setattr(auth_api.database_service, "create_user", create_mock)

    with pytest.raises(HTTPException) as exc_info:
        run_async(auth_api.register(UserCreate(
            email=VALID_EMAIL, password=VALID_PASSWORD)))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Email already registered"
    create_mock.assert_not_awaited()


def test_st_auth_010_login_with_correct_credentials(monkeypatch):
    monkeypatch.setattr(auth_api.database_service,
                        "get_user_by_email", AsyncMock(return_value=make_user()))
    monkeypatch.setattr(auth_api.settings, "PLATFORM_ADMIN_EMAILS", [])
    form = SimpleNamespace(username=VALID_EMAIL, password=VALID_PASSWORD)

    response = run_async(auth_api.login(form))

    assert response.token_type == "bearer"
    assert auth_utils.verify_token(response.access_token) == "1"
    assert response.is_admin is False


def test_st_auth_011_login_unknown_email_has_generic_error(monkeypatch):
    monkeypatch.setattr(auth_api.database_service,
                        "get_user_by_email", AsyncMock(return_value=None))
    form = SimpleNamespace(username="nobody@example.com",
                           password=VALID_PASSWORD)

    with pytest.raises(HTTPException) as exc_info:
        run_async(auth_api.login(form))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Incorrect email or password"


def test_st_auth_012_login_wrong_password_has_same_generic_error(monkeypatch):
    monkeypatch.setattr(auth_api.database_service,
                        "get_user_by_email", AsyncMock(return_value=make_user()))
    form = SimpleNamespace(username=VALID_EMAIL, password="Wrong@123")

    with pytest.raises(HTTPException) as exc_info:
        run_async(auth_api.login(form))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Incorrect email or password"
