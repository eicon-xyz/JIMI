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
from server.services.auth import decode_access_token, hash_password
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


# Bearer token scheme (auto_error=False lets us handle auth errors ourselves)
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
    "/failures/stats",
    summary="失败归因统计",
    description="按失败类型分布 + 24h 趋势",
)
async def failures_stats(admin_key: str = Depends(verify_admin_key)):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from server.database import SessionLocal
    from server.database.models import Failure

    db = SessionLocal()
    try:
        # 按类型分布
        type_dist = (
            db.query(
                Failure.failure_type,
                func.count(Failure.failure_id).label("cnt"),
            )
            .group_by(Failure.failure_type)
            .all()
        )
        distribution = [
            {"type": row[0], "label": row[0], "count": row[1]}
            for row in type_dist
        ]

        # 24h 趋势
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        trend_rows = (
            db.query(
                func.strftime("%H", Failure.created_at).label("hour"),
                func.count(Failure.failure_id).label("cnt"),
            )
            .filter(Failure.created_at >= since)
            .group_by("hour")
            .order_by("hour")
            .all()
        )
        trend = [{"hour": f"{int(row[0]):02d}:00", "count": row[1]} for row in trend_rows]

        total = db.query(Failure).count()

        return {
            "success": True,
            "data": {
                "distribution": distribution,
                "trend": trend,
                "total": total,
            },
        }
    finally:
        db.close()


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


@router.get(
    "/config/deploy-logs",
    summary="部署操作日志",
)
async def config_deploy_logs(
    limit: int = 20,
    admin_key: str = Depends(verify_admin_key),
):
    """返回部署操作日志。从系统配置的更新记录构建。"""
    from server.database import SessionLocal
    from server.database.models import SystemConfig

    db = SessionLocal()
    try:
        configs = (
            db.query(SystemConfig)
            .order_by(SystemConfig.updated_at.desc())
            .limit(limit)
            .all()
        )
        logs = [
            {
                "id": i + 1,
                "operator": "admin",
                "version": c.config_key,
                "action": "deploy" if c.updated_at else "unknown",
                "timestamp": c.updated_at.isoformat() if c.updated_at else "",
                "affected": 0,
            }
            for i, c in enumerate(configs)
        ]
        return {
            "success": True,
            "data": {"logs": logs},
        }
    finally:
        db.close()


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
# 健康监控（新增）
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/monitor/health",
    summary="系统健康监控",
    description="返回服务器资源（CPU/内存/磁盘）+ 组件状态",
)
async def monitor_health(admin_key: str = Depends(verify_admin_key)):
    """采集本机资源 + 组件健康探活"""
    import time as _time

    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime_seconds = int(_time.time() - psutil.boot_time())
        uptime_str = ""
        d = uptime_seconds // 86400
        h = (uptime_seconds % 86400) // 3600
        m = (uptime_seconds % 3600) // 60
        if d:
            uptime_str += f"{d}d "
        uptime_str += f"{h}h {m}m"
    except ImportError:
        cpu_pct = 0
        mem = type("obj", (object,), {"total": 0, "used": 0, "available": 0, "percent": 0})()
        disk = type("obj", (object,), {"total": 0, "used": 0, "free": 0, "percent": 0})()
        uptime_str = "psutil 未安装"
        uptime_seconds = 0

    # 组件探活
    components = []

    # OmniParser
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.OMNIPARSER_URL}/probe/")
        omni_ready = r.status_code == 200
        omni_detail = "就绪"
    except Exception:
        omni_ready = False
        omni_detail = "不可达"
    components.append({
        "name": "OmniParser (GPU)",
        "status": "healthy" if omni_ready else "critical",
        "detail": omni_detail,
    })

    # LLM API
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(
                settings.LLM_BASE_URL.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            )
        llm_ready = r.status_code == 200
        llm_detail = "就绪"
    except Exception:
        llm_ready = False
        llm_detail = "不可达"
    components.append({
        "name": "LLM API",
        "status": "healthy" if llm_ready else "critical",
        "detail": llm_detail,
    })

    # SQLite
    try:
        from server.database import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_ready = True
        db_detail = "连接正常"
    except Exception:
        db_ready = False
        db_detail = "连接失败"
    components.append({
        "name": "SQLite",
        "status": "healthy" if db_ready else "critical",
        "detail": db_detail,
    })

    return {
        "success": True,
        "data": {
            "resources": {
                "cpu_pct": round(cpu_pct, 1),
                "memory_gb": round(mem.used / (1024**3), 1),
                "memory_total_gb": round(mem.total / (1024**3), 1),
                "memory_pct": mem.percent,
                "disk_free_gb": round(disk.free / (1024**3), 1),
                "disk_total_gb": round(disk.total / (1024**3), 1),
                "disk_pct": disk.percent,
                "uptime": uptime_str,
                "uptime_seconds": uptime_seconds,
            },
            "components": components,
        },
    }


