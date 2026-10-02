# -*- coding: utf-8 -*-
"""
书脉 BookPulse —— 微信读书热门划线工作台（桌面版）
================================================================================
抓取/导出逻辑在 core.py，本地知识库在 store.py，主题在 theme.py，
自定义控件与动效在 widgets.py，多语言在 i18n.py，偏好设置在 settings.py。
本文件只负责「把它们组装成一个好看的界面」。

启动：双击 `启动工作台.bat`
     或   <项目>/.venv/Scripts/python.exe app_gui.py

界面结构
  · 侧栏   —— 高频导航（5 项）+ 导出目录快捷入口
  · 顶栏   —— 命令入口 / 语言切换 / 明暗切换（按钮不集中在左侧）
  · 命令面板 —— Ctrl+K 唤起，低频操作全收在这里
================================================================================
"""
import os
import sys
import time
import random
import ctypes
import datetime
import urllib.request
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core
import store as kb
import theme
import widgets as W
import i18n
import settings
import ai as AIm
import feishu
import watch as WATCH
import merge
import mindmap
import exporters as EX
from i18n import t as T

# 数据与导出目录：开发时装在脚本旁；打包成 exe 后装在 exe 旁（而非临时解包目录）
APP_DIR = core.app_dir()
FALLBACK_DIR = os.path.join(APP_DIR, 'exports')


def export_dir():
    """导出目录：优先用设置里自定义的路径；留空则用程序旁边的 exports/。"""
    d = (settings.get('export_dir') or '').strip()
    return d or FALLBACK_DIR


def cur_mode():
    """当前真正生效的明暗模式（设置里的 'auto' 在这里被解析成 light/dark）。"""
    return theme.resolve_mode(settings.get('mode'))


# 导出模板里可选的标题配色
ACCENT_PRESETS = ['#7C3AED', '#6366F1', '#0EA5E9', '#10B981',
                  '#F59E0B', '#EF4444', '#DB2777', '#334155']


def apply_net_settings():
    """把设置里的网络选项同步给 core（core 不 import settings，保持可独立运行）。"""
    try:
        core.set_net(timeout=int(settings.get('net_timeout') or 25),
                     retries=int(settings.get('net_retries') or 3),
                     proxy=settings.get('net_proxy') or '',
                     proxy_mode=settings.get('net_proxy_mode') or 'direct')
    except Exception:
        pass


def export_style():
    """把设置里的导出模板整理成 core 认识的样子。"""
    return {
        'font_size': int(settings.get('style_font_size') or 15),
        'show_chapter': bool(settings.get('style_show_chapter')),
        'show_index': bool(settings.get('style_show_index')),
        'accent': settings.get('style_accent') or '#7C3AED',
        'line_height': float(settings.get('style_line_height') or 1.8),
    }


def render_pdf(result, with_people=True, style=None):
    """把打印版 HTML 渲染成 PDF —— 用 Qt 自带的 QPdfWriter，零额外依赖。

    不引 reportlab / fpdf 的理由：PySide6 本来就带着完整的排版引擎，
    中文靠系统字体，打包体积一点不涨。
    """
    import tempfile
    from PySide6.QtGui import QPdfWriter, QTextDocument, QPageSize, QPageLayout
    from PySide6.QtCore import QMarginsF, QSizeF

    st = EX.make_style(style)
    html = core.to_print_html(result, with_people, st)

    doc = QTextDocument()
    f = QFont('Microsoft YaHei UI')
    f.setPixelSize(max(9, int(st['font_size'] * 1.05)))
    doc.setDefaultFont(f)
    doc.setHtml(html)

    fd, path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
        writer.setResolution(300)
        doc.setPageSize(QSizeF(writer.width(), writer.height()))
        doc.print_(writer)
        del writer
        with open(path, 'rb') as fp:
            return fp.read()
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QSize, QRectF, QPointF
from PySide6.QtGui import (QDesktopServices, QFont, QIcon, QKeySequence, QShortcut,
                           QPainter, QColor, QPixmap, QPen, QPainterPath,
                           QLinearGradient)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QComboBox,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QFrame, QDialog,
    QHeaderView, QAbstractItemView, QMessageBox, QButtonGroup, QSplitter,
    QSpinBox, QDoubleSpinBox, QCheckBox, QSlider, QCompleter, QFileDialog,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QProgressBar,
    QStyledItemDelegate, QStyle, QMenu, QGraphicsOpacityEffect,
)
from PySide6.QtCore import QPropertyAnimation, QEasingCurve

APP_VERSION = '2.2'


# ==========================================================================
# 回收站删除（遵循「删除走回收站、可恢复」的安全习惯）
# ==========================================================================
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('wFunc', wintypes.UINT),
        ('pFrom', wintypes.LPCWSTR),
        ('pTo', wintypes.LPCWSTR),
        ('fFlags', ctypes.c_uint16),
        ('fAnyOperationsAborted', wintypes.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', wintypes.LPCWSTR),
    ]


def trash(path):
    try:
        op = _SHFILEOPSTRUCTW()
        op.wFunc = 3
        op.pFrom = os.path.abspath(path) + '\0\0'
        op.fFlags = 0x0040 | 0x0010 | 0x0004
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
    except Exception:
        return False


def human_size(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return ('%d B' % n) if u == 'B' else ('%.1f %s' % (n, u))
        n /= 1024.0


def app_name():
    return T('app.name')


# ==========================================================================
# 后台线程
# ==========================================================================
class SearchWorker(QThread):
    ok = Signal(list)
    err = Signal(str)

    def __init__(self, keyword, parent=None):
        super().__init__(parent)
        self.keyword = keyword

    def run(self):
        try:
            self.ok.emit(core.search_books(self.keyword))
        except Exception as e:
            self.err.emit(str(e))


class FetchWorker(QThread):
    ok = Signal(dict)
    err = Signal(str)

    def __init__(self, book, top, parent=None):
        super().__init__(parent)
        self.book, self.top = book, top

    def run(self):
        try:
            self.ok.emit(core.fetch_by_book(self.book, top=self.top))
        except Exception as e:
            self.err.emit(str(e))


class BatchWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    item_ok = Signal(dict)
    done = Signal(list, list, bool)

    def __init__(self, keywords, top, interval, parent=None):
        super().__init__(parent)
        self.keywords, self.top, self.interval = keywords, top, interval
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ok, fail, stopped = core.batch_fetch(
            self.keywords, top=self.top, interval=self.interval,
            on_log=self.log.emit,
            on_start=lambda i, t, kw: self.progress.emit(i, t),
            on_item=self.item_ok.emit,
            should_stop=lambda: self._stop,
        )
        self.done.emit(ok, fail, stopped)


# ==========================================================================
# 小部件工厂
# ==========================================================================
def _tag(text):
    lb = QLabel(text)
    lb.setObjectName('Hint')
    return lb


def _cell(text, center=False):
    it = QTableWidgetItem(str(text))
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    return it


def page_header(title, desc):
    box = QVBoxLayout()
    box.setSpacing(3)
    t = QLabel(title)
    t.setObjectName('PageTitle')
    d = QLabel(desc)
    d.setObjectName('PageDesc')
    d.setWordWrap(True)
    box.addWidget(t)
    box.addWidget(d)
    return box


def card_layout(card, margins=(16, 10, 16, 16), spacing=9):
    v = QVBoxLayout(card)
    v.setContentsMargins(*margins)
    v.setSpacing(spacing)
    return v


def read_title_list(path):
    """从 txt / csv / md 里读出一串书名。

    兼容两种常见写法：
      · 每行一个书名（最省事）
      · CSV 的第一列是书名（自动跳过表头行与序号列）
    去重且保持原顺序。
    """
    out = []
    skip = {'书名', 'title', 'Title', '序号', 'no', 'No', '#', 'id', 'ID'}
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                line = line.strip().strip('"').strip("'").strip()
                if not line:
                    continue
                if ',' in line or '\t' in line:
                    parts = [p.strip().strip('"') for p in
                             (line.split(',') if ',' in line else line.split('\t'))]
                    parts = [p for p in parts if p]
                    if not parts:
                        continue
                    line = parts[0]
                    # 第一列是纯序号、书名在第二列的表格
                    if line.isdigit() and len(parts) > 1:
                        line = parts[1]
                if line in skip:
                    continue
                line = line.lstrip('-*# ').strip()
                if line and line not in out:
                    out.append(line)
    except Exception:
        pass
    return out


class CoverLoader(QThread):
    """后台抓候选书的封面。走磁盘缓存，第二次打开秒出。

    这里有两个曾经的性能坑，都修掉了：
      ① 用裸 urllib.request.urlopen —— 它会自己读系统/环境代理，绕开 core 的
         代理模式设置。代理一挂，每本封面都要等超时，30 本串行 = 几分钟，
         表现就是「左侧书籍列表加载很久」。
      ② 一本一本来 —— 改成 4 路并发，并且把磁盘缓存里的**先一次性全发出去**，
         所以第二次搜同样的词，封面是瞬间出现的。
    """

    one = Signal(str, bytes)

    def __init__(self, books, cache_dir, parent=None):
        super().__init__(parent)
        self.books = books
        self.cache_dir = cache_dir

    def _emit_cached(self, b):
        bid = b.get('bookId') or ''
        path = os.path.join(self.cache_dir, bid + '.img')
        try:
            if os.path.exists(path) and os.path.getsize(path) > 512:
                with open(path, 'rb') as f:
                    self.one.emit(bid, f.read())
                return True
        except Exception:
            pass
        return False

    def _fetch_one(self, b):
        bid = b.get('bookId') or ''
        url = b.get('cover') or ''
        if not bid or not url:
            return
        path = os.path.join(self.cache_dir, bid + '.img')
        try:
            # 走 core 的 opener —— 与主流程用同一套代理设置，不再各自为政
            req = urllib.request.Request(url, headers={'User-Agent': core.UA})
            with core._opener().open(req, timeout=8) as r:
                data = r.read()
            if len(data) < 512:
                return
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
            self.one.emit(bid, data)
        except Exception:
            return          # 封面是锦上添花，失败就跳过

    def run(self):
        todo = []
        for b in self.books:
            if b.get('bookId') and b.get('cover') and not self._emit_cached(b):
                todo.append(b)
        if not todo:
            return
        # 4 路并发；用 ThreadPoolExecutor 保证退出时能干净收尾
        workers = min(4, len(todo))
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(self._fetch_one, b) for b in todo]
                for _ in as_completed(futs):
                    if self.isInterruptionRequested():
                        break
        except Exception:
            for b in todo:          # 兜底：退回串行
                self._fetch_one(b)


