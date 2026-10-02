# -*- coding: utf-8 -*-
"""
用户设置（自动持久化到 data/settings.json）
================================================================================
任何一处改动都会立刻写盘，界面上不存在「保存」按钮 —— 改完即生效。
"""
import os
import json

DEFAULTS = {
    'lang': 'zh',            # zh / en
    'theme': 'violet',       # violet / mint / peach / ocean
    'mode': 'light',         # light / dark
    'radius': 12,            # 圆角大小
    'motion': True,          # 界面动效开关（关掉更安静也更省电）
    'def_count': 100,        # 默认导出条数（0 = 全部）
    'sort_mode': 'hot',      # 结果排序：hot = 按划线人数降序；chapter = 按章节顺序
    'def_format': 'html',    # 上次选用的单格式
    'export_formats': ['html'],   # 勾选的导出格式（可多选，用于「多格式导出」）
    'export_dir': '',        # 自定义导出目录（空 = 用程序旁的 exports/）
    'min_people': 2,         # 导出时的划线人数下限（0/1 = 不过滤）
    'export_people': False,  # 导出内容里是否带「N 人划线」（默认不带：导出只要句子）
    'open_after_export': False,   # 导出完成后是否自动打开导出文件夹
    'interval_min': 2.0,     # 批量抓取间隔下限（秒）
    'interval_max': 4.0,     # 批量抓取间隔上限（秒）
    'win_w': 1240,
    'win_h': 800,

    # ---------------- 导出模板（所有格式统一生效）----------------
    'style_font_size': 15,       # 正文字号 pt
    'style_show_chapter': True,  # 是否带章节（分组 / 章节名）
    'style_show_index': True,    # 是否给每条加序号
    'style_accent': '#7C3AED',   # 标题主题色
    'style_line_height': 1.8,    # 行高
    'custom_titlebar': False,    # 无边框窗口（自绘标题栏）

    # ---------------- 网络（抓取）----------------
    'dedupe_threshold': 0.52,    # 跨书去重合并的相似度阈值

    'net_timeout': 25,           # 单次请求超时（秒）
    'net_retries': 3,            # 失败重试次数（指数退避）
    'net_proxy': '',             # 代理，例如 http://127.0.0.1:7890
    # 微信读书登录 Cookie —— **只用于 AI 大纲接口**（那个接口非要登录态）。
    # 抓热门划线等公开接口一律不带 Cookie，保持服务端无法归因到账号。
    'weread_cookie': '',

    # ---------------- AI 助手（方向 2 / 3）----------------
    # Key 刻意用「扁平键」而不是嵌套 dict：settings 内部是浅拷贝，
    # 嵌套结构一旦被就地修改会污染 DEFAULTS，reset 后就回不去了。
    'ai_provider': 'deepseek',
    'ai_model': '',              # 空 = 用该提供商默认模型
    'ai_timeout': 180,
    'ai_stream': True,           # 流式输出（边生成边显示）
    'ai_temp': 0.5,
    'ai_max_items': 200,         # 送给模型的划线条数上限
    'ai_key_deepseek': '',
    'ai_key_siliconflow': '',
    'ai_key_zhipu': '',
    'ai_key_dashscope': '',
    'ai_key_ollama': '',
    'ai_prompt_digest': '',      # 空 = 用内置模板
    'ai_prompt_theme': '',
    'ai_prompt_action': '',
    'ai_prompt_extract': '',

    # ---------------- 飞书推送（方向 6）----------------
    'feishu_webhook': '',
    'feishu_secret': '',
    'feishu_on': False,          # 检查到变化时自动推送
    'feishu_only_changes': True,  # 无变化时不推（避免刷屏）
    'watch_gap': 3.0,            # 关注书单逐本检查的间隔（秒）
    'watch_top': 0,              # 检查时抓取条数（0 = 全部）
    'watch_auto': False,         # 程序运行期间到点自动检查
    'watch_every': 6,            # 自动检查间隔（小时）
    'last_watch': '',            # 上次检查时间
}

_path = None
_data = None


def _default_path():
    try:
        import core
        base = core.app_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'data', 'settings.json')


def path():
    global _path
    if _path is None:
        _path = _default_path()
    return _path


def load():
    """读取设置；文件不存在或损坏时回落默认值。"""
    global _data
    if _data is not None:
        return _data
    d = dict(DEFAULTS)
    try:
        p = path()
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        d[k] = v
    except Exception:
        pass
    _data = d
    return _data


def all():
    return load()


def get(key, default=None):
    d = load()
    if key in d:
        return d[key]
    return DEFAULTS.get(key, default)


def set_value(key, value, save_now=True):
    d = load()
    d[key] = value
    if save_now:
        write()
    return value


def write():
    """落盘。失败静默 —— 设置写不进去不应该影响程序运行。"""
    try:
        p = path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(load(), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reset():
    global _data
    _data = dict(DEFAULTS)
    write()
    return _data
