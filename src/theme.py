# -*- coding: utf-8 -*-
"""
主题系统 —— 4 套主色 × 明暗两种模式，任意组合
================================================================================
设计目标：简洁专业（骨架）+ 青春活泼（配色与圆角）+ 大量自定义（用户可换）+ 优美克制动效

配色 = 主色系（ACCENTS）× 中性色系（NEUTRALS）
    主色决定气质，中性色决定明暗 —— 两者组合出 8 种外观，QSS 模板只写一份。

改配色只需要动下面两个字典；QSS 模板里全部用 %(NAME)s 引用，一处生效。
注意：
  · QSS 不支持 box-shadow → 阴影用 QGraphicsDropShadowEffect
  · QSS 不支持 transition  → 过渡动效用 QPropertyAnimation（见 widgets.py）
  · 占位符必须写全 %(NAME)s，漏掉结尾的 s 会报 unsupported format character
"""

# ---------------------------------------------------------------- 主色系
ACCENTS = {
    'violet': {'p': '#6366F1', 'pd': '#4F46E5', 'pl': '#7C3AED', 'soft': '#EEF0FB', 'acc': '#F472B6'},
    'mint':   {'p': '#10B981', 'pd': '#059669', 'pl': '#14B8A6', 'soft': '#E6F7F1', 'acc': '#FACC15'},
    'peach':  {'p': '#FB7185', 'pd': '#E11D48', 'pl': '#FB923C', 'soft': '#FFEFF2', 'acc': '#FDBA74'},
    'ocean':  {'p': '#0EA5E9', 'pd': '#0284C7', 'pl': '#06B6D4', 'soft': '#E4F5FD', 'acc': '#A78BFA'},
}

THEME_LABELS = {
    'violet': ('蓝紫暮光', 'Violet Dusk'),
    'mint':   ('青柠薄荷', 'Fresh Mint'),
    'peach':  ('蜜桃气泡', 'Peach Soda'),
    'ocean':  ('深海蔚蓝', 'Deep Ocean'),
}

THEME_ORDER = ['violet', 'mint', 'peach', 'ocean']

# ---------------------------------------------------------------- 中性色系
NEUTRALS = {
    'light': {
        'bg': '#F7F8FE', 'card': '#FFFFFF', 'ink': '#1E1B4B', 'ink_sub': '#37395C',
        'muted': '#8B8FAE', 'line': '#E7E9F7', 'input_border': '#DBDFF2',
        'hover': '#F8F9FE', 'grid': '#F2F3FB', 'head': '#FAFBFE', 'border_hl': '#C7CBF5',
        'dis_bg': '#E8EAF6', 'dis_fg': '#A9ADCB',
        'side_top': '#272361', 'side_bot': '#1A1740',
        'side_text': '#C7D2FE', 'side_muted': '#6B6FA8',
        'log_bg': '#16133A', 'log_fg': '#A5B4FC',
        'danger': '#F43F5E', 'danger_soft': '#FFE4E9', 'danger_ink': '#BE123C',
        'success': '#10B981', 'warn': '#F59E0B',
        'scrim': 'rgba(20,18,45,0.38)',
        'scrim_rgba': (20, 18, 45, 97),
        # 磨砂玻璃：卡片半透明、顶部一条高光边，好让底下的光晕透上来
        'card_glass': 'rgba(255,255,255,0.74)',
        'card_hi': 'rgba(255,255,255,0.95)',
        'glass_on': True,
    },
    'dark': {
        'bg': '#12111F', 'card': '#1C1B2E', 'ink': '#EDEDF7', 'ink_sub': '#C9CBDF',
        # muted 提亮一档（#8A8DA8 → #A2A6C6）：Hint/PageDesc 都是 12px 小字，
        # 旧值在暗背景上对比度只有 ~5:1，玻璃模式下更糊（磊哥实测反馈看不清）
        'muted': '#A2A6C6', 'line': '#2A2942', 'input_border': '#35344F',
        'hover': '#242339', 'grid': '#23223A', 'head': '#1A1930', 'border_hl': '#4A4880',
        'dis_bg': '#26253D', 'dis_fg': '#6B6D8C',
        'side_top': '#1A1930', 'side_bot': '#121120',
        'side_text': '#CBD5FE', 'side_muted': '#8D91C2',
        'log_bg': '#0C0B16', 'log_fg': '#A5B4FC',
        'danger': '#FB7185', 'danger_soft': '#3A1E29', 'danger_ink': '#FDA4AF',
        'success': '#34D399', 'warn': '#FBBF24',
        'scrim': 'rgba(0,0,0,0.55)',
        'scrim_rgba': (0, 0, 0, 140),
        'card_glass': 'rgba(30,29,50,0.72)',
        'card_hi': 'rgba(255,255,255,0.10)',
        'glass_on': True,
    },
}

