"""
HAJIMI Admin API 路由

管理控制台接口：统计总览、配置管理、失败归因、红线统计
对应 a-c-api-contract.md 中的 /api/admin/* 端点
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.config import settings
from server.database.repository import (
    ConfigRepository,
    RedlineRepository,
    TaskRepository,
    UserRepository,
)
from server.models.schemas import ResetPasswordRequest
from server.services.auth import decode_access_token
from server.services.metrics import metrics

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ────────────────────────── 认证 ──────────────────────────


def verify_admin_key(x_admin_key: Optional[str] = Header(None)) -> str:
    """管理端认证（Demo 阶段与 demo key 相同）"""
    if not x_admin_key or x_admin_key != settings.DEMO_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "AUTH_FAILED",
                    "message": "X-Admin-Key 无效",
                    "details": {},
                }
            },
        )
    return x_admin_key


# Bearer token scheme (optional — we allow either header)
_bearer_scheme = HTTPBearer(auto_error=False)


def verify_admin_or_jwt(
    x_admin_key: Optional[str] = Header(None),
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """Dual-auth: accept X-Admin-Key OR Bearer JWT (role=admin)."""
    # Try demo key first
    if x_admin_key and x_admin_key == settings.DEMO_KEY:
        return {"auth_method": "demo_key"}

    # Try JWT
    if bearer and bearer.credentials:
        payload = decode_access_token(bearer.credentials)
        if payload and payload.get("role") == "admin":
            return {"auth_method": "jwt", "user_id": payload["sub"], "role": payload["role"]}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": "AUTH_FAILED",
                "message": "需要 X-Admin-Key 或管理员 JWT 认证",
                "details": {},
            }
        },
    )


# ────────────────────────── 统计总览 ──────────────────────────


@router.get(
    "/stats/overview",
    summary="仪表盘 KPI 总览",
    description="返回事务总量、成功率、L2/L3 占比等核心指标",
)
async def stats_overview(admin_key: str = Depends(verify_admin_key)):
    stats = TaskRepository.get_stats_overview()
    redline_stats = RedlineRepository.get_stats()
    stats.update(redline_stats)
    return stats


@router.get(
    "/stats/top-tasks",
    summary="高频任务 TOP 10",
)
async def stats_top_tasks(
    limit: int = 10,
    admin_key: str = Depends(verify_admin_key),
):
    from sqlalchemy import func

    from server.database import SessionLocal
    from server.database.models import Transaction

    db = SessionLocal()
    try:
        rows = (
            db.query(
                Transaction.intent_summary,
                func.count(Transaction.task_id).label("cnt"),
            )
            .group_by(Transaction.intent_summary)
            .order_by(func.count(Transaction.task_id).desc())
            .limit(limit)
            .all()
        )
        return {"top_tasks": [{"summary": r[0], "count": r[1]} for r in rows]}
    finally:
        db.close()


@router.get(
    "/stats/trend",
    summary="24h 事务趋势",
)
async def stats_trend(admin_key: str = Depends(verify_admin_key)):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from server.database import SessionLocal
    from server.database.models import Transaction

    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = (
            db.query(
                func.strftime("%H", Transaction.timestamp).label("hour"),
                func.count(Transaction.task_id).label("cnt"),
            )
            .filter(Transaction.timestamp >= since)
            .group_by("hour")
            .order_by("hour")
            .all()
        )
        return {"trend": [{"hour": r[0], "count": r[1]} for r in rows]}
    finally:
        db.close()


# ────────────────────────── 红线统计 ──────────────────────────


@router.get(
    "/stats/redline",
    summary="红线拦截统计",
)
async def stats_redline(admin_key: str = Depends(verify_admin_key)):
    return RedlineRepository.get_stats()


# ────────────────────────── 失败归因 ──────────────────────────


@router.get(
    "/failures/list",
    summary="失败记录列表",
)
async def failures_list(
    limit: int = 20,
    offset: int = 0,
    admin_key: str = Depends(verify_admin_key),
):
    from server.database import SessionLocal
    from server.database.models import Failure

    db = SessionLocal()
    try:
        total = db.query(Failure).count()
        rows = (
            db.query(Failure)
            .order_by(Failure.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "total": total,
            "items": [
                {
                    "failure_id": f.failure_id,
                    "task_id": f.task_id,
                    "failure_type": f.failure_type,
                    "step_index": f.step_index,
                    "error_detail": f.error_detail,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in rows
            ],
        }
    finally:
        db.close()


@router.get(
    "/failures/detail/{task_id}",
    summary="单条失败详情",
)
async def failure_detail(
    task_id: str,
    admin_key: str = Depends(verify_admin_key),
):
    from server.database import SessionLocal
    from server.database.models import Failure

    db = SessionLocal()
    try:
        f = db.query(Failure).filter(Failure.task_id == task_id).first()
        if not f:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": "记录不存在"}},
            )
        return {
            "failure_id": f.failure_id,
            "task_id": f.task_id,
            "failure_type": f.failure_type,
            "step_index": f.step_index,
            "fingerprint_hash": f.fingerprint_hash,
            "llm_snapshot": f.llm_snapshot,
            "error_detail": f.error_detail,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
    finally:
        db.close()


# ────────────────────────── 配置管理 ──────────────────────────


@router.get(
    "/config/current",
    summary="获取全部系统配置",
)
async def config_current(admin_key: str = Depends(verify_admin_key)):
    return {"configs": ConfigRepository.get_all()}


@router.post(
    "/config/deploy",
    summary="热部署配置",
)
async def config_deploy(
    key: str,
    value: dict,
    description: Optional[str] = None,
    admin_key: str = Depends(verify_admin_key),
):
    config = ConfigRepository.set(key, value, description)
    return {
        "deployed": True,
        "config_key": config.config_key,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


# ────────────────────────── 反馈统计 ──────────────────────────


@router.get(
    "/stats/feedback",
    summary="用户反馈分布",
)
async def stats_feedback(admin_key: str = Depends(verify_admin_key)):
    from sqlalchemy import func

    from server.database import SessionLocal
    from server.database.models import Feedback

    db = SessionLocal()
    try:
        rows = (
            db.query(
                Feedback.feedback_type,
                func.count(Feedback.feedback_id).label("cnt"),
            )
            .group_by(Feedback.feedback_type)
            .all()
        )
        return {"feedback_distribution": {r[0]: r[1] for r in rows}}
    finally:
        db.close()


# ────────────────────────── 性能指标 ──────────────────────────


@router.get(
    "/metrics",
    summary="性能指标",
    description="返回内存中收集的 P95/P50/平均延迟等性能指标。",
)
async def get_metrics(admin_key: str = Depends(verify_admin_key)):
    """Return performance metrics collected in-memory."""
    return {"metrics": metrics.get_all()}


@router.post(
    "/metrics/reset",
    summary="重置性能指标",
)
async def reset_metrics(admin_key: str = Depends(verify_admin_key)):
    """Reset all performance metrics."""
    metrics.reset()
    return {"reset": True}


# ────────────────────────── 会话状态 ──────────────────────────


@router.get(
    "/session/status",
    summary="当前会话状态",
    description="返回当前编排器会话的状态。",
)
async def session_status(admin_key: str = Depends(verify_admin_key)):
    """Return current orchestrator session state."""
    from server.services.agent.orchestrator import orchestrator

    return {"session": orchestrator.get_session()}


# ═══════════════════════════════════════════════════════════════════
# 用户管理（新增）
# ═══════════════════════════════════════════════════════════════════

from server.services.auth import hash_password


@router.get(
    "/users/list",
    summary="用户列表",
    description="分页查询用户列表，支持用户名搜索。需管理员权限。",
)
async def users_list(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    auth: dict = Depends(verify_admin_or_jwt),
):
    """获取用户列表，含任务数量和最后登录时间。"""
    from server.database import SessionLocal
    from server.database.models import Transaction

    total, users = UserRepository.list_users(
        page=page,
        page_size=page_size,
        search=search,
    )

    # Collect task counts per user in one pass
    db = SessionLocal()
    try:
        from sqlalchemy import func

        items = []
        for u in users:
            task_count = (
                db.query(func.count(Transaction.task_id))
                .filter(Transaction.user_id == u.user_id)
                .scalar()
            ) or 0
            items.append({
                "user_id": u.user_id,
                "username": u.username,
                "role": u.role,
                "is_active": u.is_active,
                "task_count": task_count,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            })
    finally:
        db.close()

    return {
        "success": True,
        "data": {
            "total": total,
            "items": items,
        },
    }


@router.get(
    "/users/stats/{user_id}",
    summary="用户任务统计",
    description="获取指定用户的任务统计信息。需管理员权限。",
)
async def users_stats(
    user_id: str,
    auth: dict = Depends(verify_admin_or_jwt),
):
    """获取单用户的任务量、成功率、反馈等统计。"""
    user = UserRepository.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "USER_NOT_FOUND",
                    "message": "用户不存在",
                },
            },
        )

    stats = UserRepository.get_user_stats(user_id)
    stats["user_id"] = user.user_id
    stats["username"] = user.username

    return {
        "success": True,
        "data": stats,
    }


@router.post(
    "/users/reset-password",
    summary="重置用户密码",
    description="管理员重置指定用户的密码。需管理员权限。",
)
async def users_reset_password(
    body: ResetPasswordRequest,
    auth: dict = Depends(verify_admin_or_jwt),
):
    """管理员重置用户密码。"""
    # Prevent admin from resetting their own password via this endpoint
    if auth.get("user_id") == body.user_id:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "CANNOT_DELETE_SELF",
                    "message": "不能通过此接口重置自己的密码",
                },
            },
        )

    new_hash = hash_password(body.new_password)
    ok = UserRepository.update_password(body.user_id, new_hash)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "USER_NOT_FOUND",
                    "message": "用户不存在",
                },
            },
        )

    return {
        "success": True,
        "data": {
            "message": "密码已重置",
        },
    }


@router.delete(
    "/users/{user_id}",
    summary="删除用户",
    description="删除指定用户，其历史任务和反馈数据的 user_id 将被置空。需管理员权限。",
)
async def users_delete(
    user_id: str,
    auth: dict = Depends(verify_admin_or_jwt),
):
    """删除用户，历史数据保留但 user_id 置 NULL。"""
    # Prevent self-delete
    if auth.get("user_id") == user_id:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "CANNOT_DELETE_SELF",
                    "message": "不能删除自己",
                },
            },
        )

    ok = UserRepository.delete_user(user_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "USER_NOT_FOUND",
                    "message": "用户不存在",
                },
            },
        )

    return {
        "success": True,
        "data": {
            "message": "用户已删除",
        },
    }