class BookItemDelegate(QStyledItemDelegate):
    """搜索结果项自绘：标题一行 + 指标一行。

    为什么要自己画：QListWidget 默认实现遇到长文本会**撑出横向滚动条**
    （「神作 91.4% · 3.0万人评价 · 2537人在读」正好很长），
    导致列表必须左右拖动才能看全。自绘之后宽度永远服从面板，
    超长部分自动省略，鼠标悬停还能看完整 tooltip。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.covers = {}          # bookId → QPixmap（由 SearchPage 灌进来，共享同一份）

    def sizeHint(self, opt, index):
        return QSize(120, 70)

    def paint(self, p, opt, index):
        try:
            self._paint(p, opt, index)
        except Exception as e:
            # 一定要留痕：静默兜底会退化成「列表一片空白」这种极难查的现象
            print('[BookItemDelegate] paint error: %r' % (e,), file=sys.stderr)
            super().paint(p, opt, index)

    def _paint(self, p, opt, index):
        b = index.data(Qt.UserRole) or {}
        if not isinstance(b, dict):
            b = {}
        pal = theme.palette(settings.get('theme'), cur_mode())
        ink = QColor(pal.get('ink', '#22203F'))
        muted = QColor(pal.get('muted', '#8B8FAE'))
        accent = QColor(pal.get('PRIMARY', '#6366F1'))
        hover = QColor(pal.get('hover', '#F1F0FB'))

        selected = bool(opt.state & QStyle.State_Selected)
        is_hover = bool(opt.state & QStyle.State_MouseOver)

        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        r = opt.rect.adjusted(2, 2, -2, -2)

        if selected:
            p.setBrush(QColor(hover.red(), hover.green(), hover.blue(), 235))
            p.setPen(QPen(accent, 1))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(r.left() + 3, r.top() + 10, 3, r.height() - 20, 1.5, 1.5)
        elif is_hover:
            p.setBrush(hover)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, 9, 9)

        # ---- 封面缩略图 ----
        CW, CH = 42, 58
        cx, cy = r.left() + 9, r.top() + (r.height() - CH) / 2.0
        pm = self.covers.get(b.get('bookId') or '')
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx, cy, CW, CH), 6, 6)
        if pm is not None and not pm.isNull():
            p.save()
            p.setClipPath(path)
            scaled = pm.scaled(int(CW * 2), int(CH * 2),
                               Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(cx), int(cy), int(CW), int(CH),
                         scaled, max(0, (scaled.width() - int(CW)) // 2),
                         max(0, (scaled.height() - int(CH)) // 2), int(CW), int(CH))
            p.restore()
        else:
            g = QLinearGradient(cx, cy, cx + CW, cy + CH)
            g.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 46))
            g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 16))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(cx, cy, CW, CH), 6, 6)
            p.setPen(QPen(accent, 1))
            f0 = QFont(p.font())
            f0.setPixelSize(17)
            f0.setBold(True)
            p.setFont(f0)
            p.drawText(QRectF(cx, cy, CW, CH), Qt.AlignCenter,
                       ((b.get('title') or '?')[:1] or '?'))

        x = int(cx + CW + 11)
        w = max(40, int(r.right() - x - 8))

        f1 = QFont(p.font())
        f1.setPixelSize(14)
        f1.setBold(True)
        p.setFont(f1)
        p.setPen(QPen(ink, 1))
        p.drawText(x, r.top() + 11, w, 21, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(b.get('title') or '',
                                              Qt.ElideRight, w))

        f2 = QFont(p.font())
        f2.setPixelSize(11)
        f2.setBold(False)
        p.setFont(f2)
        p.setPen(QPen(muted, 1))
        sub = b.get('author') or '\u2014'
        m = metrics_line(b)
        if m:
            sub += '   ' + m
        p.drawText(x, r.top() + 33, w, 19, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.ElideRight, w))
        p.restore()


def fill_formats(combo, current=None):
    combo.clear()
    for k in core.FORMATS:
        combo.addItem(T('fmt.%s' % k), k)
    combo.addItem(T('search.fmt_all'), '__all__')
    if current:
        i = combo.findData(current)
        if i >= 0:
            combo.setCurrentIndex(i)


def export_result(result, fmt_choice, count=0, min_people=None):
    """统一的导出入口，一次处理三件事：

      ① 条数截取
      ② 人数下限过滤（默认 ≥2 人划线，过滤掉「1 人划线」的噪声）
      ③ 单格式 / 按设置里的多格式一次导出多份

    返回 (导出的文件路径列表, 过滤后的 result)
    """
    r = dict(result)
    if count:
        r['items'] = list(r['items'])[:count]

    mp = settings.get('min_people') if min_people is None else min_people
    r = core.apply_min_people(r, mp)

    if fmt_choice == '__all__':
        fmts = list(settings.get('export_formats') or ['html'])
    else:
        fmts = [fmt_choice or 'html']

    out = export_dir()
    with_people = bool(settings.get('export_people'))
    style = export_style()
    paths = []
    for f in fmts:
        try:
            paths.append(core.export(r, out, f, with_people=with_people, style=style))
        except Exception:
            pass
    return paths, r


def filtered_note(before, after):
    """若因人数下限过滤掉了条目，返回一句说明，否则空串。"""
    try:
        dropped = len(before.get('items') or []) - len(after.get('items') or [])
        if dropped > 0:
            return T('toast.filtered', n=dropped, min=settings.get('min_people'))
    except Exception:
        pass
    return ''


def metrics_line(book):
    """把一本书的可读性指标拼成一行摘要。

    数据全部来自搜索接口本身（零额外请求）：
    评价等级 · 推荐值 · 评价人数 · 在读人数 · 完结状态
    """
    parts = []
    try:
        pct = core.rating_percent(book)
        lbl = (book.get('rating_label') or '').strip()
        if pct:
            parts.append(('%s %s' % (lbl, pct)).strip())
        if book.get('rating_count'):
            parts.append(T('metric.rating_count', n=core.num_fmt(book['rating_count'])))
        if book.get('reading_count'):
            parts.append(T('metric.reading', n=core.num_fmt(book['reading_count'])))
        if book.get('finished'):
            parts.append(T('metric.finished'))
    except Exception:
        pass
    return ' · '.join(parts)


def book_tooltip(book):
    """鼠标悬停时显示的详情：简介 + 出版社。"""
    tip = []
    try:
        if book.get('publisher'):
            tip.append(T('metric.publisher', v=book['publisher']))
        if book.get('intro'):
            tip.append(book['intro'])
    except Exception:
        pass
    return '\n\n'.join(tip)


# ==========================================================================
# 页面 1：搜索下载
# ==========================================================================
class SearchPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.books = []
        self.result = None
        self._sw = None
        self._fw = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)

        root.addLayout(page_header(T('search.title'), T('search.desc')))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.kw = QLineEdit()
        self.kw.setPlaceholderText(T('search.placeholder'))
        self.kw.setMinimumHeight(40)
        self.kw.returnPressed.connect(self.do_search)
        # 搜索历史下拉：输入时会提示以前搜过的词
        self._completer = QCompleter([], self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setMaxVisibleItems(10)
        self.kw.setCompleter(self._completer)
        self.refresh_history()
        self.btn_search = QPushButton(T('search.btn'))
        self.btn_search.setFixedWidth(104)
        self.btn_search.setMinimumHeight(40)
        self.btn_search.clicked.connect(self.do_search)
        row.addWidget(self.kw, 1)
        row.addWidget(self.btn_search)
        root.addLayout(row)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)

        # ---- 左：候选 ----
        left = W.Card()
        lv = card_layout(left)
        lt = QLabel(T('search.candidates'))
        lt.setObjectName('CardTitle')
        lv.addWidget(lt)
        self.list_cand = QListWidget()
        # 自绘每一项：宽度永远服从面板，指标行不再被截断、也不会撑出横向滚动条
        self.list_cand.setItemDelegate(BookItemDelegate(self.list_cand))
        self.list_cand.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_cand.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_cand.setSpacing(2)
        self.list_cand.itemDoubleClicked.connect(lambda _: self.do_fetch())
        self.list_cand.currentRowChanged.connect(
            lambda r: self.btn_fetch.setEnabled(r >= 0))
        lv.addWidget(self.list_cand, 1)
        self._covers = {}
        self._cover_worker = None
        self.list_cand.itemDelegate().covers = self._covers   # delegate 与这里共享同一份
        self.empty_cand = W.EmptyState(T('empty.search_title'), T('empty.search_desc'))
        lv.addWidget(self.empty_cand, 1)
        self.list_cand.hide()
        self.btn_fetch = QPushButton(T('search.fetch'))
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.clicked.connect(self.do_fetch)
        lv.addWidget(self.btn_fetch)

        # ---- 右：详情 ----
        right = W.Card()
        rv = card_layout(right)

        head = QHBoxLayout()
        head.setSpacing(8)
        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        self.lb_cover = QLabel()
        self.lb_cover.setFixedSize(74, 104)
        self.lb_cover.setScaledContents(False)
        self.lb_cover.setAlignment(Qt.AlignCenter)
        self.lb_cover.hide()
        head.addWidget(self.lb_cover)

        self.lb_info = QLabel(T('search.no_result'))
        self.lb_info.setObjectName('Stat')
        self.lb_metrics = QLabel('')
        self.lb_metrics.setObjectName('Hint')
        self.lb_metrics.hide()
        info_box.addWidget(self.lb_info)
        info_box.addWidget(self.lb_metrics)
        head.addLayout(info_box)
        head.addStretch(1)
        rv.addLayout(head)

        # 工具栏拆成两行：上行是「导出前怎么取数」，下行是「拿到结果做什么」。
        # 挤成一行时最后的主按钮会被裁掉（实测过），分开之后每行都松快。
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(_tag(T('search.count')))
        self.cb_top = QComboBox()
        self.cb_top.addItems(['50', '100', '300', T('batch.all')])
        self.cb_top.setFixedWidth(96)
        tools.addWidget(self.cb_top)
        tools.addWidget(_tag(T('search.format')))
        self.cb_fmt = QComboBox()
        fill_formats(self.cb_fmt, settings.get('def_format'))
        self.cb_fmt.setMinimumWidth(150)
        tools.addWidget(self.cb_fmt)

        # 排序方式 —— 直接作用在当前表格上，不另开窗口
        tools.addWidget(_tag(T('search.sort')))
        self.cb_sort = QComboBox()
        self.cb_sort.addItem(T('sort.hot'), 'hot')
        self.cb_sort.addItem(T('sort.chapter'), 'chapter')
        _si = self.cb_sort.findData(settings.get('sort_mode'))
        if _si >= 0:
            self.cb_sort.setCurrentIndex(_si)
        self.cb_sort.setFixedWidth(126)
        self.cb_sort.setToolTip(T('sort.tip'))
        self.cb_sort.currentIndexChanged.connect(self.on_sort_changed)
        tools.addWidget(self.cb_sort)
        tools.addStretch(1)

        # 「打开导出文件夹」从界面左下角搬到这里 —— 它和导出是同一个动作链上的
        self.btn_open = QPushButton('\U0001F4C2  ' + T('search.open_dir'))
        self.btn_open.setProperty('ghost', True)
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self.win.open_export_dir)
        tools.addWidget(self.btn_open)
        rv.addLayout(tools)

        acts = QHBoxLayout()
        acts.setSpacing(8)

        # 去微信读书读这本书：用系统默认浏览器打开**阅读器**页面。
        # 踩过的坑：接口给的 deepLink 是详情页（book-detail），点进去只有简介，
        # 得再点一次「开始阅读」。真正能直接读的是 /web/reader/<infoId> ——
        # 实测该地址 <title> 就是书名，页面含 renderTarget，进去即可点选区域。
        self.btn_weread = QPushButton('\U0001F4D6  ' + T('search.open_in_weread'))
        self.btn_weread.setProperty('flat', True)
        self.btn_weread.setEnabled(False)
        self.btn_weread.clicked.connect(self.open_in_weread)
        self.btn_weread.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_weread.customContextMenuRequested.connect(self._weread_menu)
        acts.addWidget(self.btn_weread)

        self.btn_chapter = QPushButton(T('chapter.btn'))
        self.btn_chapter.setProperty('flat', True)
        self.btn_chapter.setEnabled(False)
        self.btn_chapter.clicked.connect(self.show_chapters)
        acts.addWidget(self.btn_chapter)

        self.btn_map = QPushButton(T('mm.btn'))
        self.btn_map.setProperty('flat', True)
        self.btn_map.setEnabled(False)
        self.btn_map.setToolTip(T('mm.hint'))
        self.btn_map.clicked.connect(self.show_mindmap)
        acts.addWidget(self.btn_map)

        self.btn_ai = QPushButton(T('ai.btn'))
        self.btn_ai.setProperty('flat', True)
        self.btn_ai.setEnabled(False)
        self.btn_ai.setToolTip(T('ai.empty_desc'))
        self.btn_ai.clicked.connect(self.do_ai)
        acts.addWidget(self.btn_ai)

        self.btn_queue = QPushButton(T('search.to_batch'))
        self.btn_queue.setProperty('flat', True)
        self.btn_queue.setEnabled(False)
        self.btn_queue.clicked.connect(self.to_queue)
        acts.addWidget(self.btn_queue)

        self.btn_copy = QPushButton(T('search.copy'))
        self.btn_copy.setProperty('flat', True)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.show_copy_menu)
        acts.addWidget(self.btn_copy)

        acts.addStretch(1)
        self.btn_export = QPushButton(T('search.export'))
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.do_export)
        acts.addWidget(self.btn_export)
        rv.addLayout(acts)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            T('search.col_idx'), T('search.col_chapter'),
            T('search.col_text'), T('search.col_people')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(self.copy_cell)   # 双击一行 = 复制那句话
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_menu)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 148)
        self.table.setColumnWidth(3, 80)
        rv.addWidget(self.table, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([404, 656])
        root.addWidget(split, 1)

        # 条数默认值
        n = settings.get('def_count')
        idx = {50: 0, 100: 1, 300: 2, 0: 3}.get(n, 1)
        self.cb_top.setCurrentIndex(idx)

    # ---------------- 搜索 ----------------
    # ---------------------------------------------------------- 封面
    def load_covers(self, books):
        """后台把候选书的封面抓下来（磁盘缓存在 data/covers）。"""
        try:
            if self._cover_worker and self._cover_worker.isRunning():
                return
            cache = os.path.join(os.path.dirname(kb.DB_PATH), 'covers')
            self._cover_worker = CoverLoader(list(books)[:30], cache, self)
            self._cover_worker.one.connect(self.on_cover)
            self._cover_worker.start()
        except Exception:
            pass

    def on_cover(self, bid, data):
        try:
            pm = QPixmap()
            if pm.loadFromData(data):
                self._covers[bid] = pm
                self.list_cand.viewport().update()
                if self.result and (self.result.get('book') or {}).get('bookId') == bid:
                    self.set_cover(bid)
        except Exception:
            pass

    def set_cover(self, bid):
        pm = self._covers.get(bid)
        if pm is not None and not pm.isNull():
            self.lb_cover.setPixmap(pm.scaled(74, 104, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
            self.lb_cover.show()
        else:
            self.lb_cover.hide()

    def refresh_history(self):
        """刷新搜索框的历史提示词。"""
        try:
            self._completer.model().setStringList(self.win.kb.recent_keywords(15))
        except Exception:
            pass

    def do_search(self):
        kw = self.kw.text().strip()
        if not kw:
            self.kw.setFocus()
            return
        self.btn_search.setEnabled(False)
        self.btn_search.setText(T('search.btn_busy'))
        self.list_cand.clear()
        self.win.toast(T('toast.searching', kw=kw))

        self._sw = SearchWorker(kw, self)
        self._sw.ok.connect(self._on_search_ok)
        self._sw.err.connect(self._on_search_err)
        self._sw.start()

    def _reset_search_btn(self):
        self.btn_search.setEnabled(True)
        self.btn_search.setText(T('search.btn'))

    def _on_search_ok(self, books):
        self._reset_search_btn()
        self.books = books
        if not books:
            self.win.toast(T('toast.no_result'), kind='warn')
            return
        for b in books:
            # 文本留空：内容交给 BookItemDelegate 自绘，
            # 这样才有省略号与「永不横向滚动」的自适应宽度
            it = QListWidgetItem('')
            it.setData(Qt.UserRole, b)
            it.setToolTip(book_tooltip(b))
            self.list_cand.addItem(it)
        self.list_cand.setCurrentRow(0)
        self.list_cand.show()
        self.empty_cand.hide()
        self.load_covers(books)
        self.win.toast(T('toast.found', n=len(books)), kind='ok')
        try:
            self.win.kb.log('search', keyword=self.kw.text().strip(),
                            detail='%d 本候选' % len(books))
        except Exception:
            pass
        self.refresh_history()

    def _on_search_err(self, msg):
        self._reset_search_btn()
        self.win.toast(T('toast.search_fail', msg=msg), kind='warn')

    # ---------------- 抓取 ----------------
    def _top_value(self):
        return [50, 100, 300, 0][self.cb_top.currentIndex()]

    def do_fetch(self):
        row = self.list_cand.currentRow()
        if row < 0:
            return
        book = self.list_cand.item(row).data(Qt.UserRole)
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText(T('search.fetching'))
        self.win.toast(T('toast.fetching', title=book['title']))

        self._fw = FetchWorker(book, top=0, parent=self)
        self._fw.ok.connect(self._on_fetch_ok)
        self._fw.err.connect(self._on_fetch_err)
        self._fw.start()

    def _on_fetch_ok(self, r):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText(T('search.fetch'))
        self.show_result(r)

        sid = None
        try:
            sid = self.win.kb.save(r)
        except Exception:
            pass
        try:
            self.win.kb.log('fetch', book=r.get('book'),
                            detail='%s 条' % r.get('all_count'))
        except Exception:
            pass
        if sid:
            self.win.toast(T('toast.fetch_ok', title=r['book']['title'], n=r['all_count']),
                           kind='ok', hold=3000)
        else:
            self.win.toast(T('toast.fetch_ok_nodb', title=r['book']['title'], n=r['all_count']),
                           kind='warn', hold=3400)
        self.win.refresh_library()

    def _on_fetch_err(self, msg):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText(T('search.fetch'))
        self.win.toast(T('toast.fetch_fail', msg=msg), kind='warn')

    def show_result(self, r, from_cache=False):
        self.result = r
        tag = T('search.offline_tag', time=r.get('fetched_at', '')) if from_cache else ''
        self.lb_info.setText(T('search.info', title=r['book']['title'],
                               author=r['book']['author'] or '—',
                               total=r['total'], tag=tag))
        m = metrics_line(r['book'])
        self.lb_metrics.setText(m)
        self.lb_metrics.setVisible(bool(m))
        self.lb_info.setToolTip(book_tooltip(r['book']))
        self.set_cover((r['book'] or {}).get('bookId') or '')
        self.refresh_table()
        self.btn_export.setEnabled(True)
        self.btn_weread.setEnabled(True)
        self.btn_chapter.setEnabled(True)
        self.btn_ai.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.btn_map.setEnabled(True)

    def _open_url(self, url, tip):
        if not url:
            self.win.toast(T('toast.no_link'), kind='warn')
            return
        try:
            QDesktopServices.openUrl(QUrl(url))
            self.win.toast(tip, kind='ok')
        except Exception as e:
            QMessageBox.warning(self, T('search.open_in_weread'), str(e))

    def open_in_weread(self):
        """在系统默认浏览器里**直接进入阅读界面**。

        登录态由浏览器自己维持 —— 你在浏览器里登录过，打开就是登录状态。
        程序这一侧不发任何带身份的请求，也不读取浏览器的 Cookie。
        """
        if not self.result:
            return
        self._open_url(core.book_reader_url(self.result.get('book') or {}),
                       T('toast.weread_opened'))

    def _weread_menu(self, pos):
        """右键：想看书架详情（简介/评分）时走这里。"""
        if not self.result:
            return
        book = self.result.get('book') or {}
        m = QMenu(self)
        m.addAction(T('search.open_in_weread'),
                    lambda: self._open_url(core.book_reader_url(book),
                                           T('toast.weread_opened')))
        m.addAction(T('search.open_detail'),
                    lambda: self._open_url(core.book_url(book),
                                           T('toast.weread_opened')))
        m.exec(self.btn_weread.mapToGlobal(pos))

    def show_chapters(self):
        if self.result:
            ChapterDialog(self, self.result).exec()

    def show_mindmap(self):
        if not self.result:
            return
        MindMapDialog(self, self.win, result=self.result,
                      title=(self.result.get('book') or {}).get('title') or '').exec()

    def do_ai(self):
        """一键 AI 整理当前这本书（方向 2）。"""
        if not self.result:
            return
        AiDialog(self, self.win, result=self.result, template='digest').exec()

    def to_queue(self):
        """把当前这本书直接送进「批量队列」，省得回批量页再手打一次书名。"""
        if not self.result:
            return
        title = (self.result.get('book') or {}).get('title') or ''
        if not title:
            return
        ed = self.win.page_batch.ed_input
        lines = [x.strip() for x in ed.toPlainText().splitlines() if x.strip()]
        if title not in lines:
            lines.append(title)
            ed.setPlainText('\n'.join(lines))
        self.win.toast(T('toast.queued'), kind='ok')
        self.win.switch_page(1)

    def show_copy_menu(self):
        """复制到剪贴板 —— 很多时候并不想落一个文件，只是要贴到别处。"""
        if not self.result:
            return
        m = QMenu(self)
        a_md = m.addAction(T('search.copy_md'))
        a_txt = m.addAction(T('search.copy_txt'))
        a_json = m.addAction('JSON')
        act = m.exec(self.btn_copy.mapToGlobal(self.btn_copy.rect().bottomLeft()))
        if act is None:
            return
        fmt = 'md' if act is a_md else ('txt' if act is a_txt else 'json')
        wp = bool(settings.get('export_people'))
        try:
            r = core.apply_min_people(self.result, settings.get('min_people'))
            text = core.render(r, fmt, wp)
            QApplication.clipboard().setText(text)
        except Exception as e:
            self.win.toast(str(e), kind='warn')
            return
        self.win.toast(T('toast.copied_md' if fmt == 'md' else 'toast.copied',
                         n=len(text)), kind='ok')

    def table_menu(self, pos):
        """表格右键菜单 —— 比让用户去工具栏找按钮快得多。"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        it = self.table.item(row, 2)
        text = (it.toolTip() or it.text()) if it else ''
        m = QMenu(self)
        a_copy = m.addAction(T('rowmenu.copy'))
        a_chapter = m.addAction(T('rowmenu.copy_chapter')) if self.result else None
        m.addSeparator()
        a_all = m.addAction(T('rowmenu.copy_all'))
        a_map = m.addAction(T('mm.btn')) if self.result else None
        act = m.exec(self.table.viewport().mapToGlobal(pos))
        if act is None:
            return
        if act is a_copy and text:
            QApplication.clipboard().setText(text)
            self.win.toast(T('toast.copied', n=len(text)), kind='ok')
        elif act is a_chapter and self.result:
            uid = (self.result['items'][row].get('chapterUid')
                   if row < len(self.result['items']) else '')
            chap = (self.result.get('chapters') or {}).get(uid) or ''
            lines = [(x.get('markText') or '') for x in self.result['items']
                     if (x.get('chapterUid') or '') == uid]
            QApplication.clipboard().setText('\n'.join(lines))
            self.win.toast(T('toast.copied', n=len('\n'.join(lines))), kind='ok')
        elif act is a_all:
            self.show_copy_menu()
        elif act is a_map:
            self.show_mindmap()

    def copy_cell(self, idx):
        """双击表格里的一行 = 复制那句话（用 tooltip 里的完整原文，不是截断版）。"""
        try:
            it = self.table.item(idx.row(), 2)
            if not it:
                return
            text = it.toolTip() or it.text()
            QApplication.clipboard().setText(text)
            self.win.toast(T('toast.copied', n=len(text)), kind='ok')
        except Exception:
            pass

    def _fill_table(self, items):
        ch = self.result['chapters']
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            text = it.get('markText') or ''
            self.table.setItem(i, 0, _cell(str(i + 1), center=True))
            self.table.setItem(i, 1, _cell(ch.get(it.get('chapterUid'), '')))
            c = _cell(text if len(text) <= 90 else text[:90] + '…')
            c.setToolTip(text)
            self.table.setItem(i, 2, c)
            self.table.setItem(i, 3, _cell(core.num_fmt(it.get('totalCount')), center=True))
        self.table.setUpdatesEnabled(True)

    # ---------------- 排序（表格原地切换，不弹窗）----------------
    def _sorted_items(self, items):
        """按当前排序方式重排，返回新列表（不动原始数据）。

        按热度：划线人数从多到少。接口默认就是这个顺序，这里显式再排一次，
                避免上游顺序变化后行为不一致。
        按章节：按「接口给出的章节次序」分组，章内仍按热度从高到低。

        为什么不用 chapterUid 数值排序：uid 只是章节标识，不保证递增就等于
        阅读顺序。chapters 是按接口返回顺序插入的保序 dict，用它最靠谱。
        """
        out = list(items)
        mode = self.cb_sort.currentData() if hasattr(self, 'cb_sort') else 'hot'
        if mode == 'chapter':
            ch_order = {}
            try:
                for i, uid in enumerate((self.result or {}).get('chapters') or {}):
                    ch_order[uid] = i
            except Exception:
                ch_order = {}
            if not ch_order:      # 兜底：拿不到章节表时退化为按 uid 排序
                for i, uid in enumerate(sorted({it.get('chapterUid') or 0 for it in out})):
                    ch_order[uid] = i
            last = len(ch_order) + 1
            out.sort(key=lambda it: (ch_order.get(it.get('chapterUid'), last),
                                     -int(it.get('totalCount') or 0)))
        else:
            out.sort(key=lambda it: -int(it.get('totalCount') or 0))
        return out

    def on_sort_changed(self):
        try:
            settings.set_value('sort_mode', self.cb_sort.currentData())
        except Exception:
            pass
        self.refresh_table()

    def refresh_table(self):
        """按当前排序方式重填表格（切排序、抓取完成都走这里）。"""
        if not self.result:
            return
        self._fill_table(self._sorted_items(self.result['items'])[:1000])

    # ---------------- 导出 ----------------
    def do_export(self):
        if not self.result:
            return
        fmt = self.cb_fmt.currentData()
        n = self._top_value()
        base = dict(self.result)
        # 导出跟随当前排序 —— 所见即所得，切到「按章节」导出的就是章节顺序
        items = self._sorted_items(base['items'])
        base['items'] = items if not n else items[:n]
        try:
            paths, kept = export_result(base, fmt)
        except Exception as e:
            QMessageBox.warning(self, T('search.export'), str(e))
            return
        if not paths:
            self.win.toast(T('toast.exported', name='—'), kind='warn')
            return
        if fmt and fmt != '__all__':
            settings.set_value('def_format', fmt)
        note = filtered_note(base, kept)
        if len(paths) == 1:
            msg = T('toast.exported', name=os.path.basename(paths[0]))
        else:
            msg = T('toast.exported_multi', n=len(paths))
        self.win.toast(msg + note, kind='ok', hold=3600)
        self.win.kb.log('export', book=base.get('book'),
                        detail='%d 个文件' % len(paths))
        self.win.refresh_exports()
        if settings.get('open_after_export'):
            self.win.open_export_dir()


# ==========================================================================
# 页面 2：批量队列
# ==========================================================================
class BatchPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)
        root.addLayout(page_header(T('batch.title'), T('batch.desc')))

        row = QHBoxLayout()
        row.setSpacing(14)

        left = W.Card()
        lv = card_layout(left)
        lt = QLabel(T('batch.list_title'))
        lt.setObjectName('CardTitle')
        lv.addWidget(lt)
        self.ed_input = QPlainTextEdit()
        self.ed_input.setPlaceholderText(T('batch.placeholder'))
        self.ed_input.setMinimumHeight(170)
        lv.addWidget(self.ed_input, 1)

        g = QGridLayout()
        g.setHorizontalSpacing(9)
        g.setVerticalSpacing(9)
        g.addWidget(_tag(T('batch.per_book')), 0, 0)
        self.sp_top = QSpinBox()
        self.sp_top.setRange(0, 100000)
        self.sp_top.setValue(settings.get('def_count'))
        self.sp_top.setSpecialValueText(T('batch.all'))
        g.addWidget(self.sp_top, 0, 1)
        g.addWidget(_tag(T('batch.format')), 1, 0)
        self.cb_fmt = QComboBox()
        fill_formats(self.cb_fmt, settings.get('def_format'))
        g.addWidget(self.cb_fmt, 1, 1, 1, 2)
        g.addWidget(_tag(T('batch.interval')), 2, 0)
        gap = QHBoxLayout()
        gap.setSpacing(6)
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0.0, 60.0)
        self.sp_min.setSingleStep(0.5)
        self.sp_min.setValue(settings.get('interval_min'))
        self.sp_max = QDoubleSpinBox()
        self.sp_max.setRange(0.0, 120.0)
        self.sp_max.setSingleStep(0.5)
        self.sp_max.setValue(settings.get('interval_max'))
        gap.addWidget(self.sp_min)
        gap.addWidget(_tag('~'))
        gap.addWidget(self.sp_max)
        g.addLayout(gap, 2, 1, 1, 2)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        lv.addLayout(g)

        btns = QHBoxLayout()
        btns.setSpacing(9)
        self.btn_start = QPushButton(T('batch.start'))
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QPushButton(T('batch.stop'))
        self.btn_stop.setProperty('flat', True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_clear = QPushButton(T('batch.clear'))
        self.btn_clear.setProperty('ghost', True)
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_import = QPushButton(T('batch.import'))
        self.btn_import.setProperty('ghost', True)
        self.btn_import.setToolTip(T('batch.drop_hint'))
        self.btn_import.clicked.connect(self.import_file)
        btns.addWidget(self.btn_import)
        btns.addWidget(self.btn_start, 1)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_clear)
        lv.addLayout(btns)
        self.setAcceptDrops(True)   # 书单文件可以直接拖进来

        self.bar = W.SmoothProgress()
        lv.addWidget(self.bar)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)

        tcard = W.Card()
        tv = card_layout(tcard, margins=(14, 12, 14, 14), spacing=8)
        tt = QLabel(T('batch.result'))
        tt.setObjectName('CardTitle')
        tv.addWidget(tt)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            T('batch.col_book'), T('batch.col_status'),
            T('batch.col_count'), T('batch.col_file')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 66)
        tv.addWidget(self.table, 1)
        rv.addWidget(tcard, 3)

        lcard = W.Card()
        lv2 = card_layout(lcard, margins=(14, 12, 14, 14), spacing=8)
        ltt = QLabel(T('batch.log'))
        ltt.setObjectName('CardTitle')
        lv2.addWidget(ltt)
        self.log = QPlainTextEdit()
        self.log.setObjectName('Log')
        self.log.setReadOnly(True)
        self.log.setPlaceholderText(T('batch.log_ph'))
        lv2.addWidget(self.log, 1)
        rv.addWidget(lcard, 2)

        row.addWidget(left, 3)
        row.addWidget(right, 5)
        root.addLayout(row, 1)

    # ------------------------------------------------------------------
    # ---------------------------------------------------------- 书单导入
    def import_file(self):
        """从 txt / csv 导入一串书名 —— 一次抓二十本时手打太痛苦。"""
        f, _ = QFileDialog.getOpenFileName(
            self, T('batch.import'), '',
            T('batch.file_filter'))
        if f:
            self.load_from_path(f)

    def load_from_path(self, path):
        names = read_title_list(path)
        if not names:
            self.win.toast(T('batch.import_empty'), kind='warn')
            return
        cur = [x.strip() for x in self.ed_input.toPlainText().splitlines() if x.strip()]
        merged = cur + [n for n in names if n not in cur]
        self.ed_input.setPlainText('\n'.join(merged))
        self.win.toast(T('batch.imported', n=len(names)), kind='ok')

    def dragEnterEvent(self, ev):
        try:
            if ev.mimeData().hasUrls():
                ev.acceptProposedAction()
        except Exception:
            pass

    def dropEvent(self, ev):
        try:
            for u in ev.mimeData().urls():
                p = u.toLocalFile()
                if p and os.path.isfile(p):
                    self.load_from_path(p)
                    break
        except Exception:
            pass

    def _keywords(self):
        raw = self.ed_input.toPlainText()
        raw = raw.replace('，', '\n').replace(',', '\n').replace('、', '\n')
        out, seen = [], set()
        for line in raw.splitlines():
            s = line.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def clear_all(self):
        self.ed_input.clear()
        self.table.setRowCount(0)
        self.log.clear()
        self.bar.reset()
        self.win.toast(T('toast.cleared'))

    def start(self):
        kws = self._keywords()
        if not kws:
            self.win.toast(T('toast.batch_need_input'), kind='warn')
            return
        a, b = self.sp_min.value(), self.sp_max.value()
        interval = (min(a, b), max(a, b))
        top = self.sp_top.value()

        self.table.setRowCount(0)
        self.log.clear()
        self.bar.reset()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.win.toast(T('toast.batch_start', n=len(kws)))

        self.worker = BatchWorker(kws, top, interval, self)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.on_progress)
        self.worker.item_ok.connect(self.on_item)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.append_log('>> ' + T('batch.stop'))
            self.worker.stop()
            self.btn_stop.setEnabled(False)
            self.win.toast(T('toast.batch_stopping'))

    def on_progress(self, i, total):
        self.bar.slide_to(int((i - 1) * 100 / max(total, 1)))

    def append_log(self, msg):
        self.log.appendPlainText(msg)

    def on_item(self, r):
        row = self.table.rowCount()
        self.table.insertRow(row)
        paths, kept = export_result(r, self.cb_fmt.currentData())
        name = os.path.basename(paths[0]) if paths else '—'
        if len(paths) > 1:
            name = '%s … (+%d)' % (name, len(paths) - 1)
        self.table.setItem(row, 0, _cell('《%s》' % r['book']['title']))
        self.table.setItem(row, 1, _cell(T('batch.status_ok'), center=True))
        self.table.setItem(row, 2, _cell(str(len(kept['items'])), center=True))
        self.table.setItem(row, 3, _cell(name))
        try:
            self.win.kb.log('export', book=r.get('book'),
                            detail='%d 个文件' % len(paths))
        except Exception:
            pass
        self.win.toast(T('toast.exported', name=name), kind='ok')

    def on_done(self, ok, fail, stopped):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if not stopped:
            self.bar.slide_to(100)
        for f in fail:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, _cell('《%s》' % f['keyword']))
            self.table.setItem(row, 1, _cell(T('batch.status_fail'), center=True))
            self.table.setItem(row, 2, _cell('—', center=True))
            self.table.setItem(row, 3, _cell(f['error']))
        self.win.toast(T('toast.batch_done', ok=len(ok), fail=len(fail)),
                       kind='ok' if not fail else 'warn', hold=3200)
        self.win.refresh_exports()
        self.worker = None