DEFAULT_THEME = 'violet'
DEFAULT_MODE = 'light'


def _mix(hex_a, hex_b, ratio_b):
    """把两个颜色按比例混合，用于从主色推导浅底。"""
    def rgb(h):
        h = h.lstrip('#')
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    try:
        a, b = rgb(hex_a), rgb(hex_b)
        m = tuple(int(a[i] * (1 - ratio_b) + b[i] * ratio_b) for i in range(3))
        return '#%02X%02X%02X' % m
    except Exception:
        return hex_a


def system_dark():
    """Windows 是否处于深色模式（读「应用使用浅色主题」这个值）。

    这是只读注册表查询，失败就保守地当作浅色 —— 界面绝不因为读不到系统偏好而崩。
    """
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        try:
            v, _ = winreg.QueryValueEx(k, 'AppsUseLightTheme')
        finally:
            winreg.CloseKey(k)
        return int(v) == 0
    except Exception:
        return False


def resolve_mode(mode):
    """把设置里的 'auto' 解析成真正生效的 'light' / 'dark'。"""
    if mode == 'auto':
        return 'dark' if system_dark() else 'light'
    return mode if mode in ('light', 'dark') else 'light'


def palette(theme=DEFAULT_THEME, mode=DEFAULT_MODE, radius=12, glass=True):
    """把主色系和中性色系合成一份完整调色板。

    glass=False 时把卡片还原成实心、根容器自己负责底色 ——
    相当于整条磨砂玻璃链路整体关掉，而不是半开（半开会出现
    「卡片半透明但背后什么都没有」的灰蒙蒙效果）。
    """
    acc = ACCENTS.get(theme) or ACCENTS[DEFAULT_THEME]
    neu = NEUTRALS.get(mode) or NEUTRALS[DEFAULT_MODE]
    p = dict(neu)
    p.update({
        'PRIMARY': acc['p'], 'PRIMARY_D': acc['pd'], 'PRIMARY_L': acc['pl'],
        'PRIMARY_SOFT': acc['soft'], 'ACCENT': acc['acc'],
        'RADIUS': radius,
    })
    # 深色模式下主色浅底要压暗，否则浅色块在暗背景上会刺眼
    if mode == 'dark':
        p['PRIMARY_SOFT'] = _mix(acc['p'], '#12111F', 0.80)
    p['INK'] = p['ink']
    p['GLASS'] = bool(glass)
    p['DARK'] = (mode == 'dark')
    if not glass:
        p['card_glass'] = p['card']
        p['card_hi'] = p['line']
        p['root_bg'] = p['bg']          # 关掉玻璃时由根容器自己铺底
    else:
        p['root_bg'] = 'transparent'    # 开着时底色由背景层画（它才能透出光晕）
    return p


# ==========================================================================
# 全局样式表
# ==========================================================================
_QSS_TEMPLATE = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }

#Root { background: %(root_bg)s; }

/* 无边框模式下的自绘标题栏（与侧栏同色，整体感更强） */
#TitleBar { background: %(side_top)s; }
#TitleText { color: %(side_text)s; font-size: 12.5px; font-weight: 500; }
#TbMin, #TbMax {
    background: transparent; border: 0; border-radius: 7px;
    color: %(side_text)s; font-size: 13px;
}
#TbMin:hover, #TbMax:hover { background: rgba(255,255,255,0.16); }
#TbClose {
    background: transparent; border: 0; border-radius: 7px;
    color: %(side_text)s; font-size: 12px;
}
#TbClose:hover { background: #E5484D; color: #FFFFFF; }

