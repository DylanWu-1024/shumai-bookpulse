# -*- coding: utf-8 -*-
"""
自定义控件与动效 —— 让界面「活」起来的那一层
================================================================================
QSS 有两个做不了的事，必须靠代码补：
    ① box-shadow   → 用 QGraphicsDropShadowEffect
    ② transition   → 用 QPropertyAnimation / 动画组

这里提供：
    LogoMark          纯代码绘制的品牌标记（渐变圆角方块 + 书页符号，无图片依赖）
    Card              带柔和阴影的卡片容器
    FadeStack         切页时淡入的 QStackedWidget
    SmoothProgress    数值平滑推进的进度条
    Toast             底部浮层提示（淡入 + 上滑 + 自动淡出）
    Pill              药丸小标签
    set_caption_color Windows 原生标题栏染色（让系统标题栏与侧栏连成一体）
"""

import ctypes

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QSize,
    QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, Property, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QLinearGradient, QRadialGradient,
    QPen, QPainterPath, QPixmap, QBrush,
)

import sys as _sys
from PySide6.QtWidgets import (
    QLabel, QWidget, QFrame, QStackedWidget, QProgressBar, QLineEdit,
    QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout, QLayout,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
)

import theme

# 当前调色板（由界面在换主题时刷新，自绘控件从这里取色）
_PAL = theme.palette()

# 全局动效开关：关掉后所有动画退化为瞬时切换（更安静、更省电）
MOTION = True


def set_palette(p):
    global _PAL
    _PAL = p


def pal():
    """取当前调色板 —— 需要在 HTML / 自绘里用主题色时用它，别自己写死颜色。"""
    return _PAL


def set_motion(on):
    global MOTION
    MOTION = bool(on)


# ==========================================================================
# Windows 原生标题栏染色
# ==========================================================================
def set_caption_color(win, color_hex=None, dark=None):
    """把系统标题栏染成指定颜色，视觉上与深色侧栏连成一体。

    使用 Windows 11 的 DwmSetWindowAttribute：
        attribute 35 = DWMWA_CAPTION_COLOR（22H2+）
        attribute 20 = DWMWA_USE_IMMERSIVE_DARK_MODE
    任何一步失败都静默跳过，不影响程序运行。
    """
    try:
        hwnd = int(win.winId())
    except Exception:
        return
    try:
        if color_hex and len(color_hex) == 7:
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            colorref = r | (g << 8) | (b << 16)      # COLORREF 是 BGR
            v = ctypes.c_int(colorref)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass
    try:
        if dark is not None:
            v2 = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(v2), ctypes.sizeof(v2))
    except Exception:
        pass


# ==========================================================================
# 柔和阴影
# ==========================================================================
def apply_shadow(widget, blur=22, dy=4, alpha=26, color='#3B3A7A'):
    """给控件加柔和阴影（QSS 不支持 box-shadow）。"""
    try:
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur)
        eff.setXOffset(0)
        eff.setYOffset(dy)
        c = QColor(color)
        c.setAlpha(alpha)
        eff.setColor(c)
        widget.setGraphicsEffect(eff)
        return eff
    except Exception:
        return None


# ==========================================================================
# 品牌标记（纯代码绘制，不依赖任何图片资源）
# ==========================================================================
class LogoMark(QWidget):
    """渐变圆角方块 + 简化书页符号。纯 QPainter 绘制，打包时零资源依赖。"""

    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, ev):
        # 绘画异常绝不能冒到 Qt 的 C++ 层 —— 那会直接让整个进程段错误
        try:
            self._paint()
        except Exception:
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        sz = self.width()
        p.scale(sz / 100.0, sz / 100.0)

        g = QLinearGradient(0, 0, 100, 100)
        g.setColorAt(0.0, QColor(_PAL.get('PRIMARY', '#6366F1')))
        g.setColorAt(1.0, QColor(_PAL.get('PRIMARY_L', '#7C3AED')))
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, 100, 100, 30, 30)

        # 书形轮廓（开口向上的槽）
        pen = QPen(QColor(255, 255, 255), 6.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        book = QPainterPath()
        book.moveTo(28, 33)
        book.lineTo(28, 70)
        book.lineTo(72, 70)
        book.lineTo(72, 33)
        p.drawPath(book)

        # 脉冲线
        pen2 = QPen(QColor(255, 255, 255), 5.0)
        pen2.setCapStyle(Qt.RoundCap)
        pen2.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen2)
        pulse = QPainterPath()
        pulse.moveTo(33, 52)
        pulse.lineTo(43, 52)
        pulse.lineTo(48, 40)
        pulse.lineTo(55, 64)
        pulse.lineTo(60, 52)
        pulse.lineTo(67, 52)
        p.drawPath(pulse)
        p.end()


# ==========================================================================
# 卡片
# ==========================================================================
class Card(QFrame):
    """圆角卡片 + 柔和阴影。objectName 用 theme 里的 #Card。"""

    def __init__(self, parent=None, shadow=True, name='Card'):
        super().__init__(parent)
        self.setObjectName(name)
        self._has_shadow = bool(shadow)
        if shadow:
            apply_shadow(self)

    def restore_shadow(self):
        """重新挂回阴影。

        背景：Qt 里一个控件只能挂一个 QGraphicsEffect。卡片入场动效会挂
        QGraphicsOpacityEffect，这会顶掉卡片原本的阴影；动画结束后若只是
        简单 setGraphicsEffect(None)，卡片的阴影就永久消失了。
        所以入场动效结束时调用本方法，把阴影挂回来。
        """
        if self._has_shadow:
            apply_shadow(self)
        else:
            self.setGraphicsEffect(None)


