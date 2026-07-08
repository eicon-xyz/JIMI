"""
HAJIMI 数据仓库层

提供高层 CRUD 操作，供路由和服务层调用。
"""

from datetime import datetime, timezone
from typing import Optional

import hashlib
import secrets

from sqlalchemy.orm import Session

from server.database import SessionLocal
from server.database.models import (
    Failure,
    Feedback,
    Memory,
    RedlineLog,
    RefreshToken,
    StepLog,
    SystemConfig,
    Transaction,
    User,
)
from server.models.schemas import ProcessResponse


class TaskRepository:
    """任务事务仓库"""

    @staticmethod
    def create_from_response(
        response: ProcessResponse,
        query: str,
        db: Optional[Session] = None,
    ) -> Transaction:
        """从 ProcessResponse 创建事务记录"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            txn = Transaction(
                task_id=response.task_id,
                intent_category=response.intent.category,
                user_query=query,
                intent_summary=response.intent.summary,
                reference_type=response.intent.reference_type,
                plan_type=(
                    response.detection_meta.get("route", "L3")
                    if response.detection_meta
                    else "L3"
                ),
                complexity_score=(
                    response.detection_meta.get("complexity", 0)
                    if response.detection_meta
                    else 0
                ),
                blueprint_json={
                    "name": response.blueprint.name,
                    "total_steps": response.blueprint.total_steps,
                    "state": response.blueprint.state,
                },
                element_count=(
                    response.detection_meta.get("element_count")
                    if response.detection_meta
                    else None
                ),
                detection_latency_ms=(
                    response.detection_meta.get("latency_ms")
                    if response.detection_meta
                    else None
                ),
                redline_triggered=False,
                redline_category=None,
                result=None,
                clarification_count=1 if response.intent.needs_clarification else 0,
            )

            # 记录步骤日志
            for step in response.steps:
                action_text = getattr(step, "action", None) or step.instruction
                step_log = StepLog(
                    task_id=response.task_id,
                    step_index=step.step_index,
                    action=action_text,
                    target_element_id=getattr(step, "target_element_id", None),
                    target_bbox=(
                        getattr(step, "target_bbox", None)
                        if hasattr(step, "target_bbox")
                        else None
                    ),
                    status=step.status,
                )
                db.add(step_log)

            db.add(txn)
            db.commit()
            db.refresh(txn)
            return txn
        finally:
            if close_db:
                db.close()

    @staticmethod
    def update_result(
        task_id: str,
        result: str,
        duration_ms: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> None:
        """更新任务结果"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            txn = db.query(Transaction).filter(Transaction.task_id == task_id).first()
            if txn:
                txn.result = result
                if duration_ms is not None:
                    txn.duration_ms = duration_ms
                db.commit()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_stats_overview(db: Optional[Session] = None) -> dict:
        """获取仪表盘总览统计"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            total = db.query(Transaction).count()
            success_count = (
                db.query(Transaction).filter(Transaction.result == "success").count()
            )
            fail_count = (
                db.query(Transaction).filter(Transaction.result == "fail").count()
            )
            rejected_count = (
                db.query(Transaction).filter(Transaction.result == "rejected").count()
            )
            l2_count = (
                db.query(Transaction).filter(Transaction.plan_type == "L2").count()
            )
            l3_count = (
                db.query(Transaction).filter(Transaction.plan_type == "L3").count()
            )

            return {
                "total_transactions": total,
                "success_count": success_count,
                "fail_count": fail_count,
                "rejected_count": rejected_count,
                "success_rate": round(success_count / total, 3) if total > 0 else 0.0,
                "l2_count": l2_count,
                "l3_count": l3_count,
                "l2_ratio": round(l2_count / total, 3) if total > 0 else 0.0,
            }
        finally:
            if close_db:
                db.close()


class RedlineRepository:
    """红线拦截日志仓库"""

    @staticmethod
    def log(
        query: str,
        category: str,
        action: str,
        message: str,
        db: Optional[Session] = None,
    ) -> RedlineLog:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            log_entry = RedlineLog(
                query=query,
                category=category,
                action=action,
                message=message,
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            return log_entry
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_stats(db: Optional[Session] = None) -> dict:
        """红线拦截统计"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            from sqlalchemy import func

            total = db.query(RedlineLog).count()
            by_category = (
                db.query(RedlineLog.category, func.count(RedlineLog.log_id))
                .group_by(RedlineLog.category)
                .all()
            )
            return {
                "total_redlines": total,
                "by_category": {cat: cnt for cat, cnt in by_category},
            }
        finally:
            if close_db:
                db.close()


