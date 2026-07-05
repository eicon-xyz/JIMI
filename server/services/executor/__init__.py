"""
HAJIMI 自动操作助手 — 执行引擎
"""
from server.services.executor.engine import run_plan, cancel_task, register_task, unregister_task
from server.services.executor.clicker import execute_action, click_at, type_text, press_keys
from server.services.executor.safety import check_step, check_query, SafetyResult

__all__ = [
    "run_plan",
    "cancel_task",
    "register_task",
    "unregister_task",
    "execute_action",
    "click_at",
    "type_text",
    "press_keys",
    "check_step",
    "check_query",
    "SafetyResult",
]
