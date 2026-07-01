"""用户系统设置持久化（部署模式 + API 配置）。"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict

DEFAULT_SETTINGS: Dict[str, Any] = {
    "deployment_mode": "local",
    "ui_theme": "current",
    "a_end_url": "http://127.0.0.1:8010",
    "demo_key": "hajimi-demo-2026",
    "llm": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-chat",
    },
    "omniparser": {
        "url": "http://127.0.0.1:8002",
        "gpu_url": "",
    },
}


def _settings_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "HAJIMI")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "user_settings.json")


def _merge_defaults(data: dict) -> dict:
    out = deepcopy(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return out
    if data.get("deployment_mode") in ("local", "intranet"):
        out["deployment_mode"] = data["deployment_mode"]
    if data.get("ui_theme") in ("current", "variant_b", "variant_c"):
        out["ui_theme"] = data["ui_theme"]
    for key in ("a_end_url", "demo_key"):
        if data.get(key):
            out[key] = str(data[key]).strip()
    llm = data.get("llm") or {}
    if isinstance(llm, dict):
        for k in ("base_url", "api_key", "model"):
            if llm.get(k) is not None:
                out["llm"][k] = str(llm[k]).strip()
    omni = data.get("omniparser") or {}
    if isinstance(omni, dict):
        for k in ("url", "gpu_url"):
            if omni.get(k) is not None:
                out["omniparser"][k] = str(omni[k]).strip()
    return out


def load_user_settings() -> dict:
    path = _settings_path()
    if not os.path.isfile(path):
        return deepcopy(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as f:
            return _merge_defaults(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return deepcopy(DEFAULT_SETTINGS)


def save_user_settings(data: dict) -> dict:
    merged = _merge_defaults(data)
    path = _settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return merged


def apply_user_settings(data: dict | None = None) -> dict:
    """写入 os.environ 并刷新 config / api_client 模块变量。"""
    settings = _merge_defaults(data) if data is not None else load_user_settings()

    os.environ["HAJIMI_DEPLOYMENT_MODE"] = settings["deployment_mode"]
    os.environ["HAJIMI_API_URL"] = settings["a_end_url"]
    os.environ["HAJIMI_DEMO_KEY"] = settings["demo_key"]

    llm = settings.get("llm") or {}
    if llm.get("base_url"):
        os.environ["DEEPSEEK_BASE_URL"] = llm["base_url"]
    if llm.get("api_key"):
        os.environ["DEEPSEEK_API_KEY"] = llm["api_key"]
    if llm.get("model"):
        os.environ["DEEPSEEK_MODEL"] = llm["model"]

    omni = settings.get("omniparser") or {}
    if omni.get("url"):
        os.environ["OMNIPARSER_LOCAL_URL"] = omni["url"]
    gpu_url = (omni.get("gpu_url") or "").strip()
    if gpu_url:
        os.environ["OMNIPARSER_GPU_URL"] = gpu_url
    elif "OMNIPARSER_GPU_URL" in os.environ and not gpu_url:
        os.environ.pop("OMNIPARSER_GPU_URL", None)

    os.environ.setdefault("DETECTOR_BACKEND", "auto")

    import config as client_config

    client_config.reload_from_env()

    try:
        import core.api_client as api_client

        api_client.reload_client_config()
    except Exception:
        pass

    return settings


def is_intranet_mode() -> bool:
    return os.environ.get("HAJIMI_DEPLOYMENT_MODE", "local") == "intranet"
