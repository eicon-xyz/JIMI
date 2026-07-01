"""
水晶玻璃质感 PyQt5 页面背景 —— 晶莹透亮设计
==============================================
单个大面板 + 丰富背景内容，让透明度一目了然。

运行方式:  python -m ui.glass_demo
"""

import sys
import math
import random
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import (
    QPainter,
    QBrush,
    QColor,
    QPen,
    QLinearGradient,
    QRadialGradient,
    QFont,
    QPainterPath,
    QFontMetricsF,
)


random.seed(42)  # 固定种子，背景内容每次启动一致


# ═══════════════════════════════════════════
#  水晶玻璃面板
# ═══════════════════════════════════════════

class CrystalPanel(QWidget):
    """
    极致晶莹透亮的水晶玻璃面板。
    多层绘制: 半透明基底 → 边缘辉光 → 顶部镜面反射 → 底部微光
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # 投影 — 水晶阴影更轻更散
        fx = QGraphicsDropShadowEffect(self)
        fx.setBlurRadius(56)
        fx.setOffset(0, 14)
        fx.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(fx)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = 20.0
        rect = QRectF(0, 0, w, h)

        # ── 1. 主填充 —— 更低透明度让背景更清晰 ──
        base = QColor(12, 20, 38, 165)  # alpha ≈ 0.65
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(base))
        painter.drawPath(path)

        # ── 2. 外边框 —— 水晶的天然弧光 ──
        # 用 clip 保证所有后续绘制都在圆角内
        clip = QPainterPath()
        clip.addRoundedRect(rect, r, r)
        painter.setClipPath(clip)

        # 主体描边
        border_pen = QPen(QColor(255, 255, 255, 50), 1.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        # ── 3. 顶部镜面高光 —— 水晶特有的强烈反光 ──
        # 第一层: 大面积柔和高光
        grad1 = QLinearGradient(0, 0, 0, h * 0.45)
        grad1.setColorAt(0.00, QColor(255, 255, 255, 35))
        grad1.setColorAt(0.15, QColor(255, 255, 255, 18))
        grad1.setColorAt(0.40, QColor(255, 255, 255, 5))
        grad1.setColorAt(0.70, QColor(255, 255, 255, 0))
        grad1.setColorAt(1.00, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad1))
        painter.drawRect(QRectF(0, 0, w, h * 0.45))

        # 第二层: 顶部细窄的镜面反射条 (水晶标志)
        grad2 = QLinearGradient(0, 3, 0, h * 0.18)
        grad2.setColorAt(0.00, QColor(255, 255, 255, 55))
        grad2.setColorAt(0.08, QColor(255, 255, 255, 30))
        grad2.setColorAt(0.30, QColor(255, 255, 255, 6))
        grad2.setColorAt(0.80, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(grad2))
        painter.drawRect(QRectF(8, 3, w - 16, h * 0.18))

        # ── 4. 底部微光 ──
        bot_grad = QLinearGradient(0, h * 0.75, 0, h)
        bot_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        bot_grad.setColorAt(0.6, QColor(255, 255, 255, 4))
        bot_grad.setColorAt(1.0, QColor(255, 255, 255, 12))
        painter.setBrush(QBrush(bot_grad))
        painter.drawRect(QRectF(0, h * 0.75, w, h * 0.25))

        # ── 5. 侧边微光 —— 水晶边缘的微弱光晕 ──
        # 左上角
        corner = QRadialGradient(QPointF(12, 16), 180)
        corner.setColorAt(0.0, QColor(255, 255, 255, 14))
        corner.setColorAt(0.6, QColor(255, 255, 255, 3))
        corner.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(corner))
        painter.drawRect(QRectF(0, 0, w * 0.3, h * 0.3))

        # 右上角
        corner2 = QRadialGradient(QPointF(w - 12, 16), 180)
        corner2.setColorAt(0.0, QColor(255, 255, 255, 10))
        corner2.setColorAt(0.6, QColor(255, 255, 255, 2))
        corner2.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(corner2))
        painter.drawRect(QRectF(w * 0.7, 0, w * 0.3, h * 0.3))

        painter.end()


# ═══════════════════════════════════════════
#  丰富背景 (各种内容让透明度可见)
# ═══════════════════════════════════════════

class BusyBackground(QWidget):
    """绘制色彩丰富的背景内容，让玻璃的透明度一目了然。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("水晶玻璃质感 · Crystal Glass — HAJIMI UI")
        self.setMinimumSize(900, 680)

        # 预生成一些随机元素
        self._blocks = self._gen_blocks()
        self._circles = self._gen_circles()
        self._code_lines = self._gen_code_lines()
        self._grid_lines = self._gen_grid()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 26, 60, 40)
        layout.setSpacing(0)

        # ── 标题 (在背景上，不在玻璃内) ──
        title = QLabel("水晶玻璃 · Crystal Glass")
        title.setStyleSheet(
            "color: rgba(255,255,255,0.92); font-size: 22px; font-weight: 700;"
            "letter-spacing: 1px; background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("背景布满随机文字与色块，透过玻璃面板的透明区域验证质感")
        sub.setStyleSheet(
            "color: rgba(255,255,255,0.55); font-size: 12px;"
            "background: transparent; padding-bottom: 14px;"
        )
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # ── 水晶玻璃面板 (填充整块空间) ──
        self._glass = CrystalPanel()
        glass_inner = QVBoxLayout(self._glass)
        glass_inner.setContentsMargins(28, 22, 28, 22)
        glass_inner.setSpacing(6)

        hint = QLabel(
            "下方区域布满彩色色块、随机文本行、代码片段。"
            "透过玻璃面板的透明区域观察这些内容，即可判断透明度 / 晶透效果是否理想。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color: #f1f5f9; font-size: 13px; line-height: 1.8; background: transparent;"
        )
        glass_inner.addWidget(hint)

        glass_inner.addStretch()

        params = QHBoxLayout()
        params.setSpacing(32)
        for name, val in [
            ("填充 α", "165 / 255"),
            ("顶部高光 α", "35~55 / 255"),
            ("边框 α", "50 / 255"),
            ("阴影模糊", "56px"),
            ("圆角", "20px"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(3)
            n = QLabel(name)
            n.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 10px; background: transparent;")
            v = QLabel(val)
            v.setStyleSheet("color: rgba(255,255,255,0.92); font-size: 16px; font-weight: 700; background: transparent;")
            col.addWidget(n)
            col.addWidget(v)
            params.addLayout(col)
        params.addStretch()
        glass_inner.addLayout(params)

        layout.addWidget(self._glass, 1)

    # ── 背景生成器 ──

    def _gen_blocks(self):
        """随机彩色矩形块"""
        items = []
        colors = [
            (255, 80, 80, 90), (80, 180, 255, 85), (100, 220, 120, 80),
            (255, 200, 60, 95), (180, 80, 255, 80), (255, 130, 60, 90),
            (60, 210, 210, 85), (255, 100, 180, 80), (120, 160, 255, 85),
            (240, 240, 60, 70), (255, 150, 100, 80), (80, 220, 180, 85),
        ]
        for _ in range(18):
            x = random.randint(10, 850)
            y = random.randint(40, 630)
            w = random.randint(40, 180)
            h = random.randint(18, 90)
            c = random.choice(colors)
            items.append((QRectF(x, y, w, h), QColor(*c)))
        return items

    def _gen_circles(self):
        """随机彩色圆形"""
        items = []
        colors = [
            (255, 80, 80, 70), (80, 180, 255, 65), (100, 240, 120, 70),
            (255, 210, 60, 75), (170, 80, 240, 65), (255, 140, 60, 70),
            (60, 200, 200, 65), (200, 120, 255, 60), (130, 170, 255, 70),
            (240, 240, 60, 55), (255, 110, 140, 65), (80, 210, 190, 65),
        ]
        for _ in range(12):
            cx = random.randint(40, 860)
            cy = random.randint(60, 620)
            rad = random.randint(25, 80)
            c = random.choice(colors)
            items.append((QPointF(cx, cy), rad, QColor(*c)))
        return items

    def _gen_code_lines(self):
        """模拟代码行/文本行"""
        prefixes = [
            "import", "from", "def", "class", "return", "self.",
            "const", "let", "await", "async", "export", "function",
            "SELECT", "INSERT", "UPDATE", "WHERE", "ORDER BY",
            "<div", "</div>", "margin:", "padding:", "border-radius",
            "QWidget {", "key=lambda", "yield", "raise", "with",
        ]
        colors = [
            QColor(120, 180, 255, 140),  # 蓝色关键字
            QColor(140, 220, 140, 130),  # 绿色字符串
            QColor(220, 180, 100, 130),  # 黄色
            QColor(200, 140, 220, 120),  # 紫色
            QColor(140, 200, 220, 120),  # 青色
            QColor(220, 140, 140, 115),  # 粉色
        ]
        items = []
        y = 40
        for _ in range(35):
            prefix = random.choice(prefixes)
            suffix_len = random.randint(6, 28)
            suffix = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz_') for _ in range(suffix_len))
            color = random.choice(colors)
            size = random.randint(10, 13)
            x = random.randint(5, 700)
            y += random.randint(14, 24)
            if y > 660:
                break
            items.append((prefix + " " + suffix, QPointF(x, y), size, color))
        return items

    def _gen_grid(self):
        """网格辅助线"""
        lines_v = []
        for x in range(60, 860, 90):
            lines_v.append((QPointF(x, 0), QPointF(x, 680)))
        lines_h = []
        for y in range(30, 660, 80):
            lines_h.append((QPointF(0, y), QPointF(900, y)))
        return (lines_v, lines_h)

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # ── 底层: 深色渐变 ──
        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor(8, 12, 28))
        base.setColorAt(0.5, QColor(14, 22, 46))
        base.setColorAt(1.0, QColor(6, 10, 22))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(base))
        painter.drawRect(self.rect())

        # ── 网格线 ──
        pen = QPen(QColor(255, 255, 255, 6), 0.5, Qt.DotLine)
        painter.setPen(pen)
        for (p1, p2) in self._grid_lines[0]:
            painter.drawLine(p1, p2)
        for (p1, p2) in self._grid_lines[1]:
            painter.drawLine(p1, p2)

        # ── 彩色圆形 ──
        for pos, rad, color in self._circles:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(pos, rad, rad)

        # ── 彩色矩形块 ──
        for rect, color in self._blocks:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, 4, 4)

        # ── 模拟代码行 ──
        for text, pos, size, color in self._code_lines:
            font = QFont("Consolas", size)
            font.setStyleHint(QFont.Monospace)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(pos, text)

        # ── 装饰光斑 ──
        glow1 = QRadialGradient(QPointF(w * 0.3, h * 0.2), 320)
        glow1.setColorAt(0.0, QColor(90, 160, 200, 10))
        glow1.setColorAt(1.0, QColor(90, 160, 200, 0))
        painter.setBrush(QBrush(glow1))
        painter.drawRect(self.rect())

        glow2 = QRadialGradient(QPointF(w * 0.8, h * 0.75), 300)
        glow2.setColorAt(0.0, QColor(180, 120, 240, 8))
        glow2.setColorAt(1.0, QColor(180, 120, 240, 0))
        painter.setBrush(QBrush(glow2))
        painter.drawRect(self.rect())

        painter.end()


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyleSheet("""
        * { font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
    """)

    window = BusyBackground()
    window.show()
    sys.exit(app.exec_())