/* ------------------------------------------------------------ 侧栏 */
#Sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 %(side_top)s, stop:1 %(side_bot)s);
}
#Brand { color: #FFFFFF; font-size: 19px; font-weight: 600; letter-spacing: 1px; }
#BrandSub { color: %(side_muted)s; font-size: 10.5px; letter-spacing: .6px; }
#NavBtn {
    color: %(side_text)s; text-align: left; padding: 11px 14px 11px 12px;
    border: 0; border-left: 3px solid transparent; background: transparent;
    font-size: 13.5px; border-radius: 0px; margin: 2px 10px 2px 6px;
}
#NavBtn:hover { background: rgba(255,255,255,0.09); color: #FFFFFF; }
#NavBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 %(PRIMARY)s, stop:1 %(PRIMARY_L)s);
    color: #FFFFFF; font-weight: 600; border-left: 3px solid %(ACCENT)s;
}
#SideHint { color: %(side_muted)s; font-size: 11px; padding: 6px 18px 2px 18px; }
#SidePath { color: %(side_text)s; font-size: 11px; padding: 0 18px 8px 18px; }
#SideOpen {
    color: #FFFFFF; background: rgba(255,255,255,0.12); border: 0; border-radius: 9px;
    padding: 10px 14px; margin: 4px 14px 8px 14px; font-size: 12.5px; font-weight: 500;
}
#SideOpen:hover { background: %(PRIMARY)s; }
#SideKbd { color: %(side_muted)s; font-size: 10.5px; padding: 0 18px 16px 18px; }

/* ------------------------------------------------------------ 顶栏（工具栏） */
#TopBar { background: %(card_glass)s; border-bottom: 1px solid %(line)s; }
#TopTitle { color: %(INK)s; font-size: 15px; font-weight: 600; }
#TopSub { color: %(muted)s; font-size: 11.5px; }
#ToolBtn {
    background: %(hover)s; color: %(ink_sub)s; border: 1px solid %(line)s;
    border-radius: 9px; padding: 7px 13px; font-size: 12.5px; font-weight: 500;
}
#ToolBtn:hover { background: %(PRIMARY_SOFT)s; color: %(PRIMARY_D)s; border-color: %(border_hl)s; }
#SearchBox {
    border: 1px solid %(input_border)s; border-radius: 10px; padding: 8px 13px;
    background: %(hover)s; font-size: 13px; color: %(INK)s;
}
#SearchBox:focus { border: 1px solid %(PRIMARY)s; background: %(card)s; }

/* ------------------------------------------------------------ 页面标题 */
#PageTitle { font-size: 20px; font-weight: 600; color: %(INK)s; }
#PageDesc { color: %(muted)s; font-size: 12.5px; }
#SetSummary {
    background: %(hover)s; color: %(ink_sub)s; border: 1px solid %(line)s;
    border-radius: 10px; padding: 9px 14px; font-size: 12.5px;
}
#CardTitle { font-size: 13px; font-weight: 600; color: %(ink_sub)s; }
#Hint { color: %(muted)s; font-size: 12px; }
#Kbd {
    background: %(hover)s; color: %(ink_sub)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 4px 8px; font-size: 11.5px;
}
#Stat { color: %(INK)s; font-size: 13px; font-weight: 600; }
#MetricLabel { color: %(muted)s; font-size: 11.5px; }
#MetricValue { color: %(INK)s; font-size: 21px; font-weight: 600; }
#Pill {
    color: %(PRIMARY_D)s; background: %(PRIMARY_SOFT)s; border-radius: 9px;
    padding: 2px 9px; font-size: 11.5px; font-weight: 500;
}
#PillAccent {
    color: %(PRIMARY_D)s; background: %(PRIMARY_SOFT)s; border-radius: 9px;
    padding: 2px 9px; font-size: 11.5px; font-weight: 500;
}
#SectionTitle { color: %(ink_sub)s; font-size: 13.5px; font-weight: 600; }

/* ------------------------------------------------------------ 卡片 */
#Card { background: %(card_glass)s; border: 1px solid %(line)s; border-top: 1px solid %(card_hi)s; border-radius: %(RADIUS)spx; }
#CardFlat { background: %(hover)s; border: 1px solid %(line)s; border-radius: %(RADIUS)spx; }
#CardHover { background: %(card_glass)s; border: 1px solid %(line)s; border-radius: %(RADIUS)spx; }
#CardHover:hover { border: 1px solid %(border_hl)s; }