# ==========================================================================
# 背景装饰层：柔和光晕 + 缓慢漂浮的粒子
# ==========================================================================
class BackdropLayer(QWidget):
    """铺在主内容区底下的装饰层。

    干三件事：铺底色 → 画三团柔和光晕 → 飘几十个小光点。
    卡片做成半透明（#Card 用 rgba）之后，底下的光晕会透上来 —— 这就是
    「磨砂玻璃」的观感来源（QSS 没有 backdrop-filter，得自己造）。

    纯 QPainter 自绘、不引任何额外依赖。光晕渲染进缓存位图，每帧只做一次
    位图合成 + 画几十个小圆，开销很低。关掉「界面动效」粒子就静止；
    关掉「磨砂玻璃」整层隐藏，根容器自己铺底色。
    """

    STEP_MS = 45          # ≈22 帧/秒：粒子本来就慢，够顺，也省电

    def __init__(self, parent=None):
        super().__init__(parent)
        # 只是装饰，绝不能挡住底下的点击
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._back = None
        self._key = None
        self._parts = []
        self._timer = QTimer(self)
        self._timer.setInterval(self.STEP_MS)
        self._timer.timeout.connect(self._tick)
        self._sync()

    # ------------------------------------------------------------ 生命周期
    def refresh_theme(self):
        """换主题 / 改尺寸后调用：丢掉缓存位图，重新撒粒子。"""
        self._back = None
        self._key = None
        self._parts = []
        self._sync()
        self.update()

    def _sync(self):
        want = bool(MOTION) and self.isVisible() and bool(_PAL.get('GLASS'))
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._sync()

    # ------------------------------------------------------------ 粒子
    def _seed(self):
        """按面积撒粒子：窗口大就多几个，但设上限免得大屏上糊成一片。"""
        import random as _r
        w, h = max(1, self.width()), max(1, self.height())
        n = max(14, min(46, int(w * h / 40000)))
        self._parts = []
        for _ in range(n):
            self._parts.append([
                _r.uniform(210, max(240, w)), _r.uniform(0, h),      # x, y（避开侧栏）
                _r.uniform(1.4, 4.0),                               # 半径
                _r.uniform(-0.26, 0.26), _r.uniform(-0.22, 0.22),   # vx, vy
                _r.uniform(0.30, 1.0),                              # 亮度
            ])

    def _tick(self):
        if not self._parts and self.width() > 1:
            self._seed()
        w, h = max(1, self.width()), max(1, self.height())
        lo = 202                     # 侧栏右边缘，粒子只在内容区飘
        for q in self._parts:
            q[0] += q[4]
            q[1] += q[5]
            if q[0] < lo:
                q[0] = w + 8
            elif q[0] > w + 8:
                q[0] = lo
            if q[1] < -8:
                q[1] = h + 8
            elif q[1] > h + 8:
                q[1] = -8
        self.update()

    # ------------------------------------------------------------ 绘制
    def _render_glow(self, rect, pal):
        """把底色上的「点阵纹理 + 三团柔和光晕」渲染进一张缓存位图。

        只在尺寸或配色变化时重算，所以每帧的实际开销只是贴一张图 + 画几十个小圆。
        光晕中心特意偏右、偏下：左侧 200px 会被侧栏盖住，光晕放那儿纯属浪费。
        """
        pm = QPixmap(rect.size())
        pm.fill(Qt.transparent)
        g = QPainter(pm)
        g.setRenderHint(QPainter.Antialiasing, True)
        g.setPen(Qt.NoPen)
        w, h = rect.width(), rect.height()
        dark = bool(pal.get('DARK'))
        c1 = QColor(pal.get('PRIMARY') or '#6366F1')
        c2 = QColor(pal.get('ACCENT') or c1.name())

        # ① 极淡的点阵纹理 —— 让大片空白有"材质"，但又几乎注意不到
        dot = QColor(pal.get('ink') or '#000000')
        dot.setAlpha(18 if dark else 13)
        g.setBrush(dot)
        step = 26
        x0, y0 = 214, 14          # 从侧栏右侧开始，少画一堆被挡住的点
        for yy in range(y0, h, step):
            for xx in range(x0, w, step):
                # 隔行错位，看起来像细密网点而不是方格纸
                g.drawEllipse(QPointF(xx + (step // 2 if (yy // step) % 2 else 0),
                                      yy), 1.0, 1.0)

        # ② 三团柔和光晕
        a1 = 56 if dark else 42
        a2 = 42 if dark else 30
        spots = (
            (w * 0.42, h * 0.00, max(w, h) * 0.62, c1, a1),   # 上中
            (w * 0.97, h * 0.26, max(w, h) * 0.54, c2, a2),   # 右中
            (w * 0.70, h * 1.04, max(w, h) * 0.64, c1, a2),   # 右下
        )
        for cx, cy, rad, col, alpha in spots:
            grad = QRadialGradient(QPointF(cx, cy), rad)
            # 分三段衰减（0 → 35% → 0）而不是线性两段：
            # 线性衰减在浅色背景上能看出圆形的边，中间多一段就化开了
            inner = QColor(col)
            inner.setAlpha(alpha)
            mid = QColor(col)
            mid.setAlpha(int(alpha * 0.34))
            outer = QColor(col)
            outer.setAlpha(0)
            grad.setColorAt(0.0, inner)
            grad.setColorAt(0.5, mid)
            grad.setColorAt(1.0, outer)
            g.setBrush(QBrush(grad))
            g.drawEllipse(QPointF(cx, cy), rad, rad)
        g.end()
        return pm

    def paintEvent(self, ev):
        pal = _PAL
        rect = self.rect()
        if rect.width() < 4 or rect.height() < 4:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(rect, QColor(pal.get('bg') or '#FFFFFF'))

        key = (rect.width(), rect.height(), pal.get('PRIMARY'),
               pal.get('ACCENT'), pal.get('bg'), pal.get('DARK'))
        if self._back is None or self._key != key:
            self._back = self._render_glow(rect, pal)
            self._key = key
        p.drawPixmap(0, 0, self._back)

        if not pal.get('GLASS'):
            p.end()
            return

        if not self._parts:
            self._seed()
        base = QColor(pal.get('PRIMARY') or '#6366F1')
        accent = QColor(pal.get('ACCENT') or base.name())
        top = 108 if pal.get('DARK') else 74
        p.setPen(Qt.NoPen)
        for i, q in enumerate(self._parts):
            c = QColor(accent if i % 3 == 0 else base)
            c.setAlpha(max(8, int(top * q[5])))
            p.setBrush(c)
            p.drawEllipse(QPointF(q[0], q[1]), q[2], q[2])
        p.end()


# ==========================================================================
# 自动换行的水平布局
# ==========================================================================
class FlowLayout(QLayout):
    """像网页那样「一行放不下就自动换行」的布局。

    背景：导出格式那排复选框原来是写死的 QHBoxLayout。窗口一窄，Qt 会把
    每个复选框压扁，`HTML` 被裁成 `HTM`、`JSON` 被裁成 `JSO` —— 难看且费解。
    Qt 自带的布局没有换行能力，所以自己写一个（实现很直白，就一遍扫描）。
    """

    def __init__(self, parent=None, spacing=10):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ---- QLayout 要求的一堆小接口 ----
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ---- 真正干活：一遍扫描，超宽就换行 ----
    def _layout(self, rect, test):
        m = self.contentsMargins()
        box = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = box.x(), box.y(), 0
        for it in self._items:
            sz = it.sizeHint()
            if x + sz.width() > box.right() + 1 and line_h > 0:
                x = box.x()
                y += line_h + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._sp
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()


# ==========================================================================
# 淡入切换的页面容器
# ==========================================================================
class FadeStack(QStackedWidget):
    """切页时给目标页做一次淡入。

    关键细节：动画结束后必须把 QGraphicsEffect 摘掉，否则该页所有子控件
    都会被强制走离屏渲染，表格滚动会明显变卡。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = None

    def fade_to(self, idx):
        if idx < 0 or idx >= self.count() or idx == self.currentIndex():
            return
        if not MOTION:
            self.setCurrentIndex(idx)
            return
        target = self.widget(idx)
        fx = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b'opacity', self)
        anim.setDuration(190)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def cleanup():
            try:
                target.setGraphicsEffect(None)     # 摘掉效果，恢复硬件加速
            except Exception:
                pass

        anim.finished.connect(cleanup)
        self.setCurrentIndex(idx)
        anim.start()
        self._anim = anim


# ==========================================================================
# 平滑进度条
# ==========================================================================
class SmoothProgress(QProgressBar):
    """数值变化时平滑推进，而不是生硬跳变。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setRange(0, 100)
        self.setValue(0)
        self._anim = QPropertyAnimation(self, b'value', self)
        self._anim.setDuration(340)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def slide_to(self, v):
        v = int(max(self.minimum(), min(self.maximum(), v)))
        if v == self.value():
            return
        if not MOTION:
            self.setValue(v)
            return
        self._anim.stop()
        self._anim.setStartValue(self.value())
        self._anim.setEndValue(v)
        self._anim.start()

    def reset(self):
        self._anim.stop()
        self.setValue(0)


# ==========================================================================
# 药丸小标签
# ==========================================================================
def make_pill(text, accent=False):
    lb = QLabel(text)
    lb.setObjectName('PillAccent' if accent else 'Pill')
    return lb


# ==========================================================================
# 浮层提示
# ==========================================================================
class Toast(QLabel):
    """底部浮层提示：淡入 + 从下往上滑入，停留后自动淡出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Toast')
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWordWrap(False)
        self.hide()

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)

        self._slide = QPropertyAnimation(self, b'pos', self)
        self._fade = QPropertyAnimation(self._fx, b'opacity', self)
        self._group = QParallelAnimationGroup(self)
        self._group.addAnimation(self._fade)
        self._group.addAnimation(self._slide)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)

    def _target_pos(self):
        par = self.parentWidget()
        if not par:
            return QPoint(0, 0)
        self.adjustSize()
        x = int((par.width() - self.width()) / 2)
        y = int(par.height() - self.height() - 34)
        return QPoint(max(0, x), max(0, y))

    def show_msg(self, text, kind='', hold=2200):
        self.setText(text)
        self.setObjectName({'ok': 'ToastOk', 'warn': 'ToastWarn'}.get(kind, 'Toast'))
        self.style().unpolish(self)
        self.style().polish(self)
        self.adjustSize()

        end = self._target_pos()
        start = QPoint(end.x(), end.y() + 16)
        self.move(start)
        self._fx.setOpacity(0.0)
        self.show()
        self.raise_()

        if not MOTION:
            self._fx.setOpacity(1.0)
            self.move(end)
            self.show()
            self.raise_()
            self._timer.start(hold)
            return

        self._group.stop()
        self._slide.setDuration(240)
        self._slide.setStartValue(start)
        self._slide.setEndValue(end)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.setDuration(200)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._group.start()

        self._timer.start(hold)

    def fade_out(self):
        try:
            self._group.stop()
            self._fade.setDuration(260)
            self._fade.setStartValue(self._fx.opacity())
            self._fade.setEndValue(0.0)
            self._fade.start()
            self._timer.stop()
            QTimer.singleShot(300, self.hide)
        except Exception:
            self.hide()


# ==========================================================================
# 空状态：自绘插画 + 标题 + 一句引导
# ==========================================================================
class _EmptyArt(QWidget):
    """几根线条组成的「空书页」，纯 QPainter 绘制，零图片依赖。"""

    def __init__(self, size=78, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, ev):
        try:
            self._paint()
        except Exception:
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()

        pen = QPen(QColor(_PAL.get('input_border', '#DBDFF2')), max(1.6, w * 0.026))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(2, 2, w - 4, w - 4, w * 0.16, w * 0.16)

        pen2 = QPen(QColor(_PAL.get('muted', '#8B8FAE')), max(1.6, w * 0.026))
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        y = w * 0.34
        for frac in (0.64, 0.50, 0.36):
            p.drawLine(int(w * 0.22), int(y), int(w * 0.22 + (w - w * 0.44) * (frac / 0.64)), int(y))
            y += w * 0.14
        p.end()


class EmptyState(QWidget):
    """比干巴巴一句「暂无数据」友好得多的空状态。"""

    def __init__(self, title='', desc='', parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(9)
        v.addWidget(_EmptyArt(), 0, Qt.AlignHCenter)
        self.lb_t = QLabel(title)
        self.lb_t.setObjectName('EmptyTitle')
        self.lb_t.setAlignment(Qt.AlignCenter)
        self.lb_d = QLabel(desc)
        self.lb_d.setObjectName('EmptyDesc')
        self.lb_d.setAlignment(Qt.AlignCenter)
        self.lb_d.setWordWrap(True)
        v.addWidget(self.lb_t)
        v.addWidget(self.lb_d)
        self._art = v.itemAt(0).widget()

    def set_text(self, title, desc):
        self.lb_t.setText(title)
        self.lb_d.setText(desc)

    def paintEvent(self, ev):
        # 主题变化后重绘自绘插画
        try:
            self._art.update()
        except Exception:
            pass
        super().paintEvent(ev)


# ==========================================================================
# 数字滚动
# ==========================================================================
class AnimatedNumber(QLabel):
    """数值变化时平滑滚动到新值，而不是硬跳（统计卡用）。"""

    def __init__(self, value=0, parent=None):
        super().__init__(parent)
        self._num = 0.0
        self.setText('0')
        self._anim = QPropertyAnimation(self, b'num', self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_num(self):
        return self._num

    def set_num(self, v):
        self._num = float(v)
        self.setText('{:,}'.format(int(round(self._num))))

    num = Property(float, get_num, set_num)

    def roll_to(self, value):
        value = int(value)
        if not MOTION:
            self._anim.stop()
            self.set_num(value)
            return
        self._anim.stop()
        self._anim.setStartValue(self._num)
        self._anim.setEndValue(float(value))
        self._anim.start()


# ==========================================================================
# 图表（纯 QPainter 绘制 —— 不引入 matplotlib/pyqtgraph，打包体积零增加）
# ==========================================================================
def fmt_num_cn(n):
    """中文习惯的短数字：9.1万 / 2537 / 416。"""
    try:
        n = int(n or 0)
    except Exception:
        return '0'
    if abs(n) >= 10000:
        return '%.1f万' % (n / 10000.0)
    return str(n)


def _nice_max(v):
    """把最大值向上取整到「好看的刻度」：1 / 2 / 2.5 / 5 / 10 × 10^n。"""
    import math
    try:
        v = float(v)
    except Exception:
        return 1
    if v <= 0:
        return 1
    e = math.pow(10, math.floor(math.log10(v)))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e:
            return m * e
    return 10 * e


class LineChart(QWidget):
    """多序列折线图。

    series: [{'name': str, 'points': [int|None, ...], 'color': '#RRGGBB'}]
    points 里的 None 表示该时间点这条线还不存在 —— 折线会自然断开，
    而不是假装它等于 0（那会把「新出现的划线」画成从零暴涨，是错误信息）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        self.series = []
        self._hover = -1
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_data(self, labels, series):
        self.labels = list(labels or [])
        self.series = [dict(s) for s in (series or [])]
        self._hover = -1
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, ev):
        try:
            self._paint()
        except Exception:
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if not self.series or not self.labels:
            return

        ink_sub = QColor(_PAL.get('muted', '#8B8FAE'))
        line = QColor(_PAL.get('line', '#E6E7F4'))
        ink = QColor(_PAL.get('ink', '#22203F'))

        legend_h = 22 if len(self.series) > 1 else 0
        pad_l, pad_r, pad_t, pad_b = 58, 20, 14 + legend_h, 30
        cw = max(10, w - pad_l - pad_r)
        ch = max(10, h - pad_t - pad_b)

        # 数值范围（None 不参与）
        allv = [v for s in self.series for v in s.get('points', []) if v is not None]
        if not allv:
            return

        # Y 轴范围。两条规则：
        #   ① 单序列看绝对量 → 从 0 起，不夸大
        #   ② 多序列是用来看走势对比的 → 从最小值附近起，否则几条线会糊在一起
        vmax, vmin = max(allv), min(allv)
        multi = len(self.series) > 1
        if multi or (vmax > 0 and (vmax - vmin) <= vmax * 0.35):
            pad = max(1.0, (vmax - vmin) * 0.25)
            ymax = _nice_max(vmax + pad)
            ymin = max(0.0, vmin - pad)
            if ymin >= ymax * 0.85:
                ymin = 0.0
        else:
            ymin = 0.0
            ymax = _nice_max(vmax)

        def px(i):
            n = len(self.labels)
            return pad_l + (cw * (i / (n - 1)) if n > 1 else cw / 2)

        def py(v):
            return pad_t + ch - ch * ((v - ymin) / (ymax - ymin or 1))

        # 网格 + y 轴刻度
        p.setPen(QPen(line, 1))
        for k in range(5):
            y = pad_t + ch * k / 4.0
            p.drawLine(int(pad_l), int(y), int(pad_l + cw), int(y))
        p.setPen(QPen(ink_sub, 1))
        for k in range(5):
            v = ymax - (ymax - ymin) * k / 4.0
            y = pad_t + ch * k / 4.0
            p.drawText(0, int(y) - 8, pad_l - 10, 16,
                       Qt.AlignRight | Qt.AlignVCenter, fmt_num_cn(v))

        # x 轴标签（自动抽稀，避免挤在一起；最后一个右对齐，否则会被裁掉）
        n = len(self.labels)
        step = max(1, int((n + 5) / 6))
        idxs = [i for i in range(n) if (i % step == 0 or i == n - 1)]
        # 末尾两个标签挨得太近就丢掉前一个，否则文字会叠在一起
        if len(idxs) >= 2 and idxs[-1] - idxs[-2] < step:
            idxs.pop(-2)
        p.setPen(QPen(ink_sub, 1))
        for i in idxs:
            if i == n - 1:
                xx, al = int(px(i)) - 84, Qt.AlignRight
            else:
                xx, al = int(px(i)) - 44, Qt.AlignHCenter
            p.drawText(xx, int(pad_t + ch) + 7, 88, 18,
                       al | Qt.AlignTop, str(self.labels[i]))

        # 折线
        for s in self.series:
            col = QColor(s.get('color') or _PAL.get('PRIMARY', '#6366F1'))
            pen = QPen(col, 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)

            pts = s.get('points') or []
            prev = None
            for i, v in enumerate(pts):
                if v is None:
                    prev = None
                    continue
                cur = QPoint(int(px(i)), int(py(v)))
                if prev is not None:
                    p.drawLine(prev, cur)
                prev = cur

            # 端点
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            for i, v in enumerate(pts):
                if v is None:
                    continue
                if n <= 14 or i == 0 or i == n - 1 or i == self._hover:
                    p.drawEllipse(QPoint(int(px(i)), int(py(v))), 3, 3)

        # 悬停竖线
        if 0 <= self._hover < n:
            p.setPen(QPen(QColor(_PAL.get('PRIMARY', '#6366F1')), 1, Qt.DashLine))
            x = int(px(self._hover))
            p.drawLine(x, int(pad_t), x, int(pad_t + ch))

        # 图例
        if legend_h:
            x = pad_l
            p.setPen(QPen(ink, 1))
            for s in self.series:
                col = QColor(s.get('color') or _PAL.get('PRIMARY', '#6366F1'))
                p.setBrush(col)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x, 6, 10, 10, 3, 3)
                name = str(s.get('name') or '')
                if len(name) > 16:
                    name = name[:16] + '…'
                p.setPen(QPen(ink, 1))
                p.drawText(x + 15, 2, 190, 18, Qt.AlignLeft | Qt.AlignVCenter, name)
                x += 15 + 22 + p.fontMetrics().horizontalAdvance(name)
                if x > w - 120:
                    break
        p.end()

    def mouseMoveEvent(self, ev):
        try:
            n = len(self.labels)
            if n > 1:
                pad_l, pad_r = 58, 20
                cw = max(10, self.width() - pad_l - pad_r)
                ratio = (ev.position().x() - pad_l) / cw
                idx = int(round(ratio * (n - 1)))
                idx = max(0, min(n - 1, idx))
                if idx != self._hover:
                    self._hover = idx
                    tips = []
                    for s in self.series:
                        pts = s.get('points') or []
                        if idx < len(pts) and pts[idx] is not None:
                            tips.append('%s: %s' % (s.get('name', ''), fmt_num_cn(pts[idx])))
                    if tips:
                        self.setToolTip('%s\n%s' % (self.labels[idx], '\n'.join(tips)))
                    self.update()
        except Exception:
            pass

    def leaveEvent(self, ev):
        self._hover = -1
        self.update()