# ==========================================================================
# 热度变化对话框
# ==========================================================================
# 图表配色：第一色跟随主题主色，其余为固定辅助色（保证任意主题下都可区分）
CHART_COLORS = ['#6366F1', '#F472B6', '#22D3EE', '#F59E0B', '#10B981', '#A855F7']


class TrendDialog(QDialog):
    def __init__(self, parent, book_title, snaps, rows, book_id=''):
        super().__init__(parent)
        self.setWindowTitle(T('lib.trend_title', title=book_title))
        self.resize(940, 800)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        t = QLabel(T('lib.trend_title', title=book_title))
        t.setObjectName('PageTitle')
        root.addWidget(t)

        if len(snaps) >= 2:
            sub = T('lib.trend_cmp', old=snaps[1]['taken_at'], new=snaps[0]['taken_at'])
        else:
            sub = T('lib.trend_need', n=len(snaps))
        d = QLabel(sub)
        d.setObjectName('PageDesc')
        root.addWidget(d)

        # ---------------- 趋势图表（方向 5）----------------
        series = {}
        if book_id:
            try:
                series = kb.get_store().snap_series(book_id, top=6)
            except Exception:
                series = {}
        labels = series.get('labels') or []

        if len(labels) >= 2:
            card1 = W.Card()
            cv1 = card_layout(card1, margins=(14, 12, 14, 12), spacing=7)
            cv1.addWidget(_tag('%s · %s' % (T('chart.total'),
                                            T('chart.snaps', n=len(labels)))))
            ch1 = W.LineChart()
            ch1.setFixedHeight(170)
            ch1.set_data(labels, [{'name': T('chart.total'),
                                   'points': series.get('totals') or [],
                                   'color': CHART_COLORS[0]}])
            cv1.addWidget(ch1)
            root.addWidget(card1)

            lines = series.get('lines') or []
            if lines:
                card2 = W.Card()
                cv2 = card_layout(card2, margins=(14, 12, 14, 12), spacing=7)
                cv2.addWidget(_tag(T('chart.top_lines')))
                ch2 = W.LineChart()
                ch2.setFixedHeight(226)
                sers = []
                for i, ln in enumerate(lines[:6]):
                    nm = (ln.get('text') or '').strip()[:18]
                    sers.append({'name': nm, 'points': ln.get('points') or [],
                                 'color': CHART_COLORS[i % len(CHART_COLORS)]})
                ch2.set_data(labels, sers)
                cv2.addWidget(ch2)
                root.addWidget(card2)
        elif book_id:
            tip = W.Card()
            tv = card_layout(tip, margins=(14, 12, 14, 12), spacing=5)
            tv.addWidget(_tag(T('chart.need_more')))
            hl = QLabel(T('chart.need_more_desc'))
            hl.setObjectName('Hint')
            hl.setWordWrap(True)
            tv.addWidget(hl)
            root.addWidget(tip)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels([
            T('lib.col_kind'), T('lib.col_change'),
            T('search.col_chapter'), T('search.col_text')])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setShowGrid(False)
        h = table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        table.setColumnWidth(0, 72)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(2, 130)

        if not rows:
            table.setRowCount(1)
            for c in range(3):
                table.setItem(0, c, _cell('—', center=True))
            table.setItem(0, 3, _cell(T('lib.trend_none')))
        else:
            table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                if r['kind'] == 'new':
                    k, chg = T('lib.trend_kind_new'), T('lib.trend_new', n=r['new'])
                else:
                    k, chg = (T('lib.trend_kind_up'),
                              T('lib.trend_up', old=r['old'], new=r['new'], delta=r['delta']))
                table.setItem(i, 0, _cell(k, center=True))
                table.setItem(i, 1, _cell(chg, center=True))
                table.setItem(i, 2, _cell(r.get('chapter') or ''))
                c = _cell((r.get('text') or '')[:110])
                c.setToolTip(r.get('text') or '')
                table.setItem(i, 3, c)
        root.addWidget(table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        b = QPushButton(T('dlg.close'))
        b.setProperty('flat', True)
        b.clicked.connect(self.accept)
        bottom.addWidget(b)
        root.addLayout(bottom)


# ==========================================================================
# 按章节浏览对话框
# ==========================================================================
class ChapterDialog(QDialog):
    """按章节看热门划线。

    两个作用：
      · **章节热度** —— 哪几章最戳人（热度条按该章最热一条划线归一化）
      · **同章共鸣** —— 同一章节里的其他热门划线，就是读者在这个段落里
        共同关注的东西（这是"读者评价"在免登录前提下的最佳替代）
    """

    def __init__(self, parent, result):
        super().__init__(parent)
        self.result = result
        title = result['book']['title']
        self.setWindowTitle(T('chapter.title', title=title))
        self.resize(960, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        t = QLabel(T('chapter.title', title=title))
        t.setObjectName('PageTitle')
        root.addWidget(t)

        groups = core.group_by_chapter(result)
        total_items = sum(g['count'] for g in groups)
        d = QLabel(T('chapter.total', ch=len(groups), n=total_items))
        d.setObjectName('PageDesc')
        root.addWidget(d)

        if not groups:
            empty = W.EmptyState(T('chapter.empty'), '')
            root.addWidget(empty, 1)
        else:
            tree = QTreeWidget()
            tree.setColumnCount(3)
            tree.setHeaderLabels([T('chapter.col_item'), T('chapter.col_heat'),
                                  T('chapter.col_count')])
            tree.setRootIsDecorated(True)
            tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree.setAlternatingRowColors(False)
            h = tree.header()
            h.setSectionResizeMode(0, QHeaderView.Stretch)
            h.setSectionResizeMode(1, QHeaderView.Fixed)
            h.setSectionResizeMode(2, QHeaderView.Fixed)
            tree.setColumnWidth(1, 148)
            tree.setColumnWidth(2, 152)

            for g in groups:
                summary = T('chapter.summary', n=g['count'], avg=core.num_fmt(g['avg']))
                top = QTreeWidgetItem([g['chapter'], '', summary])
                tree.addTopLevelItem(top)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(g['heat'])
                bar.setTextVisible(False)
                bar.setFixedHeight(10)
                tree.setItemWidget(top, 1, bar)
                for i, it in enumerate(g['items'][:80], 1):
                    txt = it.get('markText') or ''
                    child = QTreeWidgetItem([
                        '%d. %s' % (i, txt[:110]), '',
                        core.num_fmt(it.get('totalCount'))])
                    child.setToolTip(0, txt)
                    top.addChild(child)
                top.setExpanded(len(groups) <= 3)
            root.addWidget(tree, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        b = QPushButton(T('dlg.close'))
        b.setProperty('flat', True)
        b.clicked.connect(self.accept)
        bottom.addWidget(b)
        root.addLayout(bottom)


# ==========================================================================
# 使用记录对话框
# ==========================================================================
class HistoryDialog(QDialog):
    """操作时间线：什么时候搜了什么词、抓了哪本书、导出了什么文件。"""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.setWindowTitle(T('hist.title'))
        self.resize(840, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        t = QLabel(T('hist.title'))
        t.setObjectName('PageTitle')
        root.addWidget(t)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            T('col.time'), T('col.action'), T('col.target'), T('col.detail')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 154)
        self.table.setColumnWidth(1, 88)
        self.table.setColumnWidth(3, 190)
        root.addWidget(self.table, 1)

        self.desc = QLabel('')
        self.desc.setObjectName('Hint')
        root.addWidget(self.desc)

        bottom = QHBoxLayout()
        b_open = QPushButton(T('lib.open_data'))
        b_open.setProperty('ghost', True)
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(kb.DB_PATH))))
        b_clear = QPushButton(T('hist.clear'))
        b_clear.setProperty('danger', True)
        b_clear.clicked.connect(self.on_clear)
        b_close = QPushButton(T('dlg.close'))
        b_close.setProperty('flat', True)
        b_close.clicked.connect(self.accept)
        bottom.addWidget(b_open)
        bottom.addWidget(b_clear)
        bottom.addStretch(1)
        bottom.addWidget(b_close)
        root.addLayout(bottom)

        self.refresh()

    def refresh(self):
        rows = self.win.kb.history(200)
        kind_map = {'search': T('hist.search'), 'fetch': T('hist.fetch'),
                    'export': T('hist.export'), 'offline': T('hist.offline')}
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            target = r.get('title') or r.get('keyword') or ''
            if r.get('kind') == 'search':
                target = r.get('keyword') or target
            self.table.setItem(i, 0, _cell(r.get('at') or '', center=True))
            self.table.setItem(i, 1, _cell(kind_map.get(r.get('kind'), r.get('kind') or ''),
                                           center=True))
            self.table.setItem(i, 2, _cell(target))
            self.table.setItem(i, 3, _cell(r.get('detail') or ''))
        self.desc.setText(T('hist.footer', n=len(rows)) if rows else T('hist.empty'))

    def on_clear(self):
        if QMessageBox.question(
                self, T('hist.clear'), T('dlg.clear_text'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.win.kb.clear_history()
        self.refresh()


# ==========================================================================
# 页面 3：本地书库
# ==========================================================================
class LibraryPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._build()
        self.refresh()

    def _metric(self, label):
        card = W.Card(shadow=False)
        card.setObjectName('CardFlat')
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 11, 16, 11)
        v.setSpacing(1)
        lb = QLabel(label)
        lb.setObjectName('MetricLabel')
        val = W.AnimatedNumber(0)
        val.setObjectName('MetricValue')
        v.addWidget(lb)
        v.addWidget(val)
        return card, val

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)
        root.addLayout(page_header(T('lib.title'), T('lib.desc')))

        row = QHBoxLayout()
        row.setSpacing(12)
        c1, self.v_books = self._metric(T('lib.m_books'))
        c2, self.v_marks = self._metric(T('lib.m_marks'))
        c3, self.v_snaps = self._metric(T('lib.m_snaps'))
        c4, self.v_size = self._metric(T('lib.m_size'))
        for c in (c1, c2, c3, c4):
            row.addWidget(c)
        row.addStretch(1)
        root.addLayout(row)

        tools = QHBoxLayout()
        tools.setSpacing(9)
        b1 = QPushButton(T('lib.open'))
        b1.clicked.connect(self.open_preview)
        b2 = QPushButton(T('lib.trend'))
        b2.setProperty('flat', True)
        b2.clicked.connect(self.show_trend)
        b3 = QPushButton(T('lib.refresh'))
        b3.setProperty('ghost', True)
        b3.clicked.connect(self.refresh)
        b4 = QPushButton(T('lib.open_data'))
        b4.setProperty('ghost', True)
        b4.clicked.connect(self.open_data_dir)
        b5 = QPushButton(T('lib.remove'))
        b5.setProperty('danger', True)
        b5.clicked.connect(self.remove_book)
        b6 = QPushButton(T('hist.title'))
        b6.setProperty('flat', True)
        b6.clicked.connect(self.win.show_history)
        b7 = QPushButton(T('insight.add_watch'))
        b7.setProperty('flat', True)
        b7.setToolTip(T('insight.watch_empty_desc'))
        b7.clicked.connect(self.toggle_watch)
        for b in (b1, b2, b3, b4, b6, b7):
            tools.addWidget(b)
        tools.addStretch(1)
        tools.addWidget(b5)
        root.addLayout(tools)

        # 书攒多了就得能找 —— 一个筛选框比来回滚列表快得多
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(T('lib.filter_ph'))
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.setMinimumHeight(34)
        self.ed_filter.textChanged.connect(self.refresh)
        frow.addWidget(self.ed_filter, 1)
        root.addLayout(frow)

        card = W.Card()
        cv = card_layout(card, margins=(14, 14, 14, 14), spacing=8)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            T('lib.col_book'), T('lib.col_author'), T('lib.col_marks'),
            T('lib.col_snaps'), T('lib.col_updated')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(lambda _: self.open_preview())
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        for i in (2, 3, 4):
            h.setSectionResizeMode(i, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 88)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 150)
        cv.addWidget(self.table, 1)
        self.empty = W.EmptyState(T('empty.lib_title'), T('empty.lib_desc'))
        cv.addWidget(self.empty, 1)
        self.empty.hide()
        root.addWidget(card, 1)

        self.hint = QLabel('')
        self.hint.setObjectName('Hint')
        root.addWidget(self.hint)

    # ------------------------------------------------------------------
    def refresh(self):
        books = self.win.kb.books()
        kw = (self.ed_filter.text() if hasattr(self, 'ed_filter') else '').strip().lower()
        if kw:
            books = [b for b in books
                     if kw in (b.get('title') or '').lower()
                     or kw in (b.get('author') or '').lower()]
        self.table.setRowCount(len(books))
        for i, b in enumerate(books):
            it = _cell(b.get('title') or '')
            it.setData(Qt.UserRole, b.get('book_id'))
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, _cell(b.get('author') or ''))
            self.table.setItem(i, 2, _cell(str(b.get('n_marks') or 0), center=True))
            self.table.setItem(i, 3, _cell(str(b.get('snaps') or 0), center=True))
            self.table.setItem(i, 4, _cell(b.get('last_at') or '', center=True))

        if books:
            self.table.show()
            self.empty.hide()
        else:
            self.table.hide()
            self.empty.show()

        st = self.win.kb.stats()
        self.v_books.roll_to(st['books'])
        self.v_marks.roll_to(st['marks'])
        self.v_snaps.roll_to(st['snaps'])
        self.v_size.setText(human_size(st['size']))
        self.hint.setText(T('lib.footer', n=len(books)))

    def _selected(self):
        r = self.table.currentRow()
        if r < 0:
            return None, None
        it = self.table.item(r, 0)
        if not it:
            return None, None
        return it.data(Qt.UserRole), it.text()

    def open_preview(self):
        bid, title = self._selected()
        if not bid:
            self.win.toast(T('toast.pick_book'), kind='warn')
            return
        r = self.win.kb.latest(bid)
        if not r:
            self.win.toast(T('toast.no_local'), kind='warn')
            return
        self.win.page_search.show_result(r, from_cache=True)
        self.win.switch_page(0)
        self.win.toast(T('toast.offline_ok', title=r['book']['title'],
                         n=len(r['items']), time=r['fetched_at']), kind='ok')

    def show_trend(self):
        bid, title = self._selected()
        if not bid:
            self.win.toast(T('toast.pick_book'), kind='warn')
            return
        snaps = self.win.kb.snaps(bid)
        rows = self.win.kb.trend(bid)
        TrendDialog(self, title, snaps, rows, bid).exec()

    def toggle_watch(self):
        """把选中书加入 / 移出关注书单（方向 6）。"""
        bid, title = self._selected()
        if not bid:
            self.win.toast(T('toast.pick_book'), kind='warn')
            return
        w = self.win.watcher
        if w.has(bid):
            w.remove(bid)
            self.win.toast(T('toast.watch_removed', title=title), kind='ok')
        else:
            meta = {}
            for b in self.win.kb.books():
                if b.get('book_id') == bid:
                    meta = b
                    break
            w.add({'bookId': bid, 'title': meta.get('title') or title,
                   'author': meta.get('author') or ''})
            self.win.toast(T('toast.watch_added', title=title), kind='ok')
        try:
            self.win.page_insight.refresh_watch()
        except Exception:
            pass

    def remove_book(self):
        bid, title = self._selected()
        if not bid:
            self.win.toast(T('toast.pick_book'), kind='warn')
            return
        if QMessageBox.question(
                self, T('dlg.confirm_remove'), T('dlg.remove_text', title=title),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if self.win.kb.delete(bid):
            self.refresh()
            self.win.toast(T('toast.removed', title=title), kind='ok')
        else:
            self.win.toast(T('toast.remove_fail'), kind='warn')

    def open_data_dir(self):
        d = os.path.dirname(kb.DB_PATH)
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))


# ==========================================================================
# 后台线程：AI 生成 / 关注检查
# ==========================================================================
class AiWorker(QThread):
    delta = Signal(str)
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, messages, provider, model, key, timeout=180,
                 stream=True, temp=0.5, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.provider = provider
        self.model = model
        self.key = key
        self.timeout = timeout
        self.stream = stream
        self.temp = temp
        self._stop = False

    def stop(self):
        self._stop = True

    def _on_delta(self, piece):
        # 流式请求本身没法中途掐断，所以在回调里主动抛异常来终止
        if self._stop:
            raise AIm.AiError('stopped')
        self.delta.emit(piece)

    def run(self):
        try:
            text = AIm.chat(self.messages, provider=self.provider, model=self.model,
                            key=self.key, timeout=self.timeout,
                            temperature=self.temp,
                            on_delta=self._on_delta if self.stream else None)
            if not self._stop:
                self.ok.emit(text)
        except Exception as e:
            if not self._stop:
                self.err.emit(str(e))


class WatchWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(list)

    def __init__(self, watcher, top=0, gap=3.0, parent=None):
        super().__init__(parent)
        self.watcher = watcher
        self.top = top
        self.gap = gap
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            res = self.watcher.check_all(
                top=self.top, gap=self.gap,
                on_progress=lambda i, t, row: self.progress.emit(i, t, row.get('title') or ''),
                should_stop=lambda: self._stop)
        except Exception:
            res = []
        self.done.emit(res)