/* ------------------------------------------------------------ 输入控件 */
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    border: 1px solid %(input_border)s; border-radius: 9px; padding: 8px 11px;
    background: %(card)s; font-size: 13px; color: %(INK)s;
    selection-background-color: %(PRIMARY)s; selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid %(PRIMARY)s;
}
/* 数字输入框：隐藏系统自带的上下箭头。
   默认那对按钮会画出一根超出输入框高度的竖线，很脏；
   而且它的配色不受主题控制。数值照样能用滚轮和键盘上下键调整。 */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0px; height: 0px; border: none; background: transparent;
}

QComboBox {
    border: 1px solid %(input_border)s; border-radius: 9px; padding: 8px 11px;
    background: %(card)s; font-size: 13px; color: %(INK)s;
}
QComboBox:focus { border: 1px solid %(PRIMARY)s; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView {
    border: 1px solid %(line)s; border-radius: 9px; background: %(card)s;
    color: %(INK)s; selection-background-color: %(PRIMARY_SOFT)s;
    selection-color: %(PRIMARY_D)s; padding: 4px; outline: none;
}
QCheckBox { color: %(ink_sub)s; font-size: 13px; spacing: 8px; }
QCheckBox::indicator {
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid %(input_border)s; background: %(card)s;
}
QCheckBox::indicator:checked { background: %(PRIMARY)s; border: 1px solid %(PRIMARY)s; }

/* ------------------------------------------------------------ 按钮 */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 %(PRIMARY)s, stop:1 %(PRIMARY_L)s);
    color: #FFFFFF; border: 0; border-radius: 9px;
    padding: 9px 17px; font-size: 13px; font-weight: 600;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 %(PRIMARY_D)s, stop:1 %(PRIMARY)s);
}
QPushButton:pressed { background: %(PRIMARY_D)s; }
QPushButton:disabled { background: %(dis_bg)s; color: %(dis_fg)s; font-weight: 500; }

QPushButton[flat="true"] {
    background: %(PRIMARY_SOFT)s; color: %(PRIMARY_D)s; font-weight: 500;
}
QPushButton[flat="true"]:hover { background: %(border_hl)s; color: %(PRIMARY_D)s; }
QPushButton[flat="true"]:disabled { background: %(dis_bg)s; color: %(dis_fg)s; }

QPushButton[ghost="true"] {
    background: transparent; color: %(muted)s; border: 1px solid %(line)s; font-weight: 500;
}
QPushButton[ghost="true"]:hover { background: %(hover)s; color: %(ink_sub)s; }

QPushButton[danger="true"] {
    background: %(danger_soft)s; color: %(danger_ink)s; font-weight: 500;
}
QPushButton[danger="true"]:hover { background: %(danger)s; color: #FFFFFF; }

/* ------------------------------------------------------------ 列表 / 表格 */
QListWidget, QTableWidget {
    background: %(card)s; border: 1px solid %(line)s; border-radius: %(RADIUS)spx;
    font-size: 13px; color: %(ink_sub)s; outline: none;
}
QListWidget::item { padding: 10px 12px; border-bottom: 1px solid %(grid)s; }
QListWidget::item:hover { background: %(hover)s; }
QListWidget::item:selected { background: %(PRIMARY_SOFT)s; color: %(PRIMARY_D)s; }

QTableWidget { gridline-color: %(grid)s; }
QTableWidget::item { padding: 6px 8px; }
QTableWidget::item:hover { background: %(hover)s; }
QTableWidget::item:selected { background: %(PRIMARY_SOFT)s; color: %(PRIMARY_D)s; }
QHeaderView::section {
    background: %(head)s; color: %(muted)s; border: 0;
    border-bottom: 1px solid %(line)s; padding: 9px 8px;
    font-size: 12px; font-weight: 600;
}
QTableCornerButton::section { background: %(head)s; border: 0; }

/* ------------------------------------------------------------ 进度条 */
QProgressBar {
    border: 0; border-radius: 7px; background: %(grid)s; height: 12px;
    text-align: center; color: transparent;
}
QProgressBar::chunk {
    border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 %(PRIMARY)s, stop:1 %(ACCENT)s);
}

