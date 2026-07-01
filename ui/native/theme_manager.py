"""Load and apply native UI theme packages (QSS + optional shell renderer)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from PyQt5.QtWidgets import QApplication, QWidget

from ui.native.shell_renderer import apply_shell_renderer

ShellMode = Literal["qss", "crystal"]

_THEMES_DIR = os.path.join(os.path.dirname(__file__), "themes")

THEME_IDS = ("current", "variant_b", "variant_c")

THEME_LABELS = {
    "current": "默认（工程基线）",
    "variant_b": "变体 B（Stitch 占位）",
    "variant_c": "变体 C（Stitch 占位）",
}


@dataclass(frozen=True)
class ThemeProfile:
    theme_id: str
    shell_mode: ShellMode


THEME_PROFILES: dict[str, ThemeProfile] = {
    "current": ThemeProfile("current", "qss"),
    "variant_b": ThemeProfile("variant_b", "qss"),
    "variant_c": ThemeProfile("variant_c", "qss"),
}


def _read_qss(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def compose_stylesheet(theme_id: str) -> str:
    """Concatenate _base + theme shell/topbar/content QSS."""
    if theme_id not in THEME_IDS:
        theme_id = "current"
    profile = THEME_PROFILES[theme_id]
    parts = [
        _read_qss(os.path.join(_THEMES_DIR, "_base.qss")),
    ]
    theme_dir = os.path.join(_THEMES_DIR, theme_id)
    shell_name = "shell_crystal.qss" if profile.shell_mode == "crystal" else "shell.qss"
    shell_path = os.path.join(theme_dir, shell_name)
    if profile.shell_mode == "crystal" and not os.path.isfile(shell_path):
        shell_path = os.path.join(theme_dir, "shell.qss")
    for name in (os.path.basename(shell_path), "topbar.qss", "content.qss"):
        parts.append(_read_qss(os.path.join(theme_dir, name)))
    return "\n\n".join(p for p in parts if p.strip())


class ThemeManager:
    """Apply theme stylesheet and shell renderer to registered panels."""

    def __init__(self, app: QApplication):
        self._app = app
        self._shells: list[tuple[QWidget, bool]] = []
        self._theme_id = "current"

    @property
    def theme_id(self) -> str:
        return self._theme_id

    def register_shell(self, widget: QWidget, *, compact: bool = False) -> None:
        for existing, _ in self._shells:
            if existing is widget:
                return
        self._shells.append((widget, compact))

    def apply(self, theme_id: str | None = None) -> str:
        tid = theme_id if theme_id in THEME_IDS else self._theme_id
        if theme_id in THEME_IDS:
            self._theme_id = theme_id
        profile = THEME_PROFILES.get(self._theme_id, THEME_PROFILES["current"])
        stylesheet = compose_stylesheet(self._theme_id)
        self._app.setStyleSheet(stylesheet)
        for widget, compact in self._shells:
            apply_shell_renderer(widget, profile.shell_mode, compact=compact)
        return self._theme_id


def get_theme_manager(app: QApplication | None = None) -> ThemeManager:
    """Return the singleton ThemeManager bound to the QApplication."""
    instance = app or QApplication.instance()
    if instance is None:
        raise RuntimeError("QApplication must exist before ThemeManager")
    mgr = getattr(instance, "_hajimi_theme_manager", None)
    if mgr is None:
        mgr = ThemeManager(instance)
        instance._hajimi_theme_manager = mgr  # type: ignore[attr-defined]
    return mgr
