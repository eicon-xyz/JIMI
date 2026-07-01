"""系统设置页可复用控件。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QObject, QEvent, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QButtonGroup,
    QFrame,
)


class SettingsEnterFilter(QObject):
    """Enter 提交（Shift+Enter 换行不适用单行框）。"""

    def __init__(self, submit_cb):
        super().__init__()
        self._submit = submit_cb

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._submit()
                return True
        return False


class SettingsFieldRow(QWidget):
    def __init__(
        self,
        label: str,
        placeholder: str = "",
        password: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("SettingsFieldRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)
        lbl = QLabel(label)
        lbl.setObjectName("SetRowLabel")
        lbl.setMinimumWidth(120)
        self.input = QLineEdit()
        self.input.setObjectName("SettingsInput")
        self.input.setPlaceholderText(placeholder)
        if password:
            self.input.setEchoMode(QLineEdit.Password)
        layout.addWidget(lbl, 0)
        layout.addWidget(self.input, 1)

    def text(self) -> str:
        return self.input.text().strip()

    def set_text(self, value: str) -> None:
        self.input.setText(value or "")

    def set_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)


class DeploymentModeGroup(QFrame):
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("部署模式")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("本地启动：本机 OmniParser + A 端；内网 API：仅连接远程 A 端（需校园网/VPN）")
        hint.setObjectName("HintTextSmall")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._local = QRadioButton("本地启动")
        self._local.setObjectName("SettingsRadio")
        self._intranet = QRadioButton("内网 API")
        self._intranet.setObjectName("SettingsRadio")
        self._local.setChecked(True)

        self._group = QButtonGroup(self)
        self._group.addButton(self._local, 0)
        self._group.addButton(self._intranet, 1)
        self._group.buttonClicked.connect(self._on_click)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._local)
        row.addWidget(self._intranet)
        row.addStretch()
        layout.addLayout(row)

    def _on_click(self):
        self.mode_changed.emit(self.current_mode())

    def current_mode(self) -> str:
        return "intranet" if self._intranet.isChecked() else "local"

    def set_mode(self, mode: str) -> None:
        if mode == "intranet":
            self._intranet.setChecked(True)
        else:
            self._local.setChecked(True)


class UiThemeGroup(QFrame):
    theme_changed = pyqtSignal(str)

    _THEMES = (
        ("current", "默认（工程基线）"),
        ("variant_b", "变体 B"),
        ("variant_c", "变体 C"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("界面主题")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("切换面板配色方案；变体 B/C 为 Stitch 设计占位，后续可替换为正式稿。")
        hint.setObjectName("HintTextSmall")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._buttons: dict[str, QRadioButton] = {}
        self._group = QButtonGroup(self)
        row = QVBoxLayout()
        row.setSpacing(6)
        for idx, (theme_id, label) in enumerate(self._THEMES):
            rb = QRadioButton(label)
            rb.setObjectName("SettingsRadio")
            self._group.addButton(rb, idx)
            self._buttons[theme_id] = rb
            row.addWidget(rb)
        self._group.buttonClicked.connect(self._on_click)
        layout.addLayout(row)
        self._buttons["current"].setChecked(True)

    def _on_click(self):
        self.theme_changed.emit(self.current_theme())

    def current_theme(self) -> str:
        for theme_id, btn in self._buttons.items():
            if btn.isChecked():
                return theme_id
        return "current"

    def set_theme(self, theme_id: str) -> None:
        btn = self._buttons.get(theme_id)
        if btn is not None:
            btn.setChecked(True)