@router.get(
    "/monitor/alerts",
    summary="告警列表",
)
async def monitor_alerts(
    admin_key: str = Depends(verify_admin_key),
):
    """返回内存中的告警列表。当前为占位实现。"""
    return {
        "success": True,
        "data": {
            "alerts": [],
            "total_unread": 0,
            "total": 0,
        },
    }


@router.post(
    "/monitor/alerts/{alert_id}/read",
    summary="标记告警已读",
)
async def monitor_alert_read(
    alert_id: str,
    admin_key: str = Depends(verify_admin_key),
):
    return {
        "success": True,
        "data": {"marked_read": 1},
    }


@router.post(
    "/monitor/alerts/read-all",
    summary="全部告警已读",
)
async def monitor_alert_read_all(admin_key: str = Depends(verify_admin_key)):
    return {
        "success": True,
        "data": {"marked_read": 99},
    }


# ═══════════════════════════════════════════════════════════════════
# 数据流监控（占位实现 — 数据采集机制待建）
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/flow/topology",
    summary="服务拓扑",
)
async def flow_topology(admin_key: str = Depends(verify_admin_key)):
    """返回硬编码的服务拓扑图（B端→A端→LLM/DB/OmmiParser）"""
    return {
        "success": True,
        "data": {
            "nodes": [
                {"id": "client", "label": "B端客户端", "type": "client", "online": True},
                {"id": "gateway", "label": "HAJIMI A端 (FastAPI)", "type": "server"},
                {"id": "sqlite", "label": "SQLite", "type": "database"},
                {"id": "llm", "label": "LLM API", "type": "external"},
                {"id": "omni", "label": "OmniParser (GPU)", "type": "external"},
            ],
            "links": [
                {"source": "client", "target": "gateway", "qps": 0, "latency_ms": 0, "status": "healthy"},
                {"source": "gateway", "target": "sqlite", "qps": 0, "latency_ms": 0, "status": "healthy"},
                {"source": "gateway", "target": "llm", "qps": 0, "latency_ms": 0, "status": "healthy"},
                {"source": "gateway", "target": "omni", "qps": 0, "latency_ms": 0, "status": "healthy"},
            ],
        },
    }


@router.get(
    "/flow/metrics",
    summary="链路指标时序",
)
async def flow_metrics(
    api_path: str = "",
    range: str = "1h",
    admin_key: str = Depends(verify_admin_key),
):
    """返回空的时序指标（采集机制待建）"""
    return {
        "success": True,
        "data": {
            "api_path": api_path or "/api/demo/process",
            "granularity": "5m",
            "data": [],
        },
    }


@router.get(
    "/flow/versions",
    summary="客户端版本分布",
)
async def flow_versions(admin_key: str = Depends(verify_admin_key)):
    """返回空的版本分布（需B端心跳机制配合）"""
    return {
        "success": True,
        "data": {
            "versions": [],
            "total_clients": 0,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 用户管理（新增）
# ═══════════════════════════════════════════════════════════════════



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

    # Collect task counts for all returned users in one query
    db = SessionLocal()
    try:
        from sqlalchemy import func

        user_ids = [u.user_id for u in users]
        counts_query = (
            db.query(
                Transaction.user_id,
                func.count(Transaction.task_id).label("cnt"),
            )
            .filter(Transaction.user_id.in_(user_ids))
            .group_by(Transaction.user_id)
            .all()
        )
        count_map = {row[0]: row[1] for row in counts_query}

        items = []
        for u in users:
            items.append({
                "user_id": u.user_id,
                "username": u.username,
                "role": u.role,
                "is_active": u.is_active,
                "task_count": count_map.get(u.user_id, 0),
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