class BarChart(QWidget):
    """横向条形图：适合「哪几章最热」这类分布对比。

    items: [{'label': str, 'value': int, 'sub': str}]
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setMinimumHeight(120)

    def set_data(self, items):
        self.items = list(items or [])
        row = 30
        self.setMinimumHeight(max(70, row * max(1, len(self.items)) + 12))
        self.update()

    def paintEvent(self, ev):
        try:
            self._paint()
        except Exception:
            pass

    def _paint(self):
        if not self.items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        ink = QColor(_PAL.get('ink', '#22203F'))
        ink_sub = QColor(_PAL.get('muted', '#8B8FAE'))
        track = QColor(_PAL.get('line', '#E6E7F4'))
        c1 = QColor(_PAL.get('PRIMARY', '#6366F1'))
        c2 = QColor(_PAL.get('ACCENT', '#F472B6'))

        vmax = max([int(i.get('value') or 0) for i in self.items] or [1]) or 1
        row = 30
        label_w = min(190, max(96, int(w * 0.30)))
        val_w = 74
        bar_x = label_w + 10
        bar_w = max(20, w - bar_x - val_w)

        for k, it in enumerate(self.items):
            y = k * row + 6
            if y + row > h + row:
                break
            name = str(it.get('label') or '')
            fm = p.fontMetrics()
            while len(name) > 3 and fm.horizontalAdvance(name) > label_w - 8:
                name = name[:-2] + '…'

            p.setPen(QPen(ink, 1))
            p.drawText(0, y, label_w, row, Qt.AlignRight | Qt.AlignVCenter, name)

            # 底槽
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(bar_x, y + row / 2 - 5, bar_w, 10, 5, 5)

            # 条
            v = int(it.get('value') or 0)
            bw = int(bar_w * (v / float(vmax)))
            if bw > 0:
                g = QLinearGradient(bar_x, 0, bar_x + max(bw, 12), 0)
                g.setColorAt(0.0, c1)
                g.setColorAt(1.0, c2)
                p.setBrush(g)
                p.drawRoundedRect(bar_x, y + row / 2 - 5, max(bw, 6), 10, 5, 5)

            p.setPen(QPen(ink if v == vmax else ink_sub, 1))
            p.drawText(bar_x + bar_w + 6, y, val_w - 6, row,
                       Qt.AlignLeft | Qt.AlignVCenter,
                       str(it.get('sub') or fmt_num_cn(v)))
        p.end()


# ==========================================================================
# 思维导图
# ==========================================================================
class MindMapView(QWidget):
    """自绘思维导图（右侧树形布局）。

    为什么自己画而不是引 QtCharts / graphviz：
      · QtCharts 画不了这种"节点 + 树"的形态
      · graphviz 是外部二进制，打包要多带几十 MB
      实测这套布局在几百个节点下依然流畅，而且能原样导出 PNG / SVG。

    交互：滚轮缩放（以光标为中心）、按住拖动平移、双击适应窗口。
    """

    HGAP = 46          # 层与层之间
    VGAP = 9           # 节点之间
    MAXW = 300         # 单节点最大宽度

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = None
        self.nodes = []
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self._drag = None
        self.setMinimumHeight(320)
        self.setMouseTracking(True)

    # ------------------------------------------------------------ 数据与布局
    def set_tree(self, tree):
        self.tree = tree
        self.relayout()
        self.fit()

    def _text_w(self, text, level):
        per = 14 if level == 0 else (12 if level == 1 else 11.5)
        return min(self.MAXW, max(64, int(18 + len(text or '') * per)))

    def _node_h(self, level):
        return 34 if level == 0 else (28 if level == 1 else 25)

    def _sub_h(self, node):
        kids = node.get('children') or []
        own = node['_h'] + self.VGAP
        if not kids:
            return own
        return max(own, sum(self._sub_h(k) for k in kids))

    def relayout(self):
        self.nodes = []
        if not self.tree:
            self.update()
            return

        def prep(node, level):
            node['_level'] = level
            node['_w'] = self._text_w(node.get('title'), level)
            node['_h'] = self._node_h(level)
            for k in node.get('children') or []:
                prep(k, level + 1)
        prep(self.tree, 0)

        def place(node, x, y_top):
            kids = node.get('children') or []
            if kids:
                total = sum(self._sub_h(k) for k in kids)
                node['_y'] = y_top + (total - node['_h']) / 2.0
            else:
                node['_y'] = y_top
            node['_x'] = x
            self.nodes.append(node)
            cy = y_top
            for k in kids:
                place(k, x + node['_w'] + self.HGAP, cy)
                cy += self._sub_h(k)

        place(self.tree, 0, 0)

    # ---------------------------------------------------------------- 视图
    def content_rect(self):
        if not self.nodes:
            return QRectF(0, 0, 10, 10)
        x0 = min(n['_x'] for n in self.nodes)
        y0 = min(n['_y'] for n in self.nodes)
        x1 = max(n['_x'] + n['_w'] for n in self.nodes)
        y1 = max(n['_y'] + n['_h'] for n in self.nodes)
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def fit(self):
        r = self.content_rect()
        w, h = max(20, r.width()), max(20, r.height())
        sx = (self.width() - 48) / w
        sy = (self.height() - 48) / h
        self.scale = max(0.25, min(1.35, min(sx, sy)))
        self.offset = QPointF(
            (self.width() - w * self.scale) / 2 - r.x() * self.scale,
            (self.height() - h * self.scale) / 2 - r.y() * self.scale)
        self.update()

    def zoom_by(self, factor, center=None):
        old = self.scale
        self.scale = max(0.15, min(3.0, self.scale * factor))
        k = self.scale / old
        c = center or QPointF(self.width() / 2, self.height() / 2)
        self.offset = c - (c - self.offset) * k
        self.update()

    def wheelEvent(self, ev):
        try:
            d = ev.angleDelta().y()
            if d:
                self.zoom_by(1.12 if d > 0 else 1 / 1.12, ev.position())
        except Exception:
            pass

    def mousePressEvent(self, ev):
        self._drag = ev.position()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self.offset += ev.position() - self._drag
            self._drag = ev.position()
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, ev):
        # 兜底不能静默：之前漏 import 一个类，界面直接空白，
        # 却因为 except 把异常吞掉而毫无线索。
        try:
            self._paint()
        except Exception as e:
            print('[MindMapView] paint error: %r' % (e,), file=_sys.stderr)

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._draw(p, self.width(), self.height())

    def _draw(self, p, W, H):
        pal = _PAL
        p.fillRect(0, 0, W, H, QColor(pal.get('card', '#FFFFFF')))
        if not self.nodes:
            p.setPen(QPen(QColor(pal.get('muted', '#8B8FAE')), 1))
            p.drawText(0, 0, W, H, Qt.AlignCenter, '—')
            return

        p.translate(self.offset)
        p.scale(self.scale, self.scale)

        accent = QColor(pal.get('PRIMARY', '#6366F1'))
        accent2 = QColor(pal.get('ACCENT', '#F472B6'))
        ink = QColor(pal.get('ink', '#22203F'))
        ink_sub = QColor(pal.get('ink_sub', '#4A4870'))
        line = QColor(pal.get('line', '#E6E7F4'))

        # 连线先画（压在节点下面）
        by_id = {id(n): n for n in self.nodes}
        p.setBrush(Qt.NoBrush)
        for n in self.nodes:
            for k in (n.get('children') or []):
                if id(k) not in by_id:
                    continue
                x1 = n['_x'] + n['_w']
                y1 = n['_y'] + n['_h'] / 2.0
                x2 = k['_x']
                y2 = k['_y'] + k['_h'] / 2.0
                pen = QPen(line if k['_level'] > 1 else accent, 1.6)
                p.setPen(pen)
                path = QPainterPath(QPointF(x1, y1))
                mx = (x1 + x2) / 2.0
                path.cubicTo(QPointF(mx, y1), QPointF(mx, y2), QPointF(x2, y2))
                p.drawPath(path)

        # 节点
        for n in self.nodes:
            r = QRectF(n['_x'], n['_y'], n['_w'], n['_h'])
            lv = n['_level']
            if lv == 0:
                g = QLinearGradient(r.topLeft(), r.bottomRight())
                g.setColorAt(0.0, accent)
                g.setColorAt(1.0, accent2)
                p.setBrush(g)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(r, 10, 10)
                fg = QColor('#FFFFFF')
            elif lv == 1:
                c = QColor(accent)
                c.setAlpha(34)
                p.setBrush(c)
                p.setPen(QPen(accent, 1.1))
                p.drawRoundedRect(r, 8, 8)
                fg = accent.darker(115)
            else:
                p.setBrush(QColor(pal.get('card', '#FFFFFF')))
                p.setPen(QPen(line, 1))
                p.drawRoundedRect(r, 7, 7)
                fg = ink_sub if n.get('value') else ink

            f = QFont(p.font())
            f.setPixelSize(14 if lv == 0 else (12 if lv == 1 else 11))
            if lv <= 1:
                f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(fg, 1))
            p.drawText(r.adjusted(9, 0, -9, 0), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(n.get('title') or '',
                                                  Qt.ElideRight, int(r.width()) - 16))
        p.resetTransform()
        p.end()

    # ---------------------------------------------------------------- 导出
    def export_image(self, path, fmt='png', margin=28, max_side=6000):
        """导出 PNG 或 SVG。两张走的是同一套绘制代码，所见即所得。"""
        if not self.nodes:
            return False
        r = self.content_rect()
        W = min(max_side, int(r.width() + margin * 2))
        H = min(max_side, int(r.height() + margin * 2))
        if fmt == 'svg':
            try:
                from PySide6.QtSvg import QSvgGenerator
            except Exception:
                return False
            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(W, H))
            gen.setViewBox(QRect(0, 0, W, H))
            gen.setTitle('BookPulse mindmap')
            p = QPainter()
            if not p.begin(gen):
                return False
            p.translate(margin - r.x(), margin - r.y())
            self._draw(p, W, H)
            p.end()
            return True

        img = QImage(W, H, QImage.Format_ARGB32)
        img.fill(QColor(_PAL.get('card', '#FFFFFF')))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(margin - r.x(), margin - r.y())
        self._draw(p, W, H)
        p.end()
        return bool(img.save(path))


# ==========================================================================
# 命令面板（Ctrl+K）
# ==========================================================================
class CommandPalette(QWidget):
    """居中命令面板 —— 「按钮不全堆在左侧」的答案。

    高频入口留在侧栏，低频操作全部收进这里；输入框还能直接当搜索框用，
    敲一个书名回车就等于在搜索页发起搜索。
    """

    chosen = Signal(str)        # 选中了某条命令（传命令 id）
    searched = Signal(str)      # 输入的是书名（传关键词）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('CmdScrim')
        # QWidget 默认不绘制 QSS 的 background —— 不设这个属性，遮罩就是全透明的，
        # 面板会像"浮在白底上"而不是模态弹窗
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()
        self._commands = []     # [(id, 显示文本, 关键字)]
        self._filtered = []
        self._anim = None

        self._build()

        # 【为什么这里没有 QGraphicsOpacityEffect】(2026-10-02 实测踩坑)
        # 原先给本控件挂 OpacityEffect 做淡入、子面板挂 DropShadowEffect 做阴影，
        # 实测会出现：面板打开约 1 秒后背景不再绘制 —— 表现为「命令面板变成透明的」。
        # 定位过程：打开后 300ms 面板中心像素 = #FFFFFF（正常），
        #           2.5s 后同一坐标 = #6F6E7E（遮罩色，即面板背景消失）。
        # 原因是 Qt 在多层级同时使用 graphics effect 时渲染管线会失效。
        # 现在改为：遮罩 alpha 自己动画 + 面板 geometry 上滑 —— 零图形效果，100% 稳定。
        self._scrim_a = 0.0         # 遮罩不透明度 0~1
        self._scrim_anim = None
        self._slide_anim = None

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)

        panel = QFrame()
        panel.setObjectName('CmdPanel')
        apply_shadow(panel, blur=46, dy=14, alpha=70, color='#000000')
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        self.input = QLineEdit()
        self.input.setObjectName('CmdInput')
        self.input.setPlaceholderText('输入命令或书名…')
        self.input.textChanged.connect(self._refilter)
        self.input.returnPressed.connect(self._accept)
        pv.addWidget(self.input)

        self.list = QListWidget()
        self.list.setObjectName('CmdList')
        self.list.itemActivated.connect(lambda _: self._accept())
        pv.addWidget(self.list, 1)

        self.hint = QLabel('↑↓ 选择　·　Enter 执行　·　Esc 关闭')
        self.hint.setObjectName('CmdHint')
        pv.addWidget(self.hint)

        outer.addWidget(panel)
        self.panel = panel
        self._input_ph = '输入命令或书名…'
        self._search_tpl = '搜索这本书：{kw}'

    # ------------------------------------------------------------------
    def set_texts(self, placeholder, hint, search_tpl):
        self._input_ph = placeholder
        self._search_tpl = search_tpl
        self.input.setPlaceholderText(placeholder)
        self.hint.setText(hint)

    def _fit_panel(self):
        """面板尺寸随窗口自适应 —— 写死尺寸会在窄窗口下溢出到角上。"""
        try:
            w = max(340, min(580, self.width() - 48))
            h = max(240, min(400, self.height() - 72))
            self.panel.setFixedSize(w, h)
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_panel()

    # ---- 遮罩不透明度（自绘，可被 QPropertyAnimation 驱动）----
    def _get_scrim(self):
        return self._scrim_a

    def _set_scrim(self, v):
        self._scrim_a = float(v)
        self.update()

    scrimAlpha = Property(float, _get_scrim, _set_scrim)

    def _play_in(self):
        """入场：遮罩淡入 + 面板自上而下轻滑（约 12px）。"""
        if not MOTION:
            self._scrim_a = 1.0
            self.update()
            return
        try:
            a = QPropertyAnimation(self, b'scrimAlpha', self)
            a.setDuration(160)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.start()
            self._scrim_anim = a

            end = self.panel.geometry()
            start = QRect(end.x(), end.y() + 12, end.width(), end.height())
            self.panel.setGeometry(start)
            s = QPropertyAnimation(self.panel, b'geometry', self)
            s.setDuration(190)
            s.setStartValue(start)
            s.setEndValue(end)
            s.setEasingCurve(QEasingCurve.OutCubic)
            s.start()
            self._slide_anim = s
        except Exception as e:
            print('[CommandPalette] 入场动效失败:', e, file=_sys.stderr)
            self._scrim_a = 1.0
            self.update()

    def popup(self, commands):
        """commands: [(id, 显示文本, 关键字)]"""
        self._commands = list(commands)
        self.input.clear()
        self._refilter('')
        par = self.parentWidget()
        if par:
            self.setGeometry(0, 0, par.width(), par.height())
        self._fit_panel()
        self._scrim_a = 0.0
        self.show()
        self.raise_()
        self.input.setFocus()
        self._play_in()

    def close_palette(self):
        if MOTION:
            try:
                a = QPropertyAnimation(self, b'scrimAlpha', self)
                a.setDuration(130)
                a.setStartValue(self._scrim_a)
                a.setEndValue(0.0)
                a.start()
                self._scrim_anim = a
            except Exception:
                pass
            QTimer.singleShot(150, self.hide)
        else:
            self.hide()

    # ------------------------------------------------------------------
    def _refilter(self, text):
        kw = (text or '').strip().lower()
        self.list.clear()
        self._filtered = []
        for cid, label, keys in self._commands:
            if not kw or kw in label.lower() or kw in (keys or '').lower():
                self._filtered.append(cid)
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, cid)
                self.list.addItem(it)
        if self._filtered:
            self.list.setCurrentRow(0)
        elif kw:
            try:
                label = self._search_tpl.format(kw=text.strip())
            except Exception:
                label = text.strip()
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, '__search__')
            self.list.addItem(it)
            self._filtered = ['__search__']
            self.list.setCurrentRow(0)

    def _accept(self):
        kw = self.input.text().strip()
        row = self.list.currentRow()
        if row >= 0:
            it = self.list.item(row)
            cid = it.data(Qt.UserRole)
            self.close_palette()
            if cid == '__search__':
                self.searched.emit(kw)
            else:
                self.chosen.emit(cid)
        elif kw:
            self.close_palette()
            self.searched.emit(kw)

    # ------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close_palette()
        else:
            super().keyPressEvent(ev)

    def paintEvent(self, ev):
        """遮罩自己画 —— 靠 QSS 的 background 在 QWidget 上不可靠，实测会不生效。"""
        try:
            p = QPainter(self)
            rgba = _PAL.get('scrim_rgba') or (20, 18, 45, 97)
            a = int(max(0, min(255, rgba[3] * getattr(self, '_scrim_a', 1.0))))
            p.fillRect(self.rect(), QColor(rgba[0], rgba[1], rgba[2], a))
            p.end()
        except Exception as e:
            print('[CommandPalette] paint error:', e, file=_sys.stderr)

    def mousePressEvent(self, ev):
        # 点空白遮罩处关闭
        if not self.panel.geometry().contains(ev.pos()):
            self.close_palette()
        super().mousePressEvent(ev)