class FeedbackRepository:
    """用户反馈仓库"""

    @staticmethod
    def create(
        task_id: str,
        feedback_type: str,
        comment: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Feedback:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            fb = Feedback(
                task_id=task_id,
                feedback_type=feedback_type,
                comment=comment,
            )
            db.add(fb)
            db.commit()
            db.refresh(fb)
            return fb
        finally:
            if close_db:
                db.close()


class FailureRepository:
    """失败记录仓库"""

    @staticmethod
    def create(
        task_id: str,
        failure_type: str,
        step_index: Optional[int] = None,
        fingerprint_hash: Optional[str] = None,
        llm_snapshot: Optional[str] = None,
        error_detail: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Failure:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            f = Failure(
                task_id=task_id,
                failure_type=failure_type,
                step_index=step_index,
                fingerprint_hash=fingerprint_hash,
                llm_snapshot=llm_snapshot,
                error_detail=error_detail,
            )
            db.add(f)
            db.commit()
            db.refresh(f)
            return f
        finally:
            if close_db:
                db.close()


class MemoryRepository:
    """用户记忆仓库"""

    @staticmethod
    def create(
        user_id: str,
        memory_type: str,
        trigger_query: str,
        summary: str,
        embedding_bytes: Optional[bytes] = None,
        category: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Memory:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            m = Memory(
                user_id=user_id,
                memory_type=memory_type,
                category=category,
                trigger_query=trigger_query,
                summary=summary,
                embedding=embedding_bytes,
            )
            db.add(m)
            db.commit()
            db.refresh(m)
            return m
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_active_by_user(
        user_id: str,
        db: Optional[Session] = None,
    ) -> list:
        """Get all is_active=True memories for a user."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            return (
                db.query(Memory)
                .filter(
                    Memory.user_id == user_id,
                    Memory.is_active == True,
                )
                .all()
            )
        finally:
            if close_db:
                db.close()

    @staticmethod
    def deactivate(
        memory_id: str,
        db: Optional[Session] = None,
    ) -> None:
        """Mark a memory as inactive (covered by newer memory)."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            db.query(Memory).filter(Memory.memory_id == memory_id).update(
                {"is_active": False}
            )
            db.commit()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def increment_resolved(
        memory_id: str,
        db: Optional[Session] = None,
    ) -> None:
        """Increment resolved_count for a failure_lesson. Deactivates if >= 1."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            mem = db.query(Memory).filter(Memory.memory_id == memory_id).first()
            if mem:
                mem.resolved_count += 1
                if mem.resolved_count >= 1:
                    mem.is_active = False
                db.commit()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_by_user_and_type(
        user_id: str,
        memory_type: str,
        is_active: Optional[bool] = True,
        db: Optional[Session] = None,
    ) -> list:
        """Get memories filtered by user, type, and active status."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            q = db.query(Memory).filter(
                Memory.user_id == user_id,
                Memory.memory_type == memory_type,
            )
            if is_active is not None:
                q = q.filter(Memory.is_active == is_active)
            return q.all()
        finally:
            if close_db:
                db.close()


class ConfigRepository:
    """系统配置仓库"""

    @staticmethod
    def get_all(db: Optional[Session] = None) -> dict:
        """获取全部配置"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            configs = db.query(SystemConfig).all()
            return {c.config_key: c.config_value for c in configs}
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get(key: str, db: Optional[Session] = None) -> Optional[dict]:
        """获取单个配置"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            config = (
                db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
            )
            return config.config_value if config else None
        finally:
            if close_db:
                db.close()

    @staticmethod
    def set(
        key: str,
        value: dict,
        description: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> SystemConfig:
        """设置或更新配置"""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            config = (
                db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
            )
            if config:
                config.config_value = value
                config.updated_at = datetime.now(timezone.utc)
                if description:
                    config.description = description
            else:
                config = SystemConfig(
                    config_key=key,
                    config_value=value,
                    description=description,
                )
                db.add(config)
            db.commit()
            db.refresh(config)
            return config
        finally:
            if close_db:
                db.close()


class UserRepository:
    """用户管理仓库"""

    @staticmethod
    def create(
        username: str,
        password_hash: str,
        role: str = "user",
        db: Optional[Session] = None,
    ) -> User:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            user = User(
                username=username,
                password_hash=password_hash,
                role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_by_username(
        username: str,
        db: Optional[Session] = None,
    ) -> Optional[User]:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            return db.query(User).filter(User.username == username).first()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_by_id(
        user_id: str,
        db: Optional[Session] = None,
    ) -> Optional[User]:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            return db.query(User).filter(User.user_id == user_id).first()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def list_users(
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> tuple[int, list[User]]:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            from sqlalchemy import func

            q = db.query(User)
            if search:
                q = q.filter(User.username.contains(search))
            total = q.count()
            users = (
                q.order_by(User.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return total, users
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_user_stats(
        user_id: str,
        db: Optional[Session] = None,
    ) -> dict:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            from sqlalchemy import func

            total_tasks = (
                db.query(func.count(Transaction.task_id))
                .filter(Transaction.user_id == user_id)
                .scalar()
            ) or 0
            success_count = (
                db.query(func.count(Transaction.task_id))
                .filter(Transaction.user_id == user_id, Transaction.result == "success")
                .scalar()
            ) or 0
            fail_count = (
                db.query(func.count(Transaction.task_id))
                .filter(Transaction.user_id == user_id, Transaction.result == "fail")
                .scalar()
            ) or 0
            feedback_count = (
                db.query(func.count(Feedback.feedback_id))
                .filter(Feedback.user_id == user_id)
                .scalar()
            ) or 0
            last_txn = (
                db.query(Transaction.timestamp)
                .filter(Transaction.user_id == user_id)
                .order_by(Transaction.timestamp.desc())
                .first()
            )

            return {
                "total_tasks": total_tasks,
                "success_count": success_count,
                "success_rate": round(success_count / total_tasks, 3) if total_tasks > 0 else 0.0,
                "total_failures": fail_count,
                "total_feedback": feedback_count,
                "last_active_at": last_txn[0].isoformat() if last_txn and last_txn[0] else None,
            }
        finally:
            if close_db:
                db.close()

    @staticmethod
    def update_password(
        user_id: str,
        new_password_hash: str,
        db: Optional[Session] = None,
    ) -> bool:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False
            user.password_hash = new_password_hash
            db.commit()
            return True
        finally:
            if close_db:
                db.close()

    @staticmethod
    def delete_user(
        user_id: str,
        db: Optional[Session] = None,
    ) -> bool:
        """Delete user, set their transactions/feedback user_id to NULL."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False
            # Nullify foreign keys in transactions and feedback
            db.query(Transaction).filter(Transaction.user_id == user_id).update(
                {Transaction.user_id: None}
            )
            db.query(Feedback).filter(Feedback.user_id == user_id).update(
                {Feedback.user_id: None}
            )
            db.delete(user)
            db.commit()
            return True
        finally:
            if close_db:
                db.close()


class RefreshTokenRepository:
    """Refresh Token 仓库"""

    @staticmethod
    def create(
        user_id: str,
        token_hash: str,
        expires_at,
        db: Optional[Session] = None,
    ) -> RefreshToken:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            rt = RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            db.add(rt)
            db.commit()
            db.refresh(rt)
            return rt
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_by_hash(
        token_hash: str,
        db: Optional[Session] = None,
    ) -> Optional[RefreshToken]:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            return (
                db.query(RefreshToken)
                .filter(RefreshToken.token_hash == token_hash)
                .first()
            )
        finally:
            if close_db:
                db.close()

    @staticmethod
    def revoke(
        token_hash: str,
        db: Optional[Session] = None,
    ) -> bool:
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            rt = (
                db.query(RefreshToken)
                .filter(RefreshToken.token_hash == token_hash)
                .first()
            )
            if not rt:
                return False
            rt.revoked_at = datetime.now(timezone.utc)
            db.commit()
            return True
        finally:
            if close_db:
                db.close()

    @staticmethod
    def cleanup_expired(
        user_id: str,
        db: Optional[Session] = None,
    ) -> int:
        """Delete all expired refresh tokens for a user. Returns count deleted."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            count = (
                db.query(RefreshToken)
                .filter(
                    RefreshToken.user_id == user_id,
                    RefreshToken.expires_at < datetime.now(timezone.utc),
                )
                .delete()
            )
            db.commit()
            return count
        finally:
            if close_db:
                db.close()
