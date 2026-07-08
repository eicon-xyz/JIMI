"""
HAJIMI Auth API 路由

用户注册、登录、Token 刷新、登出。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from server.database.repository import (
    RefreshTokenRepository,
    UserRepository,
)
from server.models.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from server.services.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    refresh_token_expires_at,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


# ────────────────────────── 辅助 ──────────────────────────


def _token_pair_response(user_id: str, username: str, role: str) -> dict:
    """Generate access + refresh token pair and persist refresh token."""
    access_token = create_access_token(user_id, username, role)
    refresh_raw = create_refresh_token()
    refresh_hash = hash_token(refresh_raw)
    expires_at = refresh_token_expires_at()

    RefreshTokenRepository.create(
        user_id=user_id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )

    # Clean up expired tokens for this user
    RefreshTokenRepository.cleanup_expired(user_id)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_raw,
            "token_type": "Bearer",
            "expires_in": 1800,  # 30 minutes in seconds
            "user": {
                "user_id": user_id,
                "username": username,
                "role": role,
            },
        },
    }


# ────────────────────────── 注册 ──────────────────────────


@router.post("/register", summary="用户注册")
async def register(body: RegisterRequest):
    """注册新用户（role=user）"""
    existing = UserRepository.get_by_username(body.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": {
                    "code": "USERNAME_TAKEN",
                    "message": f"用户名 '{body.username}' 已被占用",
                },
            },
        )

    password_hash = hash_password(body.password)
    user = UserRepository.create(
        username=body.username,
        password_hash=password_hash,
        role="user",
    )

    return {
        "success": True,
        "data": {
            "user_id": user.user_id,
            "username": user.username,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }


# ────────────────────────── 登录 ──────────────────────────


@router.post("/login", summary="用户登录")
async def login(body: LoginRequest):
    """用户名 + 密码登录，返回 JWT token pair"""
    user = UserRepository.get_by_username(body.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "用户名或密码错误",
                },
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error": {
                    "code": "USER_DISABLED",
                    "message": "账号已被禁用",
                },
            },
        )

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "用户名或密码错误",
                },
            },
        )

    # Extract values before the session closes to avoid ORM detach
    user_id = user.user_id
    username = user.username
    role = user.role

    # Update last_login_at in a separate session
    from server.database import SessionLocal
    from server.database.models import User as UserModel

    db = SessionLocal()
    try:
        db.query(UserModel).filter(UserModel.user_id == user_id).update(
            {"last_login_at": datetime.now(timezone.utc)}
        )
        db.commit()
    finally:
        db.close()

    return _token_pair_response(user_id, username, role)


# ────────────────────────── 刷新 ──────────────────────────


@router.post("/refresh", summary="刷新 Token")
async def refresh(body: RefreshRequest):
    """用 refresh_token 换取新的 token pair（rotation）"""
    token_hash = hash_token(body.refresh_token)
    rt = RefreshTokenRepository.get_by_hash(token_hash)

    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "无效的 refresh_token",
                },
            },
        )

    if rt.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": {
                    "code": "TOKEN_REVOKED",
                    "message": "Token 已被撤销，请重新登录",
                },
            },
        )

    if rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": {
                    "code": "TOKEN_EXPIRED",
                    "message": "Token 已过期，请重新登录",
                },
            },
        )

    # Rotation: revoke old token
    RefreshTokenRepository.revoke(token_hash)

    # Get the user
    user = UserRepository.get_by_id(rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error": {
                    "code": "USER_DISABLED",
                    "message": "账号不存在或已被禁用",
                },
            },
        )

    return _token_pair_response(user.user_id, user.username, user.role)


# ────────────────────────── 登出 ──────────────────────────


@router.post("/logout", summary="登出")
async def logout(body: LogoutRequest):
    """撤销 refresh_token"""
    token_hash = hash_token(body.refresh_token)
    RefreshTokenRepository.revoke(token_hash)

    return {
        "success": True,
        "data": {
            "message": "已登出",
        },
    }