# ==========================================================================
# AI 整理对话框（方向 2 / 3）
# ==========================================================================
class AiDialog(QDialog):
    """AI 整理工作台。

    两种用法：
        AiDialog(parent, win, result=r)            # 单本书
        AiDialog(parent, win, results=[r1, r2, …]) # 跨书主题聚合
    """

    saved = Signal()

    def __init__(self, parent, win, result=None, results=None,
                 template='digest', title=''):
        super().__init__(parent)
        self.win = win
        self.result = result
        self.results = list(results) if results else None
        self.worker = None
        self.buf = []
        self.done_text = ''
        # template 既可以是内置模板键，也可以直接是一整段自定义提示词
        # （去重合并等场景会塞进来一段拼好的 prompt）
        if template in AIm.PROMPT_ORDER:
            self.template = template
            self.free_prompt = ''
        else:
            self.template = AIm.PROMPT_ORDER[0]
            self.free_prompt = (template or '').strip()

        if not title:
            if result:
                title = (result.get('book') or {}).get('title') or ''
            elif self.results:
                names = [(r.get('book') or {}).get('title') or '' for r in self.results]
                title = ' + '.join(names[:3]) + (' …' if len(names) > 3 else '')
        self.book_title = title

        self.setWindowTitle(T('ai.title') + ((' · ' + title) if title else ''))
        # 多了「提示词」可编辑框，高度要留够；同时按屏幕可用高度收敛，
        # 免得小屏笔记本上对话框顶出屏幕。
        try:
            scr = QApplication.primaryScreen().availableGeometry()
            self.resize(min(1000, scr.width() - 80), min(880, scr.height() - 90))
        except Exception:
            self.resize(1000, 840)
        self._build()
        self._sync_prompt_preview()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(11)

        head = page_header(T('ai.title'), T('ai.empty_desc'))
        root.addLayout(head)

        # 模板选择
        tpl_row = QHBoxLayout()
        tpl_row.setSpacing(8)
        tpl_row.addWidget(_tag(T('ai.template')))
        self.tpl_group = QButtonGroup(self)
        for i, key in enumerate(AIm.PROMPT_ORDER):
            cfg = AIm.BUILTIN_PROMPTS[key]
            name = cfg['name_zh'] if i18n.is_zh() else cfg['name_en']
            b = QPushButton(name)
            b.setObjectName('ThemeChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(cfg['desc_zh'] if i18n.is_zh() else cfg['desc_en'])
            if key == self.template:
                b.setChecked(True)
            b.clicked.connect(lambda _=False, k=key: self.on_template(k))
            self.tpl_group.addButton(b, i)
            tpl_row.addWidget(b)
        tpl_row.addStretch(1)

        self.lb_meta = QLabel('')
        self.lb_meta.setObjectName('Hint')
        tpl_row.addWidget(self.lb_meta)
        root.addLayout(tpl_row)

        # ---- 提示词：可自由编辑 ----
        # 发给 AI 的内容 = 这里写的话 + 自动附上的划线正文。
        # 就算不写 {content} 占位符也没关系，ai.build_prompt 会自动把正文补在末尾。
        prow = QHBoxLayout()
        prow.setSpacing(8)
        prow.addWidget(_tag(T('ai.prompt_edit')))
        prow.addStretch(1)
        lb_fill = QLabel(T('ai.tpl_fill'))
        lb_fill.setObjectName('Hint')
        prow.addWidget(lb_fill)
        root.addLayout(prow)

        self.ed_prompt = QPlainTextEdit()
        self.ed_prompt.setObjectName('PromptBox')
        self.ed_prompt.setFixedHeight(102)
        self.ed_prompt.setPlaceholderText(T('ai.prompt_ph'))
        self._ptimer = QTimer(self)
        self._ptimer.setSingleShot(True)
        self._ptimer.timeout.connect(self._sync_prompt_preview)
        self.ed_prompt.textChanged.connect(lambda: self._ptimer.start(260))
        self.ed_prompt.setPlainText(self._current_template_text())
        root.addWidget(self.ed_prompt)

        # 送给模型的内容（只读预览 —— 让你看清实际发出去的是什么）
        self.lb_sent = _tag(T('ai.send_to'))
        root.addWidget(self.lb_sent)
        self.ed_sent = QPlainTextEdit()
        self.ed_sent.setReadOnly(True)
        self.ed_sent.setFixedHeight(94)
        self.ed_sent.setObjectName('SendBox')
        root.addWidget(self.ed_sent)

        # 结果
        self.lb_result = _tag(T('ai.result'))
        root.addWidget(self.lb_result)
        self.ed_out = QPlainTextEdit()
        self.ed_out.setReadOnly(True)
        self.ed_out.setPlaceholderText(T('ai.empty_desc'))
        root.addWidget(self.ed_out, 1)

        # 底部
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.lb_state = QLabel(T('ai.empty'))
        self.lb_state.setObjectName('Hint')
        bottom.addWidget(self.lb_state)
        bottom.addStretch(1)

        self.btn_hist = QPushButton(T('ai.history'))
        self.btn_hist.setProperty('ghost', True)
        self.btn_hist.clicked.connect(self.show_history)
        bottom.addWidget(self.btn_hist)

        self.btn_stop = QPushButton(T('ai.stop'))
        self.btn_stop.setProperty('danger', True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_gen)
        bottom.addWidget(self.btn_stop)

        self.btn_copy = QPushButton(T('ai.copy'))
        self.btn_copy.setProperty('flat', True)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_result)
        bottom.addWidget(self.btn_copy)

        self.btn_save = QPushButton(T('ai.save'))
        self.btn_save.setProperty('flat', True)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_note)
        bottom.addWidget(self.btn_save)

        self.btn_go = QPushButton(T('ai.btn'))
        self.btn_go.setObjectName('Primary')
        self.btn_go.clicked.connect(self.start)
        bottom.addWidget(self.btn_go)
        root.addLayout(bottom)

        self._refresh_meta()

    def _refresh_meta(self):
        try:
            cfg = AIm.PROVIDERS.get(settings.get('ai_provider')) or {}
            model = settings.get('ai_model') or cfg.get('model') or ''
            if self.results:
                n = sum(len(r.get('items') or []) for r in self.results)
                scope = T('insight.selected', n=len(self.results))
            else:
                n = len((self.result or {}).get('items') or [])
                scope = (self.result or {}).get('book', {}).get('title') or ''
            self.lb_meta.setText('%s · %s · %d 条' % (cfg.get('label', ''),
                                                      model, min(n, int(settings.get('ai_max_items')))))
        except Exception:
            self.lb_meta.setText('')

    # ------------------------------------------------------------------ 动作
    def on_template(self, key):
        """点模板 = 把模板原文填进提示词框，之后你随便改。"""
        self.template = key
        self.free_prompt = ''
        if hasattr(self, 'ed_prompt'):
            self.ed_prompt.setPlainText(self._current_template_text())
        self._sync_prompt_preview()

    def _custom_prompt(self, key):
        return (settings.get('ai_prompt_%s' % key) or '').strip()

    def _current_template_text(self):
        """提示词框的初始文本：优先用设置里改过的，否则用内置模板原文。"""
        if self.free_prompt:
            return self.free_prompt
        try:
            return (self._custom_prompt(self.template)
                    or AIm.BUILTIN_PROMPTS[self.template]['text'])
        except Exception:
            return ''

    def _sync_prompt_preview(self):
        """把真正要发出去的内容显示出来 —— 不做黑盒。

        组装规则：**提示词框里写的内容** + 自动附上的划线正文。
        你在框里怎么写，AI 就收到什么；没写 {content} 也没关系，
        ai.build_prompt 会把划线正文补在末尾。
        """
        try:
            if not hasattr(self, 'ed_prompt'):
                return
            tpl = self.ed_prompt.toPlainText().strip()
            if self.free_prompt:
                # 纯文本模式：传进来的整段内容已经拼好（含划线），直接发，不再套模板
                text = tpl or self.free_prompt
                self.sent_prompt = text
                self.ed_sent.setPlainText(text)
                return
            if not tpl:
                tpl = AIm.BUILTIN_PROMPTS[self.template]['text']
            if self.results:
                text = AIm.build_prompt(tpl, results=self.results,
                                        max_items=int(settings.get('ai_max_items')))
            else:
                text = AIm.build_prompt(tpl, result=self.result,
                                        max_items=int(settings.get('ai_max_items')))
            self.sent_prompt = text
            self.ed_sent.setPlainText(text)
        except Exception as e:
            self.ed_sent.setPlainText('（组装失败：%s）' % e)

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        provider = settings.get('ai_provider')
        key = settings.get('ai_key_%s' % provider) or ''
        cfg = AIm.PROVIDERS.get(provider) or {}
        if cfg.get('need_key') and not key:
            QMessageBox.information(self, T('ai.title'), T('ai.need_key'))
            return

        self._sync_prompt_preview()
        messages = [{'role': 'user', 'content': self.sent_prompt}]
        self.buf = []
        self.done_text = ''
        self.ed_out.setPlainText('')
        self.lb_state.setText(T('ai.streaming'))
        self.btn_go.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)

        self.worker = AiWorker(
            messages, provider, settings.get('ai_model') or '',
            key, timeout=int(settings.get('ai_timeout')),
            stream=bool(settings.get('ai_stream')),
            temp=float(settings.get('ai_temp')), parent=self)
        self.worker.delta.connect(self.on_delta)
        self.worker.ok.connect(self.on_ok)
        self.worker.err.connect(self.on_err)
        self.worker.start()

    def on_delta(self, piece):
        self.buf.append(piece)
        self.ed_out.setPlainText(''.join(self.buf))
        self.ed_out.verticalScrollBar().setValue(
            self.ed_out.verticalScrollBar().maximum())

    def on_ok(self, text):
        self.done_text = text or ''.join(self.buf)
        if not self.ed_out.toPlainText().strip():
            self.ed_out.setPlainText(self.done_text)
        self.lb_state.setText('%s · %s' % (T('ai.done'),
                                          T('ai.word_count', n=len(self.done_text))))
        self._finish()
        self.save_note(silent=True)

    def on_err(self, msg):
        if msg == 'stopped':
            self.lb_state.setText(T('ai.stop'))
        else:
            self.lb_state.setText('%s：%s' % (T('ai.failed'), msg))
        self._finish()

    def _finish(self):
        self.btn_go.setEnabled(True)
        self.btn_stop.setEnabled(False)
        has = bool(self.ed_out.toPlainText().strip())
        self.btn_copy.setEnabled(has)
        self.btn_save.setEnabled(has)

    def stop_gen(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lb_state.setText(T('ai.stop'))

    def copy_result(self):
        try:
            QApplication.clipboard().setText(self.ed_out.toPlainText())
            self.win.toast(T('ai.copied'), kind='ok')
        except Exception:
            pass

    def save_note(self, silent=False, _=None):
        text = self.ed_out.toPlainText().strip()
        if not text:
            return
        kind = 'theme' if self.results else self.template
        ids = ([r.get('book', {}).get('bookId') for r in self.results]
               if self.results else
               [(self.result or {}).get('book', {}).get('bookId')])
        try:
            self.win.kb.save_ai(kind, text, title=self.book_title,
                                prompt=self.sent_prompt[:2000],
                                provider=settings.get('ai_provider'),
                                model=settings.get('ai_model') or '',
                                book_ids=[i for i in ids if i])
        except Exception:
            return
        if not silent:
            self.win.toast(T('toast.ai_saved'), kind='ok')
        self.saved.emit()

    def show_history(self):
        AiHistoryDialog(self, self.win).exec()

    def closeEvent(self, ev):
        try:
            if self.worker and self.worker.isRunning():
                self.worker.stop()
                self.worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(ev)


class AiHistoryDialog(QDialog):
    """历史整理记录：左列表 + 右内容。"""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.setWindowTitle(T('ai.history'))
        self.resize(900, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(11)
        root.addLayout(page_header(T('ai.history'), T('ai.empty_desc')))

        body = QHBoxLayout()
        body.setSpacing(12)

        self.list = QListWidget()
        self.list.setObjectName('Cand')
        self.list.setFixedWidth(300)
        self.list.currentRowChanged.connect(self.on_pick)
        body.addWidget(self.list)

        right = QVBoxLayout()
        self.ed = QPlainTextEdit()
        self.ed.setReadOnly(True)
        right.addWidget(self.ed, 1)
        self.lb = QLabel('')
        self.lb.setObjectName('Hint')
        right.addWidget(self.lb)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.lb_empty = QLabel(T('ai.no_history'))
        self.lb_empty.setObjectName('Hint')
        bottom.addWidget(self.lb_empty)
        bottom.addStretch(1)
        b_del = QPushButton(T('set.clear_cache'))
        b_del.setProperty('danger', True)
        b_del.clicked.connect(self.on_delete)
        bottom.addWidget(b_del)
        b_c = QPushButton(T('dlg.close'))
        b_c.setProperty('flat', True)
        b_c.clicked.connect(self.accept)
        bottom.addWidget(b_c)
        root.addLayout(bottom)

        self.rows = []
        self.refresh()

    def refresh(self):
        self.list.clear()
        self.rows = self.win.kb.ai_history(limit=300)
        if not self.rows:
            self.lb_empty.setText(T('ai.no_history'))
            return
        self.lb_empty.setText('')
        for r in self.rows:
            kind = r.get('kind') or ''
            name = kind
            if kind in AIm.BUILTIN_PROMPTS:
                name = (AIm.BUILTIN_PROMPTS[kind]['name_zh'] if i18n.is_zh()
                        else AIm.BUILTIN_PROMPTS[kind]['name_en'])
            it = QListWidgetItem('%s  ·  %s\n%s' % (name, r.get('at') or '',
                                                    (r.get('title') or '')[:26]))
            it.setData(Qt.UserRole, r.get('id'))
            self.list.addItem(it)

    def on_pick(self, row):
        if row < 0 or row >= len(self.rows):
            return
        rec = self.win.kb.ai_get(self.rows[row]['id'])
        if not rec:
            return
        self.ed.setPlainText(rec.get('content') or '')
        self.lb.setText('%s · %s · %s · %s' % (
            rec.get('at', ''), rec.get('provider') or '', rec.get('model') or '',
            T('ai.word_count', n=len(rec.get('content') or ''))))

    def on_delete(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.rows):
            return
        self.win.kb.ai_delete(self.rows[row]['id'])
        self.win.toast(T('ai.deleted'), kind='ok')
        self.refresh()


class MindMapDialog(QDialog):
    """思维导图：书 → 章节 → 划线，支持缩放平移与多格式导出。"""

    def __init__(self, parent, win, result=None, tree=None, title=''):
        super().__init__(parent)
        self.win = win
        self.result = result
        if tree is None and result is not None:
            tree = mindmap.build_from_result(result)
        self.tree = tree or {'title': title or '', 'children': []}
        self.setWindowTitle(T('mm.title') + ((' · ' + title) if title else ''))
        self.resize(1180, 800)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        lb = QLabel(T('mm.title'))
        lb.setObjectName('PageTitle')
        head.addWidget(lb)
        c, l, _ = mindmap.stats(self.tree)
        self.lb_stat = QLabel(T('mm.stat', c=c, l=l))
        self.lb_stat.setObjectName('Hint')
        head.addWidget(self.lb_stat)
        head.addStretch(1)

        for text, fn, prop in (
                (T('mm.zoom_out'), lambda: self.view.zoom_by(1 / 1.2), 'ghost'),
                (T('mm.zoom_in'), lambda: self.view.zoom_by(1.2), 'ghost'),
                (T('mm.fit'), self.view_fit, 'flat'),
                (T('mm.png'), lambda: self.export_img('png'), 'flat'),
                (T('mm.svg'), lambda: self.export_img('svg'), 'flat'),
                (T('mm.outline'), self.export_outline, 'flat')):
            b = QPushButton(text)
            b.setProperty(prop, True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)

        self.view = W.MindMapView()
        self.view.set_tree(self.tree)
        root.addWidget(self.view, 1)

        hint = QLabel(T('mm.hint'))
        hint.setObjectName('Hint')
        root.addWidget(hint)

    def view_fit(self):
        self.view.fit()

    def export_img(self, fmt):
        if not self.view.nodes:
            self.win.toast(T('mm.no_data'), kind='warn')
            return
        default = os.path.join(export_dir(), '%s-思维导图.%s' % (
            core.safe_filename(self.tree.get('title') or 'book'), fmt))
        path, _ = QFileDialog.getSaveFileName(
            self, T('mm.' + fmt), default, '*.%s' % fmt)
        if not path:
            return
        ok = self.view.export_image(path, fmt)
        if ok:
            self.win.toast(T('mm.saved', name=os.path.basename(path)), kind='ok')
            self.win.refresh_exports()
        else:
            self.win.toast(T('mm.no_data'), kind='warn')

    def export_outline(self):
        default = os.path.join(export_dir(), '%s-大纲.md' % core.safe_filename(
            self.tree.get('title') or 'book'))
        path, sel = QFileDialog.getSaveFileName(
            self, T('mm.outline'), default, T('mm.outline_filter'))
        if not path:
            return
        try:
            if path.lower().endswith('.opml'):
                text = mindmap.to_opml(self.tree)
            else:
                text = mindmap.to_markdown_outline(self.tree)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as e:
            QMessageBox.warning(self, T('mm.outline'), str(e))
            return
        self.win.toast(T('mm.saved', name=os.path.basename(path)), kind='ok')


class DedupeDialog(QDialog):
    """跨书去重合并 —— 把不同书里说同一件事的句子归到一起。"""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.groups = []
        self.rows = []
        self.setWindowTitle(T('dedupe.title'))
        self.resize(1020, 740)
        self._build()
        QTimer.singleShot(100, self.run_analysis)

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(11)
        root.addLayout(page_header(T('dedupe.title'), T('dedupe.desc')))

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_tag(T('dedupe.threshold')))
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(35, 75)          # 0.35 ~ 0.75
        self.sl.setValue(int(float(settings.get('dedupe_threshold') or 0.52) * 100))
        self.sl.setFixedWidth(190)
        self.sl.valueChanged.connect(self._on_slider)
        row.addWidget(self.sl)
        self.lb_th = QLabel('')
        self.lb_th.setObjectName('Hint')
        self.lb_th.setMinimumWidth(84)
        row.addWidget(self.lb_th)
        row.addStretch(1)
        self.lb_stat = QLabel('')
        self.lb_stat.setObjectName('Hint')
        row.addWidget(self.lb_stat)
        self.btn_run = QPushButton(T('dedupe.run'))
        self.btn_run.setObjectName('Primary')
        self.btn_run.clicked.connect(self.run_analysis)
        row.addWidget(self.btn_run)
        root.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([T('dedupe.col_group'), T('dedupe.col_books')])
        self.tree.setColumnWidth(0, 640)
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(True)
        root.addWidget(self.tree, 1)

        self.lb_empty = QLabel(T('dedupe.empty_desc'))
        self.lb_empty.setObjectName('Hint')
        self.lb_empty.setWordWrap(True)
        root.addWidget(self.lb_empty)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addStretch(1)
        b_ai = QPushButton(T('dedupe.ai'))
        b_ai.setProperty('flat', True)
        b_ai.clicked.connect(self.send_ai)
        bottom.addWidget(b_ai)
        b_copy = QPushButton(T('dedupe.copy'))
        b_copy.setProperty('flat', True)
        b_copy.clicked.connect(self.copy_md)
        bottom.addWidget(b_copy)
        b_exp = QPushButton(T('dedupe.export'))
        b_exp.setObjectName('Primary')
        b_exp.clicked.connect(self.export_md)
        bottom.addWidget(b_exp)
        b_close = QPushButton(T('dlg.close'))
        b_close.setProperty('flat', True)
        b_close.clicked.connect(self.accept)
        bottom.addWidget(b_close)
        root.addLayout(bottom)
        self._on_slider(self.sl.value())

    def _on_slider(self, v):
        self.lb_th.setText(('%.2f  ' % (v / 100.0))
                           + (T('dedupe.loose') if v < 48 else
                              (T('dedupe.strict') if v > 60 else '')))

    # ------------------------------------------------------------------
    def run_analysis(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.rows = self.win.kb.all_latest_marks(min_people=2)
            th = self.sl.value() / 100.0
            settings.set_value('dedupe_threshold', th)
            self.groups = merge.similar_groups(self.rows, threshold=th, min_len=8)
        except Exception as e:
            self.rows, self.groups = [], []
            self.lb_stat.setText(str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self._fill()

    def _fill(self):
        self.tree.clear()
        total, merged, ratio = merge.dedup_ratio(self.rows, self.groups)
        self.lb_stat.setText(T('dedupe.stat', n=total, g=len(self.groups),
                               p='%.1f' % (ratio * 100)))
        if not self.groups:
            self.lb_empty.setText(T('dedupe.empty') + ' · ' + T('dedupe.empty_desc'))
            return
        self.lb_empty.setText(T('dedupe.empty_desc'))
        for i, g in enumerate(self.groups, 1):
            rep = (g['rep'] or '').strip()
            top = QTreeWidgetItem(['%d.  %s' % (i, rep[:110]),
                                   T('dedupe.group_info', b=g['books'], n=g['size'],
                                     top=g['top'])])
            top.setToolTip(0, rep)
            self.tree.addTopLevelItem(top)
            for r in g['items']:
                child = QTreeWidgetItem(['　　《%s》%s' % (
                    (r.get('title') or '')[:16],
                    ('· ' + (r.get('chapter') or '')) if r.get('chapter') else ''),
                    (r.get('text') or '')[:120]])
                child.setToolTip(1, r.get('text') or '')
                top.addChild(child)
        self.tree.expandToDepth(0)

    # ------------------------------------------------------------------
    def _md(self):
        return merge.to_markdown(self.groups, book_count=len(
            {r['book_id'] for r in self.rows}), threshold=self.sl.value() / 100.0)

    def copy_md(self):
        if not self.groups:
            return
        QApplication.clipboard().setText(self._md())
        self.win.toast(T('toast.copied', n=len(self._md())), kind='ok')

    def export_md(self):
        if not self.groups:
            return
        try:
            path = core.export_text(self._md(), export_dir(),
                                    '%s-跨书合并' % time.strftime('%Y%m%d'),
                                    '.md')
        except Exception as e:
            QMessageBox.warning(self, T('dedupe.export'), str(e))
            return
        self.win.toast(T('toast.exported', name=os.path.basename(path)), kind='ok',
                       hold=3200)
        self.win.refresh_exports()

    def send_ai(self):
        """把这些「被多本书共同强调的观点」交给 AI 做进一步归纳。"""
        if not self.groups:
            return
        md = self._md()
        prompt = (
            '下面是「多本书里被反复强调、说法相近」的观点，已按共同出现次数归好组。\n\n'
            '请做三件事：\n'
            '1. 把每组归纳成一句更凝练的观点（不要照抄原文）\n'
            '2. 标出哪 5 组最重要，并说明理由\n'
            '3. 指出哪些组之间其实还在讲同一件事，建议进一步合并\n'
            '用 Markdown 输出，不要开场白。\n\n' + md)
        dlg = AiDialog(self, self.win, result=None,
                       template=prompt, title=T('dedupe.title'))
        dlg.exec()


class PromptDialog(QDialog):
    """提示词编辑器 —— 让「AI 怎么整理」变成用户可改的东西，而不是黑盒。"""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.setWindowTitle(T('set.ai_prompt'))
        self.resize(960, 660)
        self.cur = AIm.PROMPT_ORDER[0]

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(11)
        root.addLayout(page_header(T('set.ai_prompt'), T('set.ai_prompt_hint')))

        body = QHBoxLayout()
        body.setSpacing(12)

        self.list = QListWidget()
        self.list.setObjectName('Cand')
        self.list.setFixedWidth(212)
        for key in AIm.PROMPT_ORDER:
            cfg = AIm.BUILTIN_PROMPTS[key]
            name = cfg['name_zh'] if i18n.is_zh() else cfg['name_en']
            desc = cfg['desc_zh'] if i18n.is_zh() else cfg['desc_en']
            it = QListWidgetItem('%s\n%s' % (name, desc[:20]))
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self.on_pick)
        body.addWidget(self.list)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.ed = QPlainTextEdit()
        right.addWidget(self.ed, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        hint = QLabel('{title}  {author}  {content}')
        hint.setObjectName('Hint')
        row.addWidget(hint)
        row.addStretch(1)
        b_r = QPushButton(T('set.ai_prompt_reset'))
        b_r.setProperty('ghost', True)
        b_r.clicked.connect(self.on_reset)
        row.addWidget(b_r)
        b_s = QPushButton(T('ai.save'))
        b_s.setObjectName('Primary')
        b_s.clicked.connect(self.on_save)
        row.addWidget(b_s)
        right.addLayout(row)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        b_c = QPushButton(T('dlg.close'))
        b_c.setProperty('flat', True)
        b_c.clicked.connect(self.accept)
        bottom.addWidget(b_c)
        root.addLayout(bottom)

        # 放在最后：setCurrentRow 会立刻触发 on_pick，此时编辑器必须已存在
        self.list.setCurrentRow(0)

    def on_pick(self, row):
        if row < 0 or not hasattr(self, 'ed'):
            return
        self.cur = self.list.item(row).data(Qt.UserRole)
        custom = (settings.get('ai_prompt_%s' % self.cur) or '').strip()
        self.ed.setPlainText(custom or AIm.BUILTIN_PROMPTS[self.cur]['text'])

    def on_reset(self):
        self.ed.setPlainText(AIm.BUILTIN_PROMPTS[self.cur]['text'])
        settings.set_value('ai_prompt_%s' % self.cur, '')
        self.win.toast(T('set.ai_prompt_reset'), kind='ok')

    def on_save(self):
        text = self.ed.toPlainText().strip()
        builtin = AIm.BUILTIN_PROMPTS[self.cur]['text'].strip()
        settings.set_value('ai_prompt_%s' % self.cur, '' if text == builtin else text)
        self.win.toast(T('set.saved'), kind='ok')


# ==========================================================================
# 页面 4：洞察台（跨书检索 / 主题聚合 / 关注推送）
# ==========================================================================
class InsightPage(QWidget):
    """三合一洞察台。

    设计取舍：这三个功能彼此独立、但都建立在「本地书库」之上，
    做成三个标签而不是三个独立页面 —— 侧栏已经够长了，
    而它们的使用节奏是"打开一次连着用"。
    """

    TABS = ['insight.tab_search', 'insight.tab_theme', 'insight.tab_watch']

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.watcher = win.watcher
        self.watch_worker = None
        self.last_results = []
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)
        root.addLayout(page_header(T('insight.title'), T('insight.desc')))

        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        for i, key in enumerate(self.TABS):
            b = QPushButton(T(key))
            b.setObjectName('ThemeChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            b.clicked.connect(lambda _=False, k=i: self.switch_tab(k))
            self.tab_group.addButton(b, i)
            tabs.addWidget(b)
        tabs.addStretch(1)
        b_dd = QPushButton(T('dedupe.btn'))
        b_dd.setProperty('ghost', True)
        b_dd.setCursor(Qt.PointingHandCursor)
        b_dd.clicked.connect(lambda: DedupeDialog(self, self.win).exec())
        tabs.addWidget(b_dd)
        root.addLayout(tabs)

        self.stack = W.FadeStack()
        self.stack.addWidget(self._build_search())
        self.stack.addWidget(self._build_theme())
        self.stack.addWidget(self._build_watch())
        root.addWidget(self.stack, 1)

    # ---------------------------------------------------------- 标签 1：检索
    def _build_search(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(11)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_kw = QLineEdit()
        self.ed_kw.setPlaceholderText(T('insight.search_ph'))
        self.ed_kw.setMinimumHeight(40)
        self.ed_kw.returnPressed.connect(self.do_search)
        row.addWidget(self.ed_kw, 1)
        b = QPushButton(T('insight.search_btn'))
        b.setObjectName('Primary')
        b.clicked.connect(self.do_search)
        row.addWidget(b)
        v.addLayout(row)

        self.lb_hits = QLabel(T('insight.only_cached'))
        self.lb_hits.setObjectName('Hint')
        v.addWidget(self.lb_hits)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels([
            T('search.col_title'), T('search.col_chapter'),
            T('search.col_people'), T('search.col_text')])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setShowGrid(False)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 190)
        self.tbl.setColumnWidth(1, 130)
        self.tbl.setColumnWidth(2, 90)
        self.tbl.hide()

        self.empty_search = W.EmptyState(T('insight.search_empty'),
                                         T('insight.search_empty_desc'))
        v.addWidget(self.tbl, 1)
        v.addWidget(self.empty_search, 1)
        return page

    def do_search(self):
        kw = self.ed_kw.text().strip()
        if not kw:
            self.win.toast(T('insight.search_ph'), kind='warn')
            return
        rows = self.win.kb.search_marks(kw, limit=400,
                                        min_people=settings.get('min_people'))
        self.show_hits(rows, kw)

    def show_hits(self, rows, kw):
        if not rows:
            self.lb_hits.setText(T('insight.no_hit', kw=kw))
            self.tbl.hide()
            self.empty_search.show()
            return
        n_books = len(set(r.get('book_id') for r in rows))
        self.lb_hits.setText(T('insight.hits', n=len(rows), b=n_books))
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            it = _cell(r.get('title') or '')
            it.setToolTip(r.get('author') or '')
            self.tbl.setItem(i, 0, it)
            self.tbl.setItem(i, 1, _cell(r.get('chapter') or ''))
            self.tbl.setItem(i, 2, _cell(str(r.get('people') or 0), center=True))
            c = _cell((r.get('text') or '')[:130])
            c.setToolTip(r.get('text') or '')
            self.tbl.setItem(i, 3, c)
        self.empty_search.hide()
        self.tbl.show()

    # ---------------------------------------------------------- 标签 2：聚合
    def _build_theme(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(11)

        top = QHBoxLayout()
        top.setSpacing(8)
        hint = QLabel(T('insight.pick_hint'))
        hint.setObjectName('Hint')
        top.addWidget(hint)
        top.addStretch(1)
        b_all = QPushButton(T('insight.select_all'))
        b_all.setProperty('ghost', True)
        b_all.clicked.connect(lambda: self._check_all(True))
        top.addWidget(b_all)
        b_none = QPushButton(T('insight.select_none'))
        b_none.setProperty('ghost', True)
        b_none.clicked.connect(lambda: self._check_all(False))
        top.addWidget(b_none)
        v.addLayout(top)

        self.list_books = QListWidget()
        self.list_books.setObjectName('Cand')
        self.list_books.itemChanged.connect(self._on_pick_changed)
        v.addWidget(self.list_books, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.lb_sel = QLabel(T('insight.selected', n=0))
        self.lb_sel.setObjectName('Hint')
        bottom.addWidget(self.lb_sel)
        bottom.addStretch(1)
        b_agg = QPushButton(T('insight.aggregate'))
        b_agg.setObjectName('Primary')
        b_agg.clicked.connect(self.do_aggregate)
        bottom.addWidget(b_agg)
        v.addLayout(bottom)
        return page

    def refresh_theme(self):
        self.list_books.blockSignals(True)
        self.list_books.clear()
        for b in self.win.kb.books():
            it = QListWidgetItem('%s\n%s · %s 条' % (
                b.get('title') or '', b.get('author') or '—', b.get('n_marks') or 0))
            it.setData(Qt.UserRole, b.get('book_id'))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.list_books.addItem(it)
        self.list_books.blockSignals(False)
        self._on_pick_changed()

    def _check_all(self, on):
        self.list_books.blockSignals(True)
        for i in range(self.list_books.count()):
            self.list_books.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list_books.blockSignals(False)
        self._on_pick_changed()

    def _picked(self):
        out = []
        for i in range(self.list_books.count()):
            it = self.list_books.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _on_pick_changed(self, *_):
        self.lb_sel.setText(T('insight.selected', n=len(self._picked())))

    def do_aggregate(self):
        ids = self._picked()
        if len(ids) < 2:
            self.win.toast(T('insight.need_two'), kind='warn')
            return
        data = self.win.kb.marks_for_books(ids, per_book=60, min_people=2)
        results = []
        for bid, d in (data or {}).items():
            ch_map, name2uid, items = {}, {}, []
            for it in d.get('items') or []:
                cname = it.get('chapter') or '—'
                if cname not in name2uid:
                    uid = 'c%d' % len(name2uid)
                    name2uid[cname] = uid
                    ch_map[uid] = cname
                items.append({'chapterUid': name2uid[cname],
                              'markText': it.get('text') or '',
                              'totalCount': it.get('people') or 0})
            if not items:
                continue
            results.append({
                'book': {'bookId': bid, 'title': d.get('title') or '',
                         'author': d.get('author') or ''},
                'items': items, 'chapters': ch_map,
                'total': len(items), 'all_count': len(items),
                'fetched_at': '', 'from_cache': True,
            })
        if len(results) < 2:
            self.win.toast(T('lib.no_data_short'), kind='warn')
            return
        AiDialog(self, self.win, results=results, template='theme').exec()

    # ---------------------------------------------------------- 标签 3：关注
    def _build_watch(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(11)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.lb_last = QLabel(T('insight.never_check'))
        self.lb_last.setObjectName('Hint')
        top.addWidget(self.lb_last)
        top.addStretch(1)
        self.btn_push = QPushButton(T('insight.push_now'))
        self.btn_push.setProperty('flat', True)
        self.btn_push.clicked.connect(lambda: self.push_feishu(False))
        top.addWidget(self.btn_push)
        self.btn_check = QPushButton(T('insight.check_now'))
        self.btn_check.setObjectName('Primary')
        self.btn_check.clicked.connect(self.do_check)
        top.addWidget(self.btn_check)
        v.addLayout(top)

        self.tbl_watch = QTableWidget(0, 4)
        self.tbl_watch.setHorizontalHeaderLabels([
            T('search.col_title'), T('search.col_author'),
            T('lib.col_last'), T('search.col_people')])
        self.tbl_watch.verticalHeader().setVisible(False)
        self.tbl_watch.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_watch.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_watch.setShowGrid(False)
        wh = self.tbl_watch.horizontalHeader()
        wh.setSectionResizeMode(0, QHeaderView.Stretch)
        wh.setSectionResizeMode(1, QHeaderView.Interactive)
        wh.setSectionResizeMode(2, QHeaderView.Interactive)
        wh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.tbl_watch.setColumnWidth(1, 150)
        self.tbl_watch.setColumnWidth(2, 150)
        self.tbl_watch.setColumnWidth(3, 100)

        self.empty_watch = W.EmptyState(T('insight.watch_empty'),
                                        T('insight.watch_empty_desc'))
        v.addWidget(self.tbl_watch, 2)
        v.addWidget(self.empty_watch, 2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName('SendBox')
        self.log.setPlaceholderText(T('insight.check_now'))
        self.log.setFixedHeight(150)
        v.addWidget(self.log)
        return page

    def refresh_watch(self):
        rows = self.watcher.list()
        self.tbl_watch.setRowCount(len(rows))
        for i, r in enumerate(rows):
            it = _cell(r.get('title') or '')
            it.setData(Qt.UserRole, r.get('book_id'))
            self.tbl_watch.setItem(i, 0, it)
            self.tbl_watch.setItem(i, 1, _cell(r.get('author') or '—'))
            self.tbl_watch.setItem(i, 2, _cell(r.get('last_check') or '—', center=True))
            self.tbl_watch.setItem(i, 3, _cell(str(r.get('last_n') or 0), center=True))
        if rows:
            self.tbl_watch.show()
            self.empty_watch.hide()
        else:
            self.tbl_watch.hide()
            self.empty_watch.show()
        last = settings.get('last_watch') or ''
        self.lb_last.setText(T('insight.last_check', t=last) if last
                             else T('insight.never_check'))

    def do_check(self):
        if not self.watcher.list():
            self.win.toast(T('insight.watch_empty'), kind='warn')
            return
        if self.watch_worker and self.watch_worker.isRunning():
            return
        self.btn_check.setEnabled(False)
        self.lb_last.setText(T('insight.checking'))
        self.log.setPlainText('')
        self.watch_worker = WatchWorker(
            self.watcher, top=int(settings.get('watch_top') or 0),
            gap=float(settings.get('watch_gap') or 3.0), parent=self)
        self.watch_worker.progress.connect(self.on_check_progress)
        self.watch_worker.done.connect(self.on_check_done)
        self.watch_worker.start()

    def on_check_progress(self, i, total, title):
        self.lb_last.setText('%s  %d/%d  %s' % (T('insight.checking'), i, total, title))

    def on_check_done(self, results):
        self.btn_check.setEnabled(True)
        self.last_results = results or []
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        hit = sum(1 for r in self.last_results
                  if (r.get('new_count') or 0) + (r.get('up_count') or 0) > 0)
        settings.set_value('last_watch', now)
        self.log.setPlainText(WATCH.plain_summary(self.last_results))
        self.refresh_watch()
        self.win.toast(T('insight.checked', hit=hit) if hit else T('insight.no_change'),
                       kind='ok' if hit else '')
        if hit and settings.get('feishu_on'):
            self.push_feishu(True)

    def push_feishu(self, auto=False):
        hook = (settings.get('feishu_webhook') or '').strip()
        if not hook:
            self.win.toast(T('set.feishu_need'), kind='warn')
            return
        res = [r for r in self.last_results if r.get('ok')]
        if not res:
            self.win.toast(T('insight.check_now'), kind='warn')
            return
        changed = [r for r in res
                   if (r.get('new_count') or 0) + (r.get('up_count') or 0) > 0]
        if not changed and settings.get('feishu_only_changes'):
            if not auto:
                self.win.toast(T('insight.no_change'))
            return
        sec = settings.get('feishu_secret') or ''
        sent = 0
        for r in (changed or res):
            try:
                feishu.push_trend_card(
                    hook, '书脉 · 热门划线更新',
                    r.get('title') or '', r.get('author') or '',
                    r.get('trends') or [], total=r.get('total'), secret=sec)
                sent += 1
            except Exception as e:
                self.win.toast(T('insight.push_fail', err=str(e)), kind='warn')
                return
        if sent:
            self.win.toast(T('insight.pushed'), kind='ok')

    # ------------------------------------------------------------------ 通用
    def switch_tab(self, idx):
        self.stack.fade_to(idx)
        btn = self.tab_group.button(idx)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        self.refresh_tab(idx)

    def refresh_tab(self, idx):
        if idx == 1:
            self.refresh_theme()
        elif idx == 2:
            self.refresh_watch()

    def refresh(self):
        """由主窗口在切页时调用。"""
        self.refresh_tab(self.stack.currentIndex())


# ==========================================================================
# 页面 4.6：AI 大纲（每章的 AI 要点，需要登录态）
# ==========================================================================
class OutlineWorker(QThread):
    """取一本书的 AI 大纲：先问结构，再分批取正文。

    两个接口（2026-10-02 实测）：
      POST /web/book/outline/check  → 章节结构 + 每章有没有要点（**免登录**）
      POST /web/book/outline/inner  → 要点正文（**必须登录态**，不带 Cookie 返回 403）

    为什么分批取正文：一本可能有上百章带要点（实测《短线交易秘诀》122 章），
    一次全塞进请求体不合适，也更容易触发风控。每批 12 章、批间随机停顿。
    单批失败不中断整体 —— 能拿到多少算多少，最后把最后一次错误一起报上来。
    """
    stage = Signal(str)
    progress = Signal(int, int)
    done = Signal(dict, list, str)      # {uid: [文本]}, 章节列表, 最后一次错误
    fail = Signal(str)

    BATCH = 12

    def __init__(self, book_id, cookie, parent=None):
        super().__init__(parent)
        self.book_id = str(book_id)
        self.cookie = cookie or ''
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.stage.emit('check')
            chapters = core.fetch_outline_chapters(self.book_id, cookie=self.cookie)
            uids = [int(c.get('chapterUid')) for c in chapters
                    if c.get('chapterUid') is not None and c.get('hasKeyPoint') == 1]

            text_map, last_err, total = {}, '', len(uids)
            for i in range(0, total, self.BATCH):
                if self._stop:
                    break
                chunk = uids[i:i + self.BATCH]
                try:
                    raw = core.fetch_outline_content(self.book_id, chunk,
                                                     cookie=self.cookie, retries=1)
                    for k, v in (core.outline_parse(raw) or {}).items():
                        try:
                            text_map[int(k)] = v
                        except (TypeError, ValueError):
                            pass
                except Exception as e:
                    last_err = str(e)
                self.progress.emit(min(i + len(chunk), total), total)
                if i + self.BATCH < total and not self._stop:
                    time.sleep(random.uniform(0.6, 1.4))

            self.done.emit(text_map, chapters, last_err)
        except Exception as e:
            self.fail.emit(str(e))


class OutlinePage(QWidget):
    """AI 大纲 —— 书里每一章的总结性要点，单独一页查看/复制/导出。"""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.worker = None
        self.chapters = []
        self.by_uid = {}
        self.book_title = ''
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(12)
        root.addLayout(page_header(T('outline.title'), T('outline.desc')))

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(_tag(T('outline.pick')))
        self.cb_book = QComboBox()
        self.cb_book.setMinimumWidth(300)
        bar.addWidget(self.cb_book)
        self.btn_fetch = QPushButton(T('outline.fetch'))
        self.btn_fetch.setCursor(Qt.PointingHandCursor)
        self.btn_fetch.clicked.connect(self.do_fetch)
        bar.addWidget(self.btn_fetch)
        self.btn_stop = QPushButton(T('ai.stop'))
        self.btn_stop.setProperty('danger', True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_fetch)
        bar.addWidget(self.btn_stop)
        bar.addStretch(1)
        self.lb_state = QLabel('')
        self.lb_state.setObjectName('Hint')
        bar.addWidget(self.lb_state)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        lcard = W.Card()
        lv = card_layout(lcard, margins=(12, 12, 12, 12), spacing=8)
        lv.addWidget(_tag(T('outline.chapters')))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.on_pick)
        lv.addWidget(self.list, 1)
        split.addWidget(lcard)

        rcard = W.Card()
        rv = card_layout(rcard, margins=(14, 12, 14, 12), spacing=8)
        rh = QHBoxLayout()
        rh.setSpacing(8)
        rh.addWidget(_tag(T('outline.content')))
        rh.addStretch(1)
        self.btn_copy = QPushButton(T('outline.copy'))
        self.btn_copy.setProperty('flat', True)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_chapter)
        rh.addWidget(self.btn_copy)
        self.btn_copy_all = QPushButton(T('outline.copy_all'))
        self.btn_copy_all.setProperty('flat', True)
        self.btn_copy_all.setEnabled(False)
        self.btn_copy_all.clicked.connect(self.copy_all)
        rh.addWidget(self.btn_copy_all)
        self.btn_export = QPushButton(T('outline.export'))
        self.btn_export.setProperty('ghost', True)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.do_export)
        rh.addWidget(self.btn_export)
        rv.addLayout(rh)

        self.ed = QPlainTextEdit()
        self.ed.setReadOnly(True)
        self.ed.setObjectName('SendBox')
        self.ed.setPlaceholderText(T('outline.pick_chapter'))
        rv.addWidget(self.ed, 1)
        split.addWidget(rcard)
        split.setSizes([320, 740])
        root.addWidget(split, 1)

        self.empty = W.EmptyState(T('outline.empty_book'), T('outline.empty_book_desc'))
        root.addWidget(self.empty)
        self.empty.hide()

    # ------------------------------------------------------------------ 数据
    def refresh(self):
        """刷新书籍下拉（数据来自本地书库，不额外发请求）。"""
        try:
            cur = self.cb_book.currentData()
            self.cb_book.clear()
            books = self.win.kb.books() or []
            for b in books:
                self.cb_book.addItem('《%s》  %s' % (b.get('title') or '', b.get('author') or ''),
                                     b.get('book_id'))
            if cur:
                i = self.cb_book.findData(cur)
                if i >= 0:
                    self.cb_book.setCurrentIndex(i)
            self.btn_fetch.setEnabled(bool(books))
            if not books:
                self.lb_state.setText('')
        except Exception as e:
            print('[OutlinePage] refresh error:', e, file=sys.stderr)

    def _cookie(self):
        return (settings.get('weread_cookie') or '').strip()

    # ------------------------------------------------------------------ 抓取
    def do_fetch(self):
        if self.worker and self.worker.isRunning():
            return
        if not self._cookie():
            self.win.toast(T('outline.need_cookie'), kind='warn', hold=4600)
            return
        bid = self.cb_book.currentData()
        if not bid:
            return

        self.book_title = (self.cb_book.currentText() or '').strip('《》 ')
        self.btn_fetch.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lb_state.setText(T('outline.loading'))
        self.list.clear()
        self.ed.setPlainText('')
        self.chapters, self.by_uid = [], {}
        self.empty.hide()

        self.worker = OutlineWorker(str(bid), self._cookie(), self)
        self.worker.stage.connect(self._on_stage)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.fail.connect(self._on_fail)
        self.worker.start()

    def _on_stage(self, what):
        if what == 'check':
            self.lb_state.setText(T('outline.loading'))

    def _on_progress(self, done, total):
        self.lb_state.setText(T('outline.progress', done=done, total=total))

    def stop_fetch(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lb_state.setText(T('ai.stop'))

    def _on_fail(self, msg):
        self.btn_fetch.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lb_state.setText('')
        QMessageBox.warning(self, T('outline.title'), msg)

    def _on_done(self, text_map, chapters, last_err):
        self.btn_fetch.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.by_uid = text_map or {}
        self.chapters = chapters or []

        n_has = sum(1 for c in self.chapters if c.get('hasKeyPoint') == 1)
        n_got = len(self.by_uid)
        chars = sum(len('\n'.join(v)) for v in self.by_uid.values())

        self.list.clear()
        for c in self.chapters:
            uid = c.get('chapterUid')
            mark = '\u25CF ' if c.get('hasKeyPoint') == 1 else '   '
            lvl = c.get('level') or 1
            pad = '    ' * max(0, min(2, int(lvl) - 1))
            it = QListWidgetItem('%s%s%s' % (mark, pad, c.get('text') or ''))
            it.setData(Qt.UserRole, uid)
            if c.get('hasKeyPoint') != 1:
                it.setForeground(QColor('#A0A0B8'))
            self.list.addItem(it)

        if n_has == 0:
            self.empty.show()
            self.lb_state.setText('')
            self.btn_copy_all.setEnabled(False)
            self.btn_export.setEnabled(False)
            return

        self.empty.hide()
        self.lb_state.setText(T('outline.summary', n=n_has, chars=core.num_fmt(chars)))
        self.btn_copy_all.setEnabled(bool(self.by_uid))
        self.btn_export.setEnabled(bool(self.by_uid))
        if last_err and n_got < n_has:
            self.win.toast(T('set.cookie_fail', msg=last_err[:70]), kind='warn', hold=5200)

    # ------------------------------------------------------------------ 交互
    def on_pick(self, row):
        if row < 0:
            return
        it = self.list.item(row)
        if it is None:
            return
        uid = it.data(Qt.UserRole)
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            uid = None
        parts = self.by_uid.get(uid) or []
        name = (it.text() or '').strip('\u25CF ')
        if parts:
            self.ed.setPlainText('【%s】\n\n%s' % (name, '\n\n'.join(parts)))
        else:
            self.ed.setPlainText('【%s】\n\n%s' % (name, T('outline.none')))
        self.btn_copy.setEnabled(bool(parts))

    def _chapter_blocks(self):
        """把已取到的大纲拼成「章名 + 要点」的文本块列表。"""
        name_of = {}
        for c in self.chapters:
            name_of[c.get('chapterUid')] = c.get('text') or ''
        blocks = []
        for c in self.chapters:
            uid = c.get('chapterUid')
            if c.get('hasKeyPoint') != 1:
                continue
            parts = self.by_uid.get(uid)
            if not parts:
                continue
            try:
                uid_i = int(uid)
            except (TypeError, ValueError):
                uid_i = uid
            parts = self.by_uid.get(uid_i) or parts
            blocks.append('## %s\n\n%s' % (name_of.get(uid, ''), '\n\n'.join(parts)))
        return blocks

    def _full_text(self):
        head = '# 《%s》· AI 大纲\n' % self.book_title
        return head + '\n\n'.join(self._chapter_blocks())

    def copy_chapter(self):
        t = self.ed.toPlainText()
        if not t.strip():
            return
        QApplication.clipboard().setText(t)
        self.win.toast(T('outline.copied'), kind='ok')

    def copy_all(self):
        t = self._full_text()
        if not t.strip():
            return
        QApplication.clipboard().setText(t)
        self.win.toast(T('outline.copied'), kind='ok')

    # ------------------------------------------------------------------ 导出
    def _render_text(self, ext):
        """把大纲渲染成 md / txt / html —— 三种覆盖了常见去向。"""
        title = self.book_title
        blocks = self._chapter_blocks()

        if ext == '.html':
            secs = []
            for b in blocks:
                lines = b.split('\n')
                name = lines[0].replace('## ', '').strip()
                body = [l for l in lines[1:] if l.strip()]
                secs.append('<section><h2>%s</h2>%s</section>'
                            % (core.esc(name),
                               ''.join('<p>%s</p>' % core.esc(p) for p in body)))
            return (
                '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>%s · AI 大纲</title><style>'
                'body{margin:0;background:#f4f6f8;font:16px/1.85 -apple-system,'
                '"PingFang SC","Microsoft YaHei",sans-serif;color:#222}'
                'header{background:linear-gradient(135deg,#6366F1,#7C3AED);'
                'color:#fff;padding:32px 20px}h1{margin:0;font-size:22px}'
                'main{max-width:760px;margin:24px auto;padding:0 16px}'
                'section{background:#fff;border-radius:12px;padding:18px 20px;'
                'margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,.05)}'
                'section h2{margin:0 0 10px;font-size:16px;color:#4C1D95}'
                'section p{margin:6px 0;font-size:15.5px;line-height:1.9}'
                '</style></head><body><header><h1>《%s》· AI 大纲</h1></header>'
                '<main>%s</main></body></html>'
                % (core.esc(title), core.esc(title), ''.join(secs)))

        if ext == '.txt':
            out = ['《%s》· AI 大纲' % title, '']
            for b in blocks:
                lines = b.split('\n')
                out.append(lines[0].replace('## ', '').strip())
                out.append('')
                out.extend(l for l in lines[1:] if l.strip())
                out.append('')
            return '\n'.join(out)

        return self._full_text()

    def do_export(self):
        """导出大纲：Markdown / 纯文本 / 网页，任选。"""
        blocks = self._chapter_blocks()
        if not blocks:
            return
        default = os.path.join(
            export_dir(), '《%s》AI大纲-%s.md'
            % (core.safe_filename(self.book_title), core.stamp()))
        filt = ';;'.join(['Markdown (*.md)', '纯文本 (*.txt)',
                          '网页 (*.html)', '所有文件 (*)'])
        path, _ = QFileDialog.getSaveFileName(self, T('outline.export'), default, filt)
        if not path:
            return
        ext = (os.path.splitext(path)[1] or '.md').lower()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._render_text(ext))
        except Exception as e:
            QMessageBox.warning(self, T('outline.export'), str(e))
            return
        self.win.toast(T('outline.exported', name=os.path.basename(path)),
                       kind='ok', hold=3600)
        self.win.refresh_exports()


# ==========================================================================
# 页面 5：导出记录
# ==========================================================================
class ExportPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)
        root.addLayout(page_header(T('exp.title'), T('exp.desc')))

        tools = QHBoxLayout()
        tools.setSpacing(9)
        b1 = QPushButton(T('exp.refresh'))
        b1.clicked.connect(self.refresh)
        b2 = QPushButton(T('exp.open_file'))
        b2.setProperty('flat', True)
        b2.clicked.connect(self.open_selected)
        b3 = QPushButton(T('exp.open_dir'))
        b3.setProperty('ghost', True)
        b3.clicked.connect(self.open_folder)
        b4 = QPushButton(T('exp.delete'))
        b4.setProperty('danger', True)
        b4.clicked.connect(self.delete_selected)
        tools.addWidget(b1)
        tools.addWidget(b2)
        tools.addWidget(b3)
        tools.addStretch(1)
        tools.addWidget(b4)
        root.addLayout(tools)

        card = W.Card()
        cv = card_layout(card, margins=(14, 14, 14, 14), spacing=8)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            T('exp.col_name'), T('exp.col_fmt'), T('exp.col_size'), T('exp.col_time')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(lambda _: self.open_selected())
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 88)
        self.table.setColumnWidth(2, 96)
        self.table.setColumnWidth(3, 150)
        cv.addWidget(self.table, 1)
        self.empty = W.EmptyState(T('empty.exp_title'), T('empty.exp_desc'))
        cv.addWidget(self.empty, 1)
        self.empty.hide()
        root.addWidget(card, 1)

        self.desc = QLabel('')
        self.desc.setObjectName('Hint')
        root.addWidget(self.desc)

    def refresh(self):
        os.makedirs(export_dir(), exist_ok=True)
        files = [os.path.join(export_dir(), n) for n in os.listdir(export_dir())
                 if os.path.isfile(os.path.join(export_dir(), n))]
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

        self.table.setRowCount(len(files))
        for i, p in enumerate(files):
            st = os.stat(p)
            ext = os.path.splitext(p)[1].lstrip('.').lower() or '—'
            item0 = _cell(os.path.basename(p))
            item0.setData(Qt.UserRole, p)
            self.table.setItem(i, 0, item0)
            self.table.setItem(i, 1, _cell(ext.upper(), center=True))
            self.table.setItem(i, 2, _cell(human_size(st.st_size), center=True))
            self.table.setItem(i, 3, _cell(
                datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'),
                center=True))
        if files:
            self.table.show()
            self.empty.hide()
        else:
            self.table.hide()
            self.empty.show()
        total = sum(os.path.getsize(p) for p in files)
        self.desc.setText(T('exp.footer', n=len(files), size=human_size(total)))

    def _selected_path(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        return it.data(Qt.UserRole) if it else None

    def open_selected(self):
        p = self._selected_path()
        if not p:
            self.win.toast(T('toast.pick_row'), kind='warn')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def open_folder(self):
        os.makedirs(export_dir(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(export_dir()))

    def delete_selected(self):
        p = self._selected_path()
        if not p:
            self.win.toast(T('toast.pick_row'), kind='warn')
            return
        name = os.path.basename(p)
        if QMessageBox.question(
                self, T('dlg.confirm_delete'), T('dlg.delete_text', name=name),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if trash(p):
            self.refresh()
            self.win.toast(T('toast.trashed', name=name), kind='ok')
        else:
            self.win.toast(T('toast.trash_fail'), kind='warn')


# ==========================================================================
# 页面 5：设置
# ==========================================================================
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._loading = True
        self._build()
        self._loading = False
        self._sync_cookie_keys()

    def _sync_cookie_keys(self):
        """把「识别到哪些关键字段」实时显示出来，用户一眼知道有没有粘对。"""
        try:
            ck = (self.ed_cookie.text() or '').strip()
            if not ck:
                self.lb_cookie_keys.setText('')
                return
            keys = core.cookie_keys(ck)
            if keys:
                self.lb_cookie_keys.setText(T('set.cookie_detected', keys=' / '.join(keys)))
            else:
                self.lb_cookie_keys.setText(T('set.cookie_nokeys'))
        except Exception:
            pass

    def _group(self, text):
        lb = QLabel(text)
        lb.setObjectName('SetGroup')
        return lb

    def _hint(self, text):
        lb = QLabel(text)
        lb.setObjectName('Hint')
        return lb

    def _row(self, label, widget, hint='', max_w=None):
        """一行设置：标签 + 控件（+ 说明）。

        输入类控件不该占满整行 —— 宽度拉满会让整个设置页看起来又挤又空。
        这里按控件类型给一个得体的宽度上限；用 `_wrap()` 包出来的组合控件
        是 QWidget，不在此列，保持自适应。
        """
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(_tag(label))
        if max_w is None:
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                max_w = 132
            elif isinstance(widget, QComboBox):
                max_w = 300
            elif isinstance(widget, QLineEdit):
                max_w = 380
        if max_w:
            try:
                widget.setMaximumWidth(int(max_w))
            except Exception:
                pass
        box.addWidget(widget)
        if hint:
            box.addWidget(self._hint(hint))
        return box

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(13)
        root.addLayout(page_header(T('set.title'), T('set.desc')))

        # 顶部摘要：一眼看清「现在到底配置成什么样」，不用逐张卡片去读
        self.lb_summary = QLabel('')
        self.lb_summary.setObjectName('SetSummary')
        self.lb_summary.setWordWrap(True)
        root.addWidget(self.lb_summary)

        # 设置项较多，外面包一层滚动区 —— 否则窗口不够高时控件会挤成一团
        inner = QWidget()
        grid = QHBoxLayout(inner)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(14)

        # ---------------- 左列 ----------------
        col1 = QVBoxLayout()
        col1.setSpacing(13)

        c_app = W.Card()
        av = card_layout(c_app, margins=(16, 15, 16, 17), spacing=12)
        av.addWidget(self._group('\U0001F3A8  ' + T('set.appearance')))

        av.addWidget(_tag(T('set.theme')))
        chips = QGridLayout()
        chips.setSpacing(8)
        self.theme_group = QButtonGroup(self)
        for i, key in enumerate(theme.THEME_ORDER):
            lbl = theme.THEME_LABELS[key][0 if i18n.is_zh() else 1]
            acc = theme.ACCENTS.get(key) or {}
            b = QPushButton(lbl)
            # 用一个真实配色的圆点当图标 —— 比文字里的「●」更准，也更精致
            pm = QPixmap(14, 14)
            pm.fill(Qt.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.Antialiasing, True)
            pp.setPen(Qt.NoPen)
            pp.setBrush(QColor(acc.get('p', '#6366F1')))
            pp.drawEllipse(1, 1, 12, 12)
            pp.setBrush(QColor(acc.get('a', '#F472B6')))
            pp.drawEllipse(7, 7, 6, 6)
            pp.end()
            b.setIcon(QIcon(pm))
            b.setCheckable(True)
            b.setObjectName('ThemeChip')
            b.setCursor(Qt.PointingHandCursor)
            if key == settings.get('theme'):
                b.setChecked(True)
            b.clicked.connect(lambda _=False, k=key: self.on_theme(k))
            self.theme_group.addButton(b, i)
            chips.addWidget(b, i // 2, i % 2)   # 2×2 排布，避免撑宽左列
        av.addLayout(chips)

        av.addWidget(_tag(T('set.mode')))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        for i, (m, key) in enumerate([(T('set.mode_light'), 'light'),
                                      (T('set.mode_dark'), 'dark'),
                                      (T('set.mode_auto'), 'auto')]):
            b = QPushButton(m)
            b.setCheckable(True)
            b.setObjectName('ThemeChip')
            b.setCursor(Qt.PointingHandCursor)
            if key == settings.get('mode'):
                b.setChecked(True)
            b.clicked.connect(lambda _=False, k=key: self.on_mode(k))
            self.mode_group.addButton(b, i)
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        av.addLayout(mode_row)

        rad_row = QHBoxLayout()
        rad_row.setSpacing(10)
        self.sl_radius = QSlider(Qt.Horizontal)
        self.sl_radius.setRange(6, 20)
        self.sl_radius.setValue(int(settings.get('radius')))
        self.sl_radius.valueChanged.connect(self.on_radius)
        self.lb_radius = _tag(str(settings.get('radius')))
        rad_row.addWidget(self.sl_radius, 1)
        rad_row.addWidget(self.lb_radius)
        av.addLayout(self._row(T('set.radius'), self._wrap(rad_row)))

        self.cb_motion = QCheckBox(T('set.motion_on'))
        self.cb_motion.setChecked(bool(settings.get('motion')))
        self.cb_motion.stateChanged.connect(self.on_motion)
        av.addWidget(self.cb_motion)

        self.cb_titlebar = QCheckBox(T('set.titlebar'))
        self.cb_titlebar.setChecked(bool(settings.get('custom_titlebar')))
        self.cb_titlebar.stateChanged.connect(self.on_titlebar)
        av.addWidget(self.cb_titlebar)
        av.addWidget(self._hint(T('set.titlebar_hint')))
        col1.addWidget(c_app)

        c_lang = W.Card()
        lv = card_layout(c_lang, margins=(16, 15, 16, 17), spacing=12)
        lv.addWidget(self._group('\U0001F310  ' + T('set.language')))
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        for code, label in i18n.AVAILABLE:
            b = QPushButton(label)
            b.setObjectName('ThemeChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if code == i18n.current():
                b.setChecked(True)
            b.clicked.connect(lambda _=False, c=code: self.on_lang(c))
            lrow.addWidget(b)
        lrow.addStretch(1)
        lv.addLayout(lrow)
        lv.addWidget(self._hint(T('set.lang_hint')))
        col1.addWidget(c_lang)

        # ---------------- 快捷键（方向 8）----------------
        # 注意：必须加在 col1.addStretch(1) **之前**，
        # 否则会被 stretch 顶到列底，看起来像"卡片没渲染出来"。
        c_keys = W.Card()
        kv = card_layout(c_keys, margins=(16, 14, 16, 16), spacing=7)
        kv.addWidget(self._group('\u2328  ' + T('set.shortcuts')))
        for k, v in [('Ctrl+K', T('cmd.placeholder')),
                     ('Ctrl+F', T('nav.search')),
                     ('Ctrl+G', T('ai.btn')),
                     ('Ctrl+E', T('search.export')),
                     ('Ctrl+R', T('set.sc_refresh')),
                     ('Ctrl+1 … 7', T('set.sc_pages')),
                     ('Ctrl+,', T('nav.settings'))]:
            row = QHBoxLayout()
            row.setSpacing(10)
            kl = QLabel(k)
            kl.setObjectName('Kbd')
            kl.setMinimumWidth(84)
            kl.setAlignment(Qt.AlignCenter)
            row.addWidget(kl)
            vl = QLabel(v)
            vl.setObjectName('Hint')
            row.addWidget(vl, 1)
            kv.addLayout(row)
        kv.addWidget(self._hint(T('set.sc_hint')))
        col1.addWidget(c_keys)

        col1.addStretch(1)

        # ---------------- 右列 ----------------
        col2 = QVBoxLayout()
        col2.setSpacing(13)

        c_beh = W.Card()
        bv = card_layout(c_beh, margins=(16, 15, 16, 17), spacing=12)
        bv.addWidget(self._group('\U0001F4E5  ' + T('set.behavior')))

        self.sp_count = QSpinBox()
        self.sp_count.setRange(0, 100000)
        self.sp_count.setValue(int(settings.get('def_count')))
        self.sp_count.setSpecialValueText(T('batch.all'))
        self.sp_count.valueChanged.connect(
            lambda v: settings.set_value('def_count', int(v)))
        bv.addLayout(self._row(T('set.def_count'), self.sp_count))

        # 划线人数下限（默认 ≥2 人）
        self.sp_minp = QSpinBox()
        self.sp_minp.setRange(0, 100000)
        self.sp_minp.setValue(int(settings.get('min_people')))
        self.sp_minp.setSpecialValueText(T('batch.all'))
        self.sp_minp.valueChanged.connect(self.on_min_people)
        bv.addLayout(self._row(T('set.min_people'), self.sp_minp,
                               T('set.min_people_hint')))

        # 导出内容里要不要带「N 人划线」（默认不带：导出给别人看只要句子本身）
        self.cb_people = QCheckBox(T('set.export_people'))
        self.cb_people.setChecked(bool(settings.get('export_people')))
        self.cb_people.stateChanged.connect(self.on_export_people)
        bv.addWidget(self.cb_people)
        bv.addWidget(self._hint(T('set.export_people_hint')))

        self.cb_open_after = QCheckBox(T('set.open_after_export'))
        self.cb_open_after.setChecked(bool(settings.get('open_after_export')))
        self.cb_open_after.stateChanged.connect(
            lambda v: settings.set_value('open_after_export', bool(v)))
        bv.addWidget(self.cb_open_after)

        # 导出格式（可多选）
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(12)
        self.fmt_checks = {}
        picked = settings.get('export_formats') or ['html']
        for k in core.FORMATS:
            cb = QCheckBox(k.upper())
            cb.setChecked(k in picked)
            cb.stateChanged.connect(self.on_formats)
            self.fmt_checks[k] = cb
            fmt_row.addWidget(cb)
        fmt_row.addStretch(1)
        # 注意：这一行【不设】宽度上限 —— 复选框文字会被裁成 HTM / JSO，
        # 让它按内容自适应。
        bv.addLayout(self._row(T('set.formats'), self._wrap(fmt_row),
                               T('set.formats_hint'), 0))

        # 导出目录（可自定义）—— 输入框与按钮分两行，避免行最小宽度超过列宽被截断
        self.ed_dir = QLineEdit()
        self.ed_dir.setReadOnly(True)
        self.ed_dir.setText(settings.get('export_dir') or '')
        self.ed_dir.setPlaceholderText(FALLBACK_DIR)
        self.ed_dir.setToolTip(settings.get('export_dir') or FALLBACK_DIR)
        b_browse = QPushButton(T('set.browse'))
        b_browse.setProperty('flat', True)
        b_browse.clicked.connect(self.on_browse_dir)
        b_rd = QPushButton(T('set.use_default_dir'))
        b_rd.setProperty('ghost', True)
        b_rd.clicked.connect(self.on_reset_dir)
        dir_btns = QHBoxLayout()
        dir_btns.setSpacing(8)
        dir_btns.addWidget(b_browse)
        dir_btns.addWidget(b_rd)
        dir_btns.addStretch(1)
        dir_box = QVBoxLayout()
        dir_box.setSpacing(6)
        dir_box.addWidget(self.ed_dir)
        dir_box.addLayout(dir_btns)
        bv.addLayout(self._row(T('set.export_dir'), self._wrap(dir_box),
                               T('set.dir_hint'), 640))

        iv = QHBoxLayout()
        iv.setSpacing(6)
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0.0, 60.0)
        self.sp_min.setSingleStep(0.5)
        self.sp_min.setValue(float(settings.get('interval_min')))
        self.sp_min.valueChanged.connect(
            lambda v: settings.set_value('interval_min', float(v)))
        self.sp_max = QDoubleSpinBox()
        self.sp_max.setRange(0.0, 120.0)
        self.sp_max.setSingleStep(0.5)
        self.sp_max.setValue(float(settings.get('interval_max')))
        self.sp_max.valueChanged.connect(
            lambda v: settings.set_value('interval_max', float(v)))
        iv.addWidget(self.sp_min)
        iv.addWidget(_tag('~'))
        iv.addWidget(self.sp_max)
        bv.addLayout(self._row(T('set.interval'), self._wrap(iv),
                               T('set.interval_hint'), 300))
        col2.addWidget(c_beh)

        # ---------------- AI 助手（方向 2 / 3）----------------
        c_ai = W.Card()
        aiv = card_layout(c_ai, margins=(16, 15, 16, 17), spacing=12)
        aiv.addWidget(self._group('\U0001F916  ' + T('set.ai')))

        self.cb_provider = QComboBox()
        for k in AIm.PROVIDER_ORDER:
            self.cb_provider.addItem(AIm.PROVIDERS[k]['label'], k)
        i0 = self.cb_provider.findData(settings.get('ai_provider'))
        if i0 >= 0:
            self.cb_provider.setCurrentIndex(i0)
        self.cb_provider.currentIndexChanged.connect(self.on_provider)
        aiv.addLayout(self._row(T('set.ai_provider'), self.cb_provider))

        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.currentTextChanged.connect(self.on_model)
        aiv.addLayout(self._row(T('set.ai_model'), self.cb_model))
        self._fill_models()

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText('sk-...')
        self.ed_key.textChanged.connect(self.on_key)
        b_get = QPushButton(T('set.ai_get_key'))
        b_get.setProperty('flat', True)
        b_get.clicked.connect(self.open_key_page)
        key_row.addWidget(self.ed_key, 1)
        key_row.addWidget(b_get)
        aiv.addLayout(self._row(T('set.ai_key'), self._wrap(key_row),
                                T('set.ai_key_hint')))
        self._load_key()

        self.cb_stream = QCheckBox(T('set.ai_stream'))
        self.cb_stream.setChecked(bool(settings.get('ai_stream')))
        self.cb_stream.stateChanged.connect(
            lambda v: settings.set_value('ai_stream', bool(v)))
        aiv.addWidget(self.cb_stream)

        self.sp_maxitems = QSpinBox()
        self.sp_maxitems.setRange(20, 1000)
        self.sp_maxitems.setValue(int(settings.get('ai_max_items')))
        self.sp_maxitems.valueChanged.connect(
            lambda v: settings.set_value('ai_max_items', int(v)))
        aiv.addLayout(self._row(T('set.ai_max_items'), self.sp_maxitems))

        ai_row = QHBoxLayout()
        ai_row.setSpacing(8)
        b_test = QPushButton(T('set.ai_test'))
        b_test.setProperty('ghost', True)
        b_test.clicked.connect(self.on_test_ai)
        b_prompt = QPushButton(T('set.ai_prompt'))
        b_prompt.setProperty('ghost', True)
        b_prompt.clicked.connect(lambda: PromptDialog(self, self.win).exec())
        ai_row.addWidget(b_test)
        ai_row.addWidget(b_prompt)
        ai_row.addStretch(1)
        aiv.addLayout(ai_row)
        col2.addWidget(c_ai)

        # ---------------- 飞书推送（方向 6）----------------
        c_fs = W.Card()
        fv = card_layout(c_fs, margins=(16, 15, 16, 17), spacing=12)
        fv.addWidget(self._group('\U0001F514  ' + T('set.feishu')))

        self.ed_hook = QLineEdit()
        self.ed_hook.setText(settings.get('feishu_webhook') or '')
        self.ed_hook.setPlaceholderText('https://open.feishu.cn/open-apis/bot/v2/hook/...')
        self.ed_hook.textChanged.connect(
            lambda t: settings.set_value('feishu_webhook', t.strip()))
        fv.addLayout(self._row(T('set.feishu_webhook'), self.ed_hook,
                               T('set.feishu_webhook_hint')))

        self.ed_secret = QLineEdit()
        self.ed_secret.setEchoMode(QLineEdit.Password)
        self.ed_secret.setText(settings.get('feishu_secret') or '')
        self.ed_secret.textChanged.connect(
            lambda t: settings.set_value('feishu_secret', t.strip()))
        fv.addLayout(self._row(T('set.feishu_secret'), self.ed_secret,
                               T('set.feishu_secret_hint')))

        self.cb_fs_on = QCheckBox(T('set.feishu_on'))
        self.cb_fs_on.setChecked(bool(settings.get('feishu_on')))
        self.cb_fs_on.stateChanged.connect(
            lambda v: settings.set_value('feishu_on', bool(v)))
        fv.addWidget(self.cb_fs_on)

        self.cb_fs_chg = QCheckBox(T('set.feishu_only_changes'))
        self.cb_fs_chg.setChecked(bool(settings.get('feishu_only_changes')))
        self.cb_fs_chg.stateChanged.connect(
            lambda v: settings.set_value('feishu_only_changes', bool(v)))
        fv.addWidget(self.cb_fs_chg)

        gap_row = QHBoxLayout()
        gap_row.setSpacing(6)
        self.sp_gap = QDoubleSpinBox()
        self.sp_gap.setRange(0.5, 60.0)
        self.sp_gap.setSingleStep(0.5)
        self.sp_gap.setValue(float(settings.get('watch_gap')))
        self.sp_gap.valueChanged.connect(
            lambda v: settings.set_value('watch_gap', float(v)))
        gap_row.addWidget(self.sp_gap)
        gap_row.addWidget(_tag('s'))
        gap_row.addStretch(1)
        fv.addLayout(self._row(T('set.watch_gap'), self._wrap(gap_row)))

        self.sp_wtop = QSpinBox()
        self.sp_wtop.setRange(0, 100000)
        self.sp_wtop.setValue(int(settings.get('watch_top')))
        self.sp_wtop.setSpecialValueText(T('batch.all'))
        self.sp_wtop.valueChanged.connect(
            lambda v: settings.set_value('watch_top', int(v)))
        fv.addLayout(self._row(T('set.watch_top'), self.sp_wtop))

        self.cb_auto = QCheckBox(T('set.watch_auto'))
        self.cb_auto.setChecked(bool(settings.get('watch_auto')))
        self.cb_auto.stateChanged.connect(
            lambda v: settings.set_value('watch_auto', bool(v)))
        fv.addWidget(self.cb_auto)

        self.sp_every = QSpinBox()
        self.sp_every.setRange(1, 168)
        self.sp_every.setSuffix(' h')
        self.sp_every.setValue(int(settings.get('watch_every')))
        self.sp_every.valueChanged.connect(
            lambda v: settings.set_value('watch_every', int(v)))
        fv.addLayout(self._row(T('set.watch_every'), self.sp_every))

        b_fstest = QPushButton(T('set.feishu_test'))
        b_fstest.setProperty('ghost', True)
        b_fstest.clicked.connect(self.on_test_feishu)
        fv.addWidget(b_fstest)
        col2.addWidget(c_fs)

        # ---------------- 导出模板 ----------------
        c_tpl = W.Card()
        tv = card_layout(c_tpl, margins=(16, 15, 16, 17), spacing=12)
        tv.addWidget(self._group('\U0001F4D0  ' + T('set.template')))

        self.sp_font = QSpinBox()
        self.sp_font.setRange(9, 26)
        self.sp_font.setSuffix(' pt')
        self.sp_font.setValue(int(settings.get('style_font_size')))
        self.sp_font.valueChanged.connect(self.on_style)
        tv.addLayout(self._row(T('set.style_font'), self.sp_font))

        self.cb_show_chapter = QCheckBox(T('set.style_chapter'))
        self.cb_show_chapter.setChecked(bool(settings.get('style_show_chapter')))
        self.cb_show_chapter.stateChanged.connect(self.on_style_check)
        tv.addWidget(self.cb_show_chapter)

        self.cb_show_index = QCheckBox(T('set.style_index'))
        self.cb_show_index.setChecked(bool(settings.get('style_show_index')))
        self.cb_show_index.stateChanged.connect(self.on_style_check)
        tv.addWidget(self.cb_show_index)

        color_row = QHBoxLayout()
        color_row.setSpacing(7)
        cur = settings.get('style_accent') or '#7C3AED'
        for hexv in ACCENT_PRESETS:
            b = QPushButton()
            b.setFixedSize(30, 30)
            pm = QPixmap(18, 18)
            pm.fill(Qt.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.Antialiasing, True)
            pp.setPen(Qt.NoPen)
            pp.setBrush(QColor(hexv))
            pp.drawEllipse(0, 0, 17, 17)
            if hexv.lower() == str(cur).lower():
                pp.setBrush(Qt.NoBrush)
                pp.setPen(QPen(QColor('#FFFFFF'), 2))
                pp.drawEllipse(3, 3, 11, 11)
            pp.end()
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(18, 18))
            b.setProperty('ghost', True)
            b.setToolTip(hexv)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=hexv: self.on_accent(c))
            color_row.addWidget(b)
        color_row.addStretch(1)
        tv.addLayout(self._row(T('set.style_accent'), self._wrap(color_row)))
        tv.addWidget(self._hint(T('set.style_hint')))
        col2.addWidget(c_tpl)

        # ---------------- 网络 ----------------
        # ---- 微信读书登录（只为 AI 大纲）----
        c_wr = W.Card()
        wv = card_layout(c_wr, margins=(16, 15, 16, 17), spacing=12)
        wv.addWidget(self._group('\U0001F510  ' + T('set.weread')))
        wv.addWidget(self._hint(T('set.cookie_hint')))

        # 两步走：先去浏览器登录，再把 Cookie 弄进来
        goto_row = QHBoxLayout()
        goto_row.setSpacing(8)
        b_go = QPushButton(T('set.cookie_open'))
        b_go.setProperty('ghost', True)
        b_go.setCursor(Qt.PointingHandCursor)
        b_go.clicked.connect(self.on_open_weread)
        goto_row.addWidget(b_go)
        b_paste = QPushButton(T('set.cookie_paste'))
        b_paste.setProperty('ghost', True)
        b_paste.setCursor(Qt.PointingHandCursor)
        b_paste.clicked.connect(self.on_paste_cookie)
        goto_row.addWidget(b_paste)
        goto_row.addStretch(1)
        wv.addLayout(goto_row)

        self.ed_cookie = QLineEdit()
        self.ed_cookie.setText(settings.get('weread_cookie') or '')
        self.ed_cookie.setPlaceholderText(T('set.cookie_ph'))
        self.ed_cookie.textChanged.connect(self.on_cookie)
        wv.addLayout(self._row(T('set.cookie'), self.ed_cookie))
        self.lb_cookie_keys = QLabel('')
        self.lb_cookie_keys.setObjectName('Hint')
        self.lb_cookie_keys.setWordWrap(True)
        wv.addWidget(self.lb_cookie_keys)
        wv.addWidget(self._hint(T('set.cookie_howto')))
        wr_row = QHBoxLayout()
        wr_row.setSpacing(8)
        b_ct = QPushButton(T('set.cookie_test'))
        b_ct.setProperty('ghost', True)
        b_ct.setCursor(Qt.PointingHandCursor)
        b_ct.clicked.connect(self.on_test_cookie)
        wr_row.addWidget(b_ct)
        wr_row.addStretch(1)
        self.lb_cookie_state = QLabel('')
        self.lb_cookie_state.setObjectName('Hint')
        self.lb_cookie_state.setWordWrap(True)
        wr_row.addWidget(self.lb_cookie_state, 1)
        wv.addLayout(wr_row)
        col2.addWidget(c_wr)

        c_net = W.Card()
        nv2 = card_layout(c_net, margins=(16, 15, 16, 17), spacing=12)
        nv2.addWidget(self._group('\U0001F4E1  ' + T('set.net')))

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(3, 180)
        self.sp_timeout.setSuffix(T('set.seconds'))
        self.sp_timeout.setValue(int(settings.get('net_timeout')))
        self.sp_timeout.valueChanged.connect(self.on_net)
        nv2.addLayout(self._row(T('set.timeout'), self.sp_timeout))

        self.sp_retries = QSpinBox()
        self.sp_retries.setRange(0, 8)
        self.sp_retries.setSuffix(T('set.times'))
        self.sp_retries.setValue(int(settings.get('net_retries')))
        self.sp_retries.valueChanged.connect(self.on_net)
        nv2.addLayout(self._row(T('set.retries'), self.sp_retries))

        # 代理模式：直连（默认）/ 跟随系统 / 自定义
        self.cb_pmode = QComboBox()
        for val, key in (('direct', 'set.pmode_direct'),
                         ('system', 'set.pmode_system'),
                         ('custom', 'set.pmode_custom')):
            self.cb_pmode.addItem(T(key), val)
        _sel = self.cb_pmode.findData(settings.get('net_proxy_mode') or 'direct')
        self.cb_pmode.setCurrentIndex(_sel if _sel >= 0 else 0)
        self.cb_pmode.currentIndexChanged.connect(self.on_net)
        nv2.addLayout(self._row(T('set.pmode'), self.cb_pmode, T('set.pmode_hint'), 340))

        self.ed_proxy = QLineEdit()
        self.ed_proxy.setText(settings.get('net_proxy') or '')
        self.ed_proxy.setPlaceholderText('http://127.0.0.1:7890')
        self.ed_proxy.textChanged.connect(self.on_net)
        nv2.addLayout(self._row(T('set.proxy'), self.ed_proxy, T('set.proxy_hint')))

        # 网络自检：实测直连 / 系统代理 / 自定义 三种方式各自的真实耗时。
        # 用来回答「是不是我的网络问题」—— 代理时开时关时这个特别好使。
        net_row = QHBoxLayout()
        net_row.setSpacing(8)
        b_st = QPushButton(T('set.net_test'))
        b_st.setProperty('ghost', True)
        b_st.setCursor(Qt.PointingHandCursor)
        b_st.clicked.connect(self.on_net_test)
        net_row.addWidget(b_st)
        net_row.addStretch(1)
        self.lb_net = QLabel('')
        self.lb_net.setObjectName('Hint')
        self.lb_net.setWordWrap(True)
        net_row.addWidget(self.lb_net, 1)
        nv2.addLayout(net_row)

        syspx = core.system_proxy_hint()
        if syspx.get('has'):
            nv2.addWidget(self._hint(T('set.sys_proxy_found', addr=syspx.get('https')
                                       or syspx.get('http'))))
        col2.addWidget(c_net)

        c_data = W.Card()
        dv = card_layout(c_data, margins=(16, 15, 16, 17), spacing=12)
        dv.addWidget(self._group('\U0001F4BE  ' + T('set.data')))
        self.lb_stats = self._hint('')
        dv.addWidget(self.lb_stats)
        dpath = QLabel(kb.DB_PATH)
        dpath.setObjectName('Hint')
        dpath.setWordWrap(True)
        dv.addWidget(dpath)
        drow = QHBoxLayout()
        drow.setSpacing(8)
        b_open = QPushButton(T('set.open_data'))
        b_open.setProperty('flat', True)
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(kb.DB_PATH))))
        b_clear = QPushButton(T('set.clear_cache'))
        b_clear.setProperty('danger', True)
        b_clear.clicked.connect(self.on_clear)
        b_reset = QPushButton(T('set.reset'))
        b_reset.setProperty('ghost', True)
        b_reset.clicked.connect(self.on_reset)
        drow.addWidget(b_open)
        drow.addWidget(b_reset)
        drow.addStretch(1)
        drow.addWidget(b_clear)
        dv.addLayout(drow)
        col2.addWidget(c_data)

        about = W.Card()
        ov = card_layout(about, margins=(16, 14, 16, 16), spacing=6)
        ov.addWidget(self._group(app_name()))
        ov.addWidget(self._hint('%s · v%s' % (T('app.subtitle'), APP_VERSION)))
        ov.addWidget(self._hint(T('app.tagline')))
        ov.addWidget(self._hint(T('set.about_tech')))
        col2.addWidget(about)
        col2.addStretch(1)

        grid.addLayout(col1, 1)
        grid.addLayout(col2, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            'QScrollArea{background:transparent;border:0;}'
            'QScrollArea>QWidget>QWidget{background:transparent;}')
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self.refresh_stats()

    def _wrap(self, layout):
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def refresh_stats(self):
        st = self.win.kb.stats()
        self.lb_stats.setText(T('set.stats', books=st['books'], marks=st['marks'],
                                size=human_size(st['size'])))
        self.refresh_summary(st)

    def refresh_summary(self, st=None):
        """顶部摘要：一眼看清当前配置。"""
        try:
            if st is None:
                st = self.win.kb.stats()
            th = theme.THEME_LABELS[settings.get('theme')][0 if i18n.is_zh() else 1]
            md = {'light': T('set.mode_light'), 'dark': T('set.mode_dark'),
                  'auto': T('set.mode_auto')}.get(settings.get('mode'), '')
            fmts = settings.get('export_formats') or ['html']
            fl = ' + '.join(x.upper() for x in fmts)
            self.lb_summary.setText(
                '%s   ·   %s   ·   %s   ·   %s'
                % (th, md, fl, T('side.library_stats',
                                 books=st['books'], marks=st['marks'])))
        except Exception:
            pass

    # ------------------------------------------------------------ 模板 / 网络
    def on_style(self, _=None):
        if self._loading:
            return
        settings.set_value('style_font_size', int(self.sp_font.value()))

    def on_style_check(self, _=None):
        if self._loading:
            return
        settings.set_value('style_show_chapter', bool(self.cb_show_chapter.isChecked()))
        settings.set_value('style_show_index', bool(self.cb_show_index.isChecked()))

    def on_accent(self, hexv):
        if self._loading:
            return
        settings.set_value('style_accent', hexv)
        self.win.toast(T('set.saved'), kind='ok')

    def on_net(self, _=None):
        if self._loading:
            return
        settings.set_value('net_timeout', int(self.sp_timeout.value()))
        settings.set_value('net_retries', int(self.sp_retries.value()))
        settings.set_value('net_proxy', self.ed_proxy.text().strip())
        settings.set_value('net_proxy_mode', self.cb_pmode.currentData() or 'direct')
        apply_net_settings()
        self.lb_net.setText('')

    def on_net_test(self):
        """网络自检：把「直连 / 系统代理 / 自定义」逐个真跑一次，报耗时。

        这是回答「是网络问题还是程序慢」最直接的办法 —— 谁快用谁。
        """
        self.lb_net.setText(T('outline.loading'))
        QApplication.processEvents()
        try:
            res = core.net_selftest()
        except Exception as e:
            self.lb_net.setText(T('set.net_test_fail', msg=str(e)[:60]))
            return
        parts, best = [], None
        for r in res:
            label = {'direct': T('set.pmode_direct'),
                     'system': T('set.pmode_system'),
                     'custom': T('set.pmode_custom')}.get(r['mode'], r['mode'])
            label = label.split('（')[0]
            if r['ok']:
                parts.append('%s %d ms' % (label, r['ms']))
                if best is None or r['ms'] < best[2]:
                    best = (r['mode'], label, r['ms'])
            else:
                parts.append('%s ✗' % label)
        self.lb_net.setText(' · '.join(parts))
        if best:
            if best[0] != (settings.get('net_proxy_mode') or 'direct'):
                self.win.toast(T('set.net_test_switch', name=best[1], ms=best[2]),
                               kind='warn', hold=6200)
            else:
                self.win.toast(T('set.net_test_ok', name=best[1], ms=best[2]),
                               kind='ok', hold=4200)

    # ---------------- 微信读书登录（只为 AI 大纲）----------------
    def on_open_weread(self):
        """打开微信读书，让用户先登录（登录态由浏览器自己保持）。"""
        QDesktopServices.openUrl(QUrl('https://weread.qq.com/'))

    def on_paste_cookie(self):
        """从剪贴板读入 Cookie —— 省得在一个小框里手工粘贴长字符串。"""
        try:
            txt = QApplication.clipboard().text() or ''
        except Exception:
            txt = ''
        txt = txt.strip()
        if not txt:
            self.lb_cookie_keys.setText(T('set.cookie_paste_fail'))
            return
        self.ed_cookie.setText(txt)          # 会触发 on_cookie 落盘
        self._sync_cookie_keys()
        self.win.toast(T('set.cookie_pasted', n=len(txt)), kind='ok')

    def on_cookie(self, text):
        if self._loading:
            return
        settings.set_value('weread_cookie', (text or '').strip())
        self._sync_cookie_keys()

    def on_test_cookie(self):
        """测一次：拿本地书库里的书试 outline/check + inner，确认登录态真的有效。

        这一步很关键 —— 因为不同书的 AI 大纲覆盖差别很大（《活着》整本都没有），
        所以要在书库里找一本「确实有要点」的来验证，才能说明 Cookie 是有效的。
        """
        ck = (self.ed_cookie.text() or '').strip()
        if not ck:
            self.lb_cookie_state.setText(T('set.cookie_fail', msg='Cookie 还是空的'))
            return
        self.lb_cookie_state.setText(T('outline.loading'))
        QApplication.processEvents()
        try:
            books = self.win.kb.books() or []
            if not books:
                self.lb_cookie_state.setText(
                    T('set.cookie_fail', msg='本地书库是空的，先抓一本书'))
                return
            for b in books[:3]:
                chs = core.fetch_outline_chapters(b['book_id'], cookie=ck)
                has = [c for c in chs if c.get('hasKeyPoint') == 1]
                if not has:
                    continue
                raw = core.fetch_outline_content(b['book_id'],
                                                 [has[0]['chapterUid']], cookie=ck)
                got = core.outline_parse(raw)
                self.lb_cookie_state.setText(
                    T('set.cookie_ok', title=b['title'], n=len(has)))
                if got:
                    self.win.toast('登录态有效：已取到 %d 章内容' % len(got),
                                   kind='ok', hold=3600)
                else:
                    self.win.toast('接口通了，但没解析出内容（返回结构可能变了）',
                                   kind='warn', hold=4600)
                return
            self.lb_cookie_state.setText(
                T('set.cookie_ok', title=books[0]['title'], n=0)
                + '（这几本都没有 AI 大纲，换一本有要点的再试）')
        except Exception as e:
            self.lb_cookie_state.setText(T('set.cookie_fail', msg=str(e)[:70]))

    def on_titlebar(self, state):
        if self._loading:
            return
        settings.set_value('custom_titlebar', bool(state))
        self.win.rebuild()      # 窗口标志要重建才生效

    def on_export_people(self, state):
        if self._loading:
            return
        settings.set_value('export_people', bool(state))
        self.win.toast(T('set.saved'), kind='ok')

    # ------------------------------------------------------------------
    def on_theme(self, key):
        if self._loading:
            return
        settings.set_value('theme', key)
        self.win.apply_style()

    def on_mode(self, key):
        if self._loading:
            return
        settings.set_value('mode', key)
        self.win.apply_style()

    def on_radius(self, v):
        self.lb_radius.setText(str(v))
        if self._loading:
            return
        settings.set_value('radius', int(v))
        self.win.apply_style()

    def on_motion(self, state):
        if self._loading:
            return
        settings.set_value('motion', bool(state))
        W.set_motion(bool(state))

    def on_min_people(self, v):
        if self._loading:
            return
        settings.set_value('min_people', int(v))

    def on_formats(self, _=None):
        """格式多选：至少留一个，否则导出会没有内容。"""
        if self._loading:
            return
        picked = [k for k, cb in self.fmt_checks.items() if cb.isChecked()]
        if not picked:
            picked = ['html']
            self._loading = True
            self.fmt_checks['html'].setChecked(True)
            self._loading = False
        settings.set_value('export_formats', picked)
        self.win.toast(T('set.saved'))

    def on_browse_dir(self):
        start = self.ed_dir.text() or FALLBACK_DIR
        d = QFileDialog.getExistingDirectory(self, T('set.export_dir'), start)
        if d:
            settings.set_value('export_dir', d)
            self.ed_dir.setText(d)
            self.ed_dir.setToolTip(d)
            self.win.refresh_exports()
            self.win.toast(T('set.dir_changed'), kind='ok')

    def on_reset_dir(self):
        settings.set_value('export_dir', '')
        self.ed_dir.setText('')
        self.ed_dir.setToolTip(FALLBACK_DIR)
        self.win.refresh_exports()
        self.win.toast(T('set.dir_changed'), kind='ok')

    # ------------------------------------------------------------ AI 配置
    def _fill_models(self):
        prov = self.cb_provider.currentData()
        cfg = AIm.PROVIDERS.get(prov) or {}
        cur = settings.get('ai_model') or cfg.get('model') or ''
        self.cb_model.blockSignals(True)
        self.cb_model.clear()
        self.cb_model.addItems(cfg.get('models') or [])
        self.cb_model.setCurrentText(cur)
        self.cb_model.blockSignals(False)

    def _load_key(self):
        prov = settings.get('ai_provider')
        self.ed_key.blockSignals(True)
        self.ed_key.setText(settings.get('ai_key_%s' % prov) or '')
        self.ed_key.blockSignals(False)

    def on_provider(self, _=0):
        if self._loading:
            return
        prov = self.cb_provider.currentData()
        settings.set_value('ai_provider', prov)
        settings.set_value('ai_model', '')
        self._fill_models()
        self._load_key()

    def on_model(self, text):
        if self._loading:
            return
        settings.set_value('ai_model', (text or '').strip())

    def on_key(self, text):
        if self._loading:
            return
        settings.set_value('ai_key_%s' % settings.get('ai_provider'),
                           (text or '').strip())

    def open_key_page(self):
        cfg = AIm.PROVIDERS.get(settings.get('ai_provider')) or {}
        url = cfg.get('key_url')
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def on_test_ai(self):
        prov = settings.get('ai_provider')
        key = settings.get('ai_key_%s' % prov) or ''
        cfg = AIm.PROVIDERS.get(prov) or {}
        if cfg.get('need_key') and not key:
            self.win.toast(T('ai.need_key'), kind='warn')
            return
        self.win.toast(T('set.ai_testing'))
        w = AiWorker([{'role': 'user', 'content': '只回复两个字：正常'}],
                     prov, settings.get('ai_model') or '', key,
                     timeout=60, stream=False, temp=0.0, parent=self)
        self._test_worker = w
        w.ok.connect(lambda t: self.win.toast(
            T('set.ai_ok', msg=(t or '')[:16].replace('\n', ' ')), kind='ok'))
        w.err.connect(lambda m: self.win.toast(
            '%s：%s' % (T('ai.failed'), m), kind='warn'))
        w.start()

    def on_test_feishu(self):
        hook = (settings.get('feishu_webhook') or '').strip()
        if not hook:
            self.win.toast(T('set.feishu_need'), kind='warn')
            return
        try:
            feishu.send_text(
                hook, '书脉 BookPulse · 测试消息\n如果你看到这条，说明 Webhook 配置正确。',
                secret=settings.get('feishu_secret') or '')
            self.win.toast(T('set.feishu_sent'), kind='ok')
        except Exception as e:
            self.win.toast('%s：%s' % (T('ai.failed'), e), kind='warn')

    def on_lang(self, code):
        if self._loading or code == i18n.current():
            return
        settings.set_value('lang', code)
        i18n.set_lang(code)
        self.win.rebuild()

    def on_clear(self):
        if QMessageBox.question(
                self, T('dlg.confirm_clear'), T('dlg.clear_text'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            for b in self.win.kb.books():
                self.win.kb.delete(b['book_id'])
        except Exception:
            pass
        self.refresh_stats()
        self.win.refresh_library()
        self.win.toast(T('set.clear_cache'), kind='ok')

    def on_reset(self):
        settings.reset()
        self.win.rebuild()


# ==========================================================================
# 自绘标题栏（无边框模式下使用）
# ==========================================================================
class TitleBar(QWidget):
    """自绘标题栏。

    只在设置里打开「无边框窗口」时才出现。
    窗口缩放 / 贴边 / 双击最大化 靠 MainWindow.nativeEvent 处理 WM_NCHITTEST，
    所以原生手感一个都不少 —— 这也是没有用「去掉系统边框自己造轮子」那一套的原因。
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName('TitleBar')
        self.setFixedHeight(40)
        self._drag = None

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 8, 0)
        h.setSpacing(9)
        h.addWidget(W.LogoMark(20))
        self.lb = QLabel('')
        self.lb.setObjectName('TitleText')
        h.addWidget(self.lb)
        h.addStretch(1)

        self.btn_min = QPushButton('\u2013')
        self.btn_max = QPushButton('\u25a1')
        self.btn_close = QPushButton('\u2715')
        for b, name in ((self.btn_min, 'TbMin'), (self.btn_max, 'TbMax'),
                        (self.btn_close, 'TbClose')):
            b.setObjectName(name)
            b.setFixedSize(40, 30)
            b.setCursor(Qt.PointingHandCursor)
            h.addWidget(b)
        self.btn_min.clicked.connect(self.win.showMinimized)
        self.btn_max.clicked.connect(self.toggle_max)
        self.btn_close.clicked.connect(self.win.close)
        self.sync()

    def sync(self):
        self.lb.setText('%s  ·  %s' % (app_name(), T('app.subtitle')))
        self.btn_max.setText('\u2750' if self.win.isMaximized() else '\u25a1')

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()
        self.sync()

    # ---------------------------------------------------------------- 拖动
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is None or not (ev.buttons() & Qt.LeftButton):
            return
        if self.win.isMaximized():
            # 从最大化拖回来时，让光标落在窗口宽度的中部，手感才自然
            self.win.showNormal()
            self._drag = QPoint(self.win.width() // 2, 20)
        self.win.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.toggle_max()


# ==========================================================================
# 主窗口
# ==========================================================================
class MainWindow(QMainWindow):
    def __init__(self, start_page=0):
        super().__init__()
        self.kb = kb.get_store()
        self.watcher = WATCH.Watcher(self.kb)
        self._caption_done = False
        self.setWindowTitle('%s · %s' % (app_name(), T('app.subtitle')))
        self.resize(int(settings.get('win_w')), int(settings.get('win_h')))
        self.setMinimumSize(1060, 690)
        self._build()
        if start_page:
            QTimer.singleShot(0, lambda: self.switch_page(start_page))

        # 方向 6：运行期间的自动增量检查。
        # 刻意不用 Windows 计划任务 —— 那样用户完全不知道它什么时候联网；
        # 放在程序里，联网时机是可预期的，也能随时关掉。
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(10 * 60 * 1000)   # 每 10 分钟醒来判断一次该不该跑
        self._auto_timer.timeout.connect(self.auto_check)
        self._auto_timer.start()
        QTimer.singleShot(9000, self.auto_check)

    # ------------------------------------------------------------------
    def _build(self):
        root = QWidget()
        root.setObjectName('Root')
        self.setCentralWidget(root)

        # 无边框模式下多一层：最上面是自绘标题栏，下面才是「侧栏 | 内容」
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.titlebar = None
        if settings.get('custom_titlebar'):
            self.titlebar = TitleBar(self)
            outer.addWidget(self.titlebar)

        body = QWidget()
        outer.addWidget(body, 1)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sidebar = self._build_sidebar()
        lay.addWidget(self.sidebar)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.topbar = self._build_topbar()
        rv.addWidget(self.topbar)

        self.stack = W.FadeStack()
        self.page_search = SearchPage(self)
        self.page_batch = BatchPage(self)
        self.page_library = LibraryPage(self)
        self.page_insight = InsightPage(self)
        self.page_outline = OutlinePage(self)
        self.page_export = ExportPage(self)
        self.page_settings = SettingsPage(self)
        for p in (self.page_search, self.page_batch, self.page_library,
                  self.page_insight, self.page_outline, self.page_export,
                  self.page_settings):
            self.stack.addWidget(p)
        rv.addWidget(self.stack, 1)
        lay.addWidget(right, 1)

        self.toast_layer = W.Toast(right)

        # 命令面板（覆盖整个窗口）
        self.palette = W.CommandPalette(root)
        self.palette.chosen.connect(self.run_command)
        self.palette.searched.connect(self.search_from_palette)
        self._sync_palette_texts()

        # 快捷键
        QShortcut(QKeySequence('Ctrl+K'), self, activated=self.open_palette)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.focus_search)
        QShortcut(QKeySequence('Ctrl+E'), self, activated=self.do_export)
        QShortcut(QKeySequence('Ctrl+1'), self, activated=lambda: self.switch_page(0))
        QShortcut(QKeySequence('Ctrl+2'), self, activated=lambda: self.switch_page(1))
        QShortcut(QKeySequence('Ctrl+3'), self, activated=lambda: self.switch_page(2))
        QShortcut(QKeySequence('Ctrl+4'), self, activated=lambda: self.switch_page(3))
        QShortcut(QKeySequence('Ctrl+5'), self, activated=lambda: self.switch_page(4))
        QShortcut(QKeySequence('Ctrl+6'), self, activated=lambda: self.switch_page(5))
        QShortcut(QKeySequence('Ctrl+7'), self, activated=lambda: self.switch_page(6))
        QShortcut(QKeySequence('Ctrl+,'), self, activated=lambda: self.switch_page(5))
        QShortcut(QKeySequence('Ctrl+G'), self, activated=self.do_ai_shortcut)
        QShortcut(QKeySequence('Ctrl+R'), self, activated=self.refresh_current)
        QShortcut(QKeySequence('Ctrl+Shift+F'), self, activated=self.toggle_focus)

    def _build_sidebar(self):
        side = QWidget()
        side.setObjectName('Sidebar')
        side.setFixedWidth(214)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(18, 20, 18, 4)
        top.setSpacing(10)
        self.brand_mark = W.LogoMark(34)
        top.addWidget(self.brand_mark)
        bb = QVBoxLayout()
        bb.setSpacing(1)
        self.lb_brand = QLabel(app_name())
        self.lb_brand.setObjectName('Brand')
        self.lb_brand.setStyleSheet('padding:0px;')
        self.lb_brand_sub = QLabel(T('app.subtitle'))
        self.lb_brand_sub.setObjectName('BrandSub')
        self.lb_brand_sub.setStyleSheet('padding:0px;')
        bb.addWidget(self.lb_brand)
        bb.addWidget(self.lb_brand_sub)
        top.addLayout(bb)
        top.addStretch(1)
        sv.addLayout(top)
        sv.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav = [('\U0001F50D', 'nav.search'), ('\U0001F4DA', 'nav.batch'),
               ('\U0001F5C2', 'nav.library'), ('\U0001F4A1', 'nav.insight'),
               ('\U0001F4D6', 'nav.outline'),
               ('\U0001F4C1', 'nav.exports'), ('\u2699', 'nav.settings')]
        for i, (icon, key) in enumerate(nav):
            b = QPushButton('%s\u3000%s' % (icon, T(key)))
            b.setObjectName('NavBtn')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            if i == 0:
                b.setChecked(True)
            self.nav_group.addButton(b, i)
            sv.addWidget(b)
        self.nav_group.idClicked.connect(self.switch_page)

        sv.addStretch(1)

        # 左下角不再挂一个显眼的「打开文件夹」按钮 —— 它已经搬到「导出」旁边了。
        # 这里改成「书库概览 + 可点击的导出目录」，信息密度更高、视觉更安静。
        self.lb_side_stats = QLabel('')
        self.lb_side_stats.setObjectName('SideHint')
        self.lb_side_stats.setWordWrap(True)
        sv.addWidget(self.lb_side_stats)

        sv.addWidget(self._side_hint(T('side.export_dir')))
        self.btn_open_dir = QPushButton('')
        self.btn_open_dir.setObjectName('SideOpen')
        self.btn_open_dir.setCursor(Qt.PointingHandCursor)
        self.btn_open_dir.clicked.connect(self.open_export_dir)
        sv.addWidget(self.btn_open_dir)

        kbd = QLabel(T('side.command_hint'))
        kbd.setObjectName('SideKbd')
        kbd.setWordWrap(True)
        sv.addWidget(kbd)
        self._update_side()
        return side

    def _side_hint(self, text):
        lb = QLabel(text)
        lb.setObjectName('SideHint')
        return lb

    def _update_side(self):
        """刷新侧栏底部：书库概览 + 导出目录（点一下直接打开）。"""
        try:
            d = export_dir()
            name = os.path.basename(d.rstrip('\\/')) or d
            self.btn_open_dir.setText('\U0001F4C2  %s' % name)
            self.btn_open_dir.setToolTip(d)
            st = self.kb.stats()
            self.lb_side_stats.setText(
                T('side.library_stats', books=st['books'], marks=st['marks']))
        except Exception:
            pass

    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName('TopBar')
        bar.setFixedHeight(58)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 18, 0)
        h.setSpacing(10)

        box = QVBoxLayout()
        box.setSpacing(0)
        self.lb_top_title = QLabel(T('nav.search'))
        self.lb_top_title.setObjectName('TopTitle')
        self.lb_top_sub = QLabel(T('app.tagline'))
        self.lb_top_sub.setObjectName('TopSub')
        box.addWidget(self.lb_top_title)
        box.addWidget(self.lb_top_sub)
        h.addLayout(box)
        h.addStretch(1)

        self.btn_cmd = QPushButton('\U0001F50D\u3000%s' % T('cmd.placeholder'))
        self.btn_cmd.setObjectName('ToolBtn')
        self.btn_cmd.setCursor(Qt.PointingHandCursor)
        self.btn_cmd.setMinimumWidth(280)
        self.btn_cmd.clicked.connect(self.open_palette)
        h.addWidget(self.btn_cmd)

        self.btn_lang = QPushButton('EN' if i18n.is_zh() else '中')
        self.btn_lang.setObjectName('ToolBtn')
        self.btn_lang.setFixedWidth(52)
        self.btn_lang.setCursor(Qt.PointingHandCursor)
        self.btn_lang.setToolTip('语言 / Language')
        self.btn_lang.clicked.connect(self.toggle_lang)
        h.addWidget(self.btn_lang)

        dark = cur_mode() == 'dark'
        self.btn_mode = QPushButton('\u2600' if dark else '\U0001F319')
        self.btn_mode.setObjectName('ToolBtn')
        self.btn_mode.setFixedWidth(52)
        self.btn_mode.setCursor(Qt.PointingHandCursor)
        self.btn_mode.clicked.connect(self.toggle_mode)
        h.addWidget(self.btn_mode)
        return bar

    # ------------------------------------------------------------------
    # 主题与重建
    # ------------------------------------------------------------------
    def apply_style(self):
        app = QApplication.instance()
        app.setStyleSheet(theme.build_qss(
            settings.get('theme'), cur_mode(), int(settings.get('radius'))))
        pal = theme.palette(settings.get('theme'), cur_mode(),
                            int(settings.get('radius')))
        W.set_palette(pal)
        W.set_motion(bool(settings.get('motion')))
        try:
            W.set_caption_color(self, color_hex=pal['side_top'],
                                dark=(cur_mode() == 'dark'))
        except Exception:
            pass
        self.brand_mark.update()
        for page in (self.page_library, self.page_export, self.page_search):
            for em in page.findChildren(W.EmptyState):
                em.update()
        try:
            self.btn_mode.setText('\u2600' if cur_mode() == 'dark' else '\U0001F319')
        except Exception:
            pass
        try:
            self._update_side()
        except Exception:
            pass
        self.toast(T('set.saved'))

    def rebuild(self):
        """语言变化后重建窗口，保留当前页面。"""
        idx = self.stack.currentIndex()
        w, h = self.width(), self.height()
        settings.set_value('win_w', w)
        settings.set_value('win_h', h)
        global CURRENT_WIN
        new = MainWindow(start_page=idx)
        new.show()
        CURRENT_WIN = new
        self.close()

    def toggle_lang(self):
        settings.set_value('lang', 'en' if i18n.is_zh() else 'zh')
        i18n.set_lang(settings.get('lang'))
        self.rebuild()

    def toggle_mode(self):
        settings.set_value('mode', 'dark' if cur_mode() == 'light' else 'light')
        self.apply_style()
        dark = cur_mode() == 'dark'
        self.btn_mode.setText('\u2600' if dark else '\U0001F319')

    # ------------------------------------------------------------------
    # 命令面板
    # ------------------------------------------------------------------
    def _commands(self):
        return [
            ('go0', T('cmd.go_search'), 'search sou suo'),
            ('go1', T('cmd.go_batch'), 'batch pi liang'),
            ('go2', T('cmd.go_library'), 'library shu ku'),
            ('go3', T('nav.insight'), 'insight dong cha cross book'),
            ('go4', T('nav.outline'), 'outline ai da gang'),
            ('go5', T('cmd.go_exports'), 'exports dao chu'),
            ('go6', T('cmd.go_settings'), 'settings she zhi'),
            ('ai', T('ai.btn'), 'ai zheng li distill summarize'),
            ('dir', T('cmd.open_dir'), 'folder wen jian jia'),
            ('data', T('cmd.open_data'), 'data shu ju'),
            ('lang', T('cmd.toggle_lang'), 'language yu yan en zh'),
            ('motion', T('cmd.toggle_motion'), 'motion dong xiao'),
            ('mode', T('set.mode'), 'dark light shen se qian se'),
        ]

    def _sync_palette_texts(self):
        self.palette.set_texts(
            T('cmd.placeholder'),
            '↑↓ 选择 · Enter 执行 · Esc 关闭' if i18n.is_zh()
            else '↑↓ navigate · Enter run · Esc close',
            T('cmd.search_book'))

    def open_palette(self):
        self.palette.popup(self._commands())

    def run_command(self, cid):
        if cid == 'go0':
            self.switch_page(0)
        elif cid == 'go1':
            self.switch_page(1)
        elif cid == 'go2':
            self.switch_page(2)
        elif cid == 'go3':
            self.switch_page(3)
        elif cid == 'go4':
            self.switch_page(4)
        elif cid == 'go5':
            self.switch_page(5)
        elif cid == 'go6':
            self.switch_page(6)
        elif cid == 'ai':
            self.do_ai_shortcut()
        elif cid == 'dir':
            self.open_export_dir()
        elif cid == 'data':
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(kb.DB_PATH)))
        elif cid == 'lang':
            self.toggle_lang()
        elif cid == 'motion':
            v = not settings.get('motion')
            settings.set_value('motion', v)
            W.set_motion(v)
            self.toast('Motion: %s' % ('on' if v else 'off'))
        elif cid == 'mode':
            self.toggle_mode()

    def search_from_palette(self, kw):
        self.switch_page(0)
        self.page_search.kw.setText(kw)
        self.page_search.do_search()

    # ------------------------------------------------------------------
    # 快捷键动作
    # ------------------------------------------------------------------
    def focus_search(self):
        self.switch_page(0)
        self.page_search.kw.setFocus()
        self.page_search.kw.selectAll()

    def do_export(self):
        if self.stack.currentIndex() == 0:
            self.page_search.do_export()

    def do_ai_shortcut(self):
        """Ctrl+G：对搜索页当前预览的书发起 AI 整理。"""
        self.switch_page(0)
        self.page_search.do_ai()

    # ------------------------------------------------------------------
    # 专注模式 / 入场动效 / 无边框缩放
    # ------------------------------------------------------------------
    def toggle_focus(self):
        """一键隐藏侧栏与顶栏，只剩正文 —— 阅读时视野干净很多。"""
        self._focus = not getattr(self, '_focus', False)
        self.sidebar.setVisible(not self._focus)
        self.topbar.setVisible(not self._focus)
        if self.titlebar is not None:
            self.titlebar.setVisible(not self._focus)
        self.toast(T('focus.on') if self._focus else T('focus.off'),
                   kind='ok', hold=2600)

    def stagger_in(self, page=None):
        """切页后让卡片错落淡入（每个延后 45ms）。

        注意：Qt 里一个控件只能挂一个 QGraphicsEffect（见 widgets.Card.
        restore_shadow 的注释）—— 动画结束必须【恢复阴影】而不是简单置 None，
        否则卡片的阴影会被这次动画永久顶掉。
        """
        if not settings.get('motion'):
            return
        try:
            page = page or self.stack.currentWidget()
            cards = page.findChildren(W.Card)[:8]

            def _restore(c):
                try:
                    if hasattr(c, 'restore_shadow'):
                        c.restore_shadow()
                    else:
                        c.setGraphicsEffect(None)
                except Exception:
                    pass

            for i, c in enumerate(cards):
                eff = QGraphicsOpacityEffect(c)
                eff.setOpacity(0.0)
                c.setGraphicsEffect(eff)
                a = QPropertyAnimation(eff, b'opacity', c)
                a.setDuration(200)
                a.setStartValue(0.0)
                a.setEndValue(1.0)
                a.setEasingCurve(QEasingCurve.OutCubic)
                QTimer.singleShot(i * 45, a.start)
                QTimer.singleShot(i * 45 + 250, lambda cc=c: _restore(cc))
        except Exception as e:
            print('[stagger_in] error:', e, file=sys.stderr)

    def nativeEvent(self, eventType, message):
        """无边框模式下自己处理 WM_NCHITTEST，把缩放/贴边还给系统。

        这样既拿到了无边框的整体观感，又不用重写一套窗口拖拽逻辑 ——
        Aero Snap、双击最大化、多屏拖拽全部保持原生行为。
        """
        try:
            if (self.titlebar is not None
                    and eventType == b'windows_generic_MSG'):
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:          # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    g = self.frameGeometry()
                    b = 6
                    left = x < g.left() + b
                    right = x >= g.right() - b
                    top = y < g.top() + b
                    bottom = y >= g.bottom() - b
                    if top and left:
                        return True, 13
                    if top and right:
                        return True, 14
                    if bottom and left:
                        return True, 16
                    if bottom and right:
                        return True, 17
                    if left:
                        return True, 10
                    if right:
                        return True, 11
                    if top:
                        return True, 12
                    if bottom:
                        return True, 15
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def auto_check(self):
        """到点了就在后台跑一次关注书单检查（方向 6）。"""
        try:
            if not settings.get('watch_auto'):
                return
            if not self.watcher.list():
                return
            hours = max(1.0, float(settings.get('watch_every') or 6))
            last = settings.get('last_watch') or ''
            if last:
                try:
                    t = datetime.datetime.strptime(last, '%Y-%m-%d %H:%M')
                    if (datetime.datetime.now() - t).total_seconds() < hours * 3600:
                        return
                except Exception:
                    pass
            p = self.page_insight
            if p.watch_worker and p.watch_worker.isRunning():
                return
            p.do_check()
            self.toast(T('insight.checking'))
        except Exception:
            pass

    def refresh_current(self):
        """Ctrl+R：刷新当前页。"""
        idx = self.stack.currentIndex()
        if idx == 2:
            self.page_library.refresh()
        elif idx == 3:
            self.page_insight.refresh()
        elif idx == 4:
            self.page_outline.refresh()
        elif idx == 5:
            self.page_export.refresh()
        elif idx == 6:
            self.page_settings.refresh_stats()
        self.toast('\u21bb %s' % T('chart.title'))

    # ------------------------------------------------------------------
    # 公共
    # ------------------------------------------------------------------
    def toast(self, text, kind='', hold=2200):
        # 成功/警告前面加一个符号，扫一眼就知道结果好坏，不用读完整句
        try:
            mark = {'ok': '\u2713  ', 'warn': '\u26a0  '}.get(kind, '')
            self.toast_layer.show_msg(mark + text, kind=kind, hold=hold)
        except Exception:
            pass

    def show_history(self):
        HistoryDialog(self, self).exec()

    def switch_page(self, idx):
        self.stack.fade_to(idx)
        btn = self.nav_group.button(idx)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        titles = ['nav.search', 'nav.batch', 'nav.library', 'nav.insight',
                  'nav.outline', 'nav.exports', 'nav.settings']
        if 0 <= idx < len(titles):
            self.lb_top_title.setText(T(titles[idx]))
        self._update_side()
        QTimer.singleShot(70, lambda: self.stagger_in(self.stack.widget(idx)))
        if idx == 2:
            self.page_library.refresh()
        elif idx == 3:
            self.page_insight.refresh()
        elif idx == 4:
            self.page_outline.refresh()
        elif idx == 5:
            self.page_export.refresh()
        elif idx == 6:
            self.page_settings.refresh_stats()

    def refresh_exports(self):
        self.page_export.refresh()

    def refresh_library(self):
        self.page_library.refresh()

    def open_export_dir(self):
        os.makedirs(export_dir(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(export_dir()))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        try:
            if self.toast_layer.isVisible():
                self.toast_layer.move(self.toast_layer._target_pos())
        except Exception:
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._caption_done:
            self._caption_done = True
            pal = theme.palette(settings.get('theme'), cur_mode())
            f = lambda: W.set_caption_color(self, color_hex=pal['side_top'],
                                            dark=(cur_mode() == 'dark'))
            f()
            QTimer.singleShot(60, f)

    def closeEvent(self, ev):
        try:
            settings.set_value('win_w', self.width(), save_now=False)
            settings.set_value('win_h', self.height(), save_now=False)
            settings.write()
        except Exception:
            pass
        # 注意：kb 是全局单例，切换语言会重建窗口，这里不能关闭它的连接
        super().closeEvent(ev)


CURRENT_WIN = None


def set_app_user_model_id():
    """告诉 Windows「这是一个独立应用」。

    不设的话，任务栏会把程序归到 python.exe 名下，图标也会显示成 Python 的。
    必须在 QApplication 创建之前调用。
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'BookPulse.WeReadHighlights.2')
    except Exception:
        pass


def app_icon():
    """优先用打包好的 app.ico（多尺寸，任务栏与资源管理器都清晰）；
    找不到时退回即时绘制的 LogoMark。"""
    for p in (os.path.join(APP_DIR, 'app.ico'), os.path.join(HERE, 'app.ico')):
        if os.path.exists(p):
            ic = QIcon(p)
            if not ic.isNull():
                return ic
    try:
        return QIcon(W.LogoMark(64).grab())
    except Exception:
        return QIcon()


def close_splash():
    """关掉 PyInstaller 的启动画面（只有启用 --splash 打包时才存在）。

    单文件 exe 要先解压 150MB 才能跑 Python，这段时间由 bootloader 显示启动图，
    否则用户看到的就是「双击了没反应」。
    """
    try:
        # 必须先查环境变量：PyInstaller 在**没有** --splash 时也会把 pyi_splash
        # 模块打进去，此时 import 它会打出一整段吓人的 traceback。
        if not os.environ.get('_PYI_SPLASH_IPC'):
            return
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass


def main():
    os.makedirs(export_dir(), exist_ok=True)
    settings.load()
    i18n.set_lang(settings.get('lang'))
    W.set_motion(bool(settings.get('motion')))
    apply_net_settings()

    # 必须在 QApplication 之前：让 Windows 把本程序当成独立应用，任务栏才会用我们的图标
    set_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName(app_name())

    # PDF 由界面层提供（依赖 Qt），在这里注册进 core 的渲染器表
    core.register_renderer('pdf', render_pdf, ext='.pdf', binary=True)
    app.setStyle('Fusion')
    app.setStyleSheet(theme.build_qss(
        settings.get('theme'), cur_mode(), int(settings.get('radius'))))
    app.setFont(QFont('Microsoft YaHei UI', 9))
    W.set_palette(theme.palette(settings.get('theme'), cur_mode()))

    ic = app_icon()
    if not ic.isNull():
        app.setWindowIcon(ic)

    global CURRENT_WIN
    CURRENT_WIN = MainWindow()
    CURRENT_WIN.setWindowIcon(ic)
    if settings.get('custom_titlebar'):
        # 无边框在 show() 之前设置才生效；缩放/贴边由 nativeEvent 兜住
        CURRENT_WIN.setWindowFlags(CURRENT_WIN.windowFlags() | Qt.FramelessWindowHint)
    CURRENT_WIN.show()
    close_splash()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
