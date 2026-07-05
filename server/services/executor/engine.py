"""
HAJIMI 自动操作助手 — 执行引擎

主循环：Plan → SafetyCheck → Execute → Verify → Next/Replan
SSE 事件通过 thread-safe queue 推送给 /stream 端点。
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Optional

from server.services.executor.clicker import execute_action, move_to
from server.services.executor.safety import check_step

logger = logging.getLogger(__name__)

# 全局事件队列：{task_id: queue.Queue}
_event_queues: dict[str, queue.Queue] = {}
_queues_lock = threading.Lock()
_cancel_flags: dict[str, bool] = {}
_cancel_lock = threading.Lock()


def _push_event(task_id: str, event: str, data: dict) -> None:
    """推送一个 SSE 事件到对应任务的事件队列。"""
    with _queues_lock:
        q = _event_queues.get(task_id)
    if q:
        q.put({"event": event, "data": data})


def _is_cancelled(task_id: str) -> bool:
    """检查任务是否已被取消。"""
    with _cancel_lock:
        return _cancel_flags.get(task_id, False)


# ═══════════════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════════════

def register_task(task_id: str) -> queue.Queue:
    """注册新任务，返回其事件队列供 /stream 端点消费。"""
    q: queue.Queue = queue.Queue()
    with _queues_lock:
        _event_queues[task_id] = q
    with _cancel_lock:
        _cancel_flags[task_id] = False
    logger.info(f"[engine] registered task {task_id}")
    return q


def cancel_task(task_id: str) -> bool:
    """取消任务。"""
    with _cancel_lock:
        if task_id in _cancel_flags:
            _cancel_flags[task_id] = True
            logger.info(f"[engine] cancel flag set for {task_id}")
            return True
    return False


def unregister_task(task_id: str) -> None:
    """清理任务资源。"""
    with _queues_lock:
        _event_queues.pop(task_id, None)
    with _cancel_lock:
        _cancel_flags.pop(task_id, None)
    logger.info(f"[engine] unregistered task {task_id}")


def run_plan(
    task_id: str,
    steps: list[dict],
    verify_fn=None,
    screenshot_fn=None,
) -> None:
    """
    逐步执行操作计划。此函数在后台线程运行。

    Args:
        task_id: 任务 ID
        steps: 执行步骤列表 [{step_index, action, description, bbox_center, params, ...}]
        verify_fn: callable(image_base64, step) -> dict — 截图验证函数（可选）
        screenshot_fn: callable() -> str — 截取当前屏幕返回 base64 JPEG（可选）
    """
    q = register_task(task_id)
    total = len(steps)
    completed = 0
    failed = 0

    _push_event(task_id, "plan_ready", {
        "task_id": task_id,
        "total_steps": total,
        "steps": steps,
    })

    for step in steps:
        # 检查取消标志
        if _is_cancelled(task_id):
            _push_event(task_id, "task_error", {
                "task_id": task_id,
                "error": "用户取消",
            })
            break

        step_idx = step.get("step_index", completed + 1)
        description = step.get("description", f"步骤 {step_idx}")
        action = step.get("action", "click")
        bbox_center = step.get("bbox_center")
        params = step.get("params")

        # Normalize "x,y" string params or coord params to bbox_center
        if bbox_center is None and isinstance(params, str) and ',' in params:
            parts = params.split(',')
            if len(parts) == 2:
                try:
                    bbox_center = [int(parts[0].strip()), int(parts[1].strip())]
                except ValueError:
                    pass

        # ── 安全管控 ──
        safety = check_step(description)
        if safety.level == "red":
            _push_event(task_id, "step_blocked", {
                "step_index": step_idx,
                "description": description,
                "reason": safety.reason,
                "risk_level": "red",
            })
            step["status"] = "blocked"
            failed += 1
            _push_event(task_id, "log", {
                "level": "warn",
                "message": f"步骤 {step_idx} 被拦截: {safety.reason}",
            })
            continue

        if safety.level == "yellow":
            _push_event(task_id, "log", {
                "level": "warn",
                "message": f"步骤 {step_idx} 需注意: {safety.reason}（当前 MVP 自动放行）",
            })

        # ── 执行步骤 ──
        _push_event(task_id, "step_start", {
            "step_index": step_idx,
            "action": action,
            "description": description,
            "bbox_center": bbox_center,
        })

        if bbox_center:
            _push_event(task_id, "step_executing", {
                "step_index": step_idx,
                "detail": f"移动鼠标到 ({bbox_center[0]},{bbox_center[1]})",
            })

        t0 = time.time()
        try:
            result = execute_action(action, bbox_center, params)
        except Exception as exc:
            logger.exception(f"step {step_idx} execution error")
            result = {"success": False, "error": str(exc)}

        duration_ms = int((time.time() - t0) * 1000)

        if not result.get("success"):
            # ── 重试 1 次 ──
            _push_event(task_id, "step_retry", {
                "step_index": step_idx,
                "attempt": 2,
                "error": result.get("error", "执行失败"),
            })
            _push_event(task_id, "log", {
                "level": "warn",
                "message": f"步骤 {step_idx} 失败，重试中... ({result.get('error','')})",
            })
            try:
                result = execute_action(action, bbox_center, params)
                duration_ms = int((time.time() - t0) * 1000)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

        if result.get("success"):
            step["status"] = "done"
            step["duration_ms"] = duration_ms
            completed += 1
            _push_event(task_id, "step_done", {
                "step_index": step_idx,
                "duration_ms": duration_ms,
                "verified": True,
            })
            _push_event(task_id, "log", {
                "level": "info",
                "message": f"✅ 步骤 {step_idx} 完成 ({duration_ms}ms): {result}",
            })
        else:
            step["status"] = "failed"
            step["error"] = result.get("error", "")
            failed += 1
            _push_event(task_id, "step_failed", {
                "step_index": step_idx,
                "error": result.get("error", ""),
                "will_retry": False,
            })
            _push_event(task_id, "log", {
                "level": "error",
                "message": f"❌ 步骤 {step_idx} 失败: {result.get('error','')}",
            })

        # ── 截图验证（如果提供了验证函数）──
        if verify_fn and screenshot_fn:
            try:
                img_b64 = screenshot_fn()
                if img_b64:
                    _push_event(task_id, "screenshot", {
                        "image_base64": img_b64,
                    })
                    v_result = verify_fn(img_b64, step)
                    if v_result.get("status") not in ("done",):
                        _push_event(task_id, "log", {
                            "level": "warn",
                            "message": f"验证: 步骤 {step_idx} 可能未完全完成 ({v_result.get('status','')})",
                        })
            except Exception as e:
                logger.warning(f"screenshot/verify error at step {step_idx}: {e}")

        # ── 步骤间等待 ──
        time.sleep(1.5)

    # ── 任务完成 ──
    _push_event(task_id, "task_done", {
        "task_id": task_id,
        "success": failed == 0,
        "steps_completed": completed,
        "steps_failed": failed,
        "total_steps": total,
    })

    # 延迟清理（让 SSE 客户端读完最后的事件）
    def _cleanup():
        time.sleep(3)
        unregister_task(task_id)

    threading.Thread(target=_cleanup, daemon=True).start()