/* ------------------------------------------------------------ 日志区 */
QPlainTextEdit#Log {
    background: %(log_bg)s; color: %(log_fg)s;
    font-family: Consolas, "Courier New", monospace; font-size: 12px;
    border: 1px solid %(line)s; border-radius: %(RADIUS)spx; padding: 11px;
    selection-background-color: %(PRIMARY)s;
}

/* 提示词框：这个是【可编辑】的，给它一点"能写"的视觉暗示，
   并与下面只读的「实际发送内容」区分开 */
QPlainTextEdit#PromptBox {
    background: %(PRIMARY_SOFT)s; border: 1px solid %(border_hl)s;
    border-radius: 10px; padding: 9px 12px; font-size: 12.5px;
    line-height: 1.6; color: %(INK)s;
}
QPlainTextEdit#PromptBox:focus { border: 1px solid %(PRIMARY)s; }

/* ------------------------------------------------------------ AI 大纲正文
   用 QTextBrowser 渲染富文本（四层结构），背景交给外层卡片，
   自己保持透明、无边框，避免出现一个「框里的框」。 */
QTextBrowser#OutlineView {
    background: transparent; border: none;
    padding: 2px 8px 2px 2px; font-size: 14px;
}
#Legend { color: %(muted)s; font-size: 11.5px; padding-left: 10px; }

/* ------------------------------------------------------------ 滚动条 */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: %(input_border)s; border-radius: 5px; min-height: 34px;
}
QScrollBar::handle:vertical:hover { background: %(muted)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: %(input_border)s; border-radius: 5px; min-width: 34px;
}
QScrollBar::handle:horizontal:hover { background: %(muted)s; }

/* ------------------------------------------------------------ 提示浮层 */
#Toast {
    background: %(card)s; color: %(INK)s; border-radius: 11px;
    padding: 11px 20px; font-size: 13px; font-weight: 600;
    border: 1px solid %(border_hl)s;
}
#ToastOk { border: 1px solid %(success)s; color: %(success)s; }
#ToastWarn { border: 1px solid %(danger)s; color: %(danger_ink)s; }

/* ------------------------------------------------------------ 命令面板 */
#CmdScrim { background: %(scrim)s; }
#CmdPanel { background: %(card)s; border: 1px solid %(border_hl)s; border-radius: 14px; }
#CmdInput {
    border: 0; border-bottom: 1px solid %(line)s; border-radius: 0px;
    padding: 15px 18px; font-size: 15px; background: transparent; color: %(INK)s;
}
#CmdList { background: transparent; border: 0; border-radius: 0px; }
#CmdList::item { padding: 10px 18px; border-bottom: 0px; border-radius: 8px; }
#CmdList::item:hover { background: %(hover)s; }
#CmdList::item:selected { background: %(PRIMARY_SOFT)s; color: %(PRIMARY_D)s; }
#CmdHint { color: %(muted)s; font-size: 11.5px; padding: 9px 18px; border-top: 1px solid %(line)s; }

/* ------------------------------------------------------------ 空状态 */
#EmptyTitle { color: %(ink_sub)s; font-size: 14.5px; font-weight: 600; }
#EmptyDesc { color: %(muted)s; font-size: 12.5px; }

/* ------------------------------------------------------------ 设置页 */
#SetGroup { color: %(PRIMARY_D)s; font-size: 12.5px; font-weight: 600; }
#ThemeChip {
    border: 1px solid %(line)s; border-radius: 10px; padding: 9px 13px;
    background: %(card)s; color: %(ink_sub)s; font-size: 12.5px; font-weight: 500;
    min-width: 104px;
}
#ThemeChip:hover { border-color: %(border_hl)s; }
#ThemeChip:checked { border: 2px solid %(PRIMARY)s; color: %(PRIMARY_D)s; }

/* ------------------------------------------------------------ 分隔线 */
#HLine { background: %(line)s; max-height: 1px; min-height: 1px; border: 0; }
"""


def build_qss(theme=DEFAULT_THEME, mode=DEFAULT_MODE, radius=12, glass=True):
    """生成完整样式表。换主题 / 换模式 / 改圆角 / 开关玻璃质感时重新调用即可。"""
    p = palette(theme, mode, radius, glass)
    return _QSS_TEMPLATE % p


# 默认样式表（供不需要动态换肤的场景直接用）
QSS = build_qss()
