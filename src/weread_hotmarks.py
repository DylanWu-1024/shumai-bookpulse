#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信读书 · 热门划线导出工具（命令行 / 双击版）
================================================================================
本文件只是「命令行外壳」：真正的抓取与导出逻辑全部在 core.py，
桌面版 app_gui.py 共用同一套，改接口只需改一处。

日常用法：双击同目录的 `一键查热门划线.bat`，按提示操作即可。
想要图形界面：双击 `启动工作台.bat`。

命令行用法（可选，方便自动化）：
    python weread_hotmarks.py "一地鸡毛" --all
    python weread_hotmarks.py "活着" --top 100 --fmt md
    python weread_hotmarks.py "活着,围城,一地鸡毛" --batch --fmt md
================================================================================
"""
import os
import sys

# 保证在任意工作目录下运行都能 import 到同目录的 core
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import argparse
import core

# 用 core.app_dir() 而不是脚本目录：源码在 src/ 时，导出仍然落在项目根的 exports/
EXPORT_DIR = os.path.join(core.app_dir(), 'exports')


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def ask(prompt, default=''):
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return v or default


def open_path(path):
    try:
        os.startfile(path)
    except Exception as e:
        print('  （自动打开失败：%s，手动双击即可）' % e)


def pick_count(items_len, default=2):
    """让用户选导出条数，返回实际条数。"""
    print('\n导出条数：')
    print('  [1] 前 50    [2] 前 100（默认）    [3] 全部 %d    [4] 自定义' % items_len)
    sel = ask('请选择（回车=2）：', str(default))
    if sel == '1':
        n = 50
    elif sel == '3':
        n = items_len
    elif sel == '4':
        t = ask('请输入条数：', '100')
        n = int(t) if t.isdigit() else 100
    else:
        n = 100
    return max(1, min(n, items_len))


def pick_format(default='html'):
    print('\n导出格式：')
    keys = list(core.FORMAT_LABELS.keys())
    for i, k in enumerate(keys, 1):
        print('  [%d] %s' % (i, core.FORMAT_LABELS[k]))
    sel = ask('请选择（回车=%s）：' % default, default)
    if sel in keys:
        return sel
    if sel.isdigit() and 1 <= int(sel) <= len(keys):
        return keys[int(sel) - 1]
    return default


# --------------------------------------------------------------------------
# 交互模式
# --------------------------------------------------------------------------
def interactive():
    print('=' * 62)
    print('  微信读书 · 热门划线导出工具（命令行版）')
    print('  导出目录：%s' % EXPORT_DIR)
    print('  ——————————————————————————————————————')
    print('  输入单个书名查一本；输入 b 进入批量模式。')
    print('=' * 62)

    while True:
        kw = ask('\n请输入书名（直接回车退出；输入 b 批量）：')
        if not kw:
            print('已退出。')
            return
        if kw.lower() == 'b':
            interactive_batch()
            continue

        print('\n正在搜索「%s」…' % kw)
        try:
            books = core.search_books(kw)
        except Exception as e:
            print('搜索失败：%s' % e)
            continue
        if not books:
            print('没搜到，换个关键词试试。')
            continue

        shown = books[:10]
        print('找到 %d 本，请选择：\n' % len(books))
        for i, b in enumerate(shown, 1):
            print('  [%2d] %s    %s' % (i, b['title'], b['author']))

        sel = ''
        while True:
            sel = ask('\n请输入序号（回车=1，输入 0 重新搜索）：', '1')
            if sel == '0':
                break
            if sel.isdigit() and 1 <= int(sel) <= len(shown):
                break
            print('输入无效，请重新选择。')
        if sel == '0':
            continue

        book = shown[int(sel) - 1]
        print('\n正在拉取「%s」的热门划线…' % book['title'])
        try:
            r = core.fetch_by_book(book, top=0)
        except Exception as e:
            print('拉取失败：%s' % e)
            continue

        print('共 %s 条。' % r['total'])
        n = pick_count(len(r['items']))
        r['items'] = r['items'][:n]

        fmt = pick_format()
        path = core.export(r, EXPORT_DIR, fmt)
        print('\n✔ 已保存：%s' % path)
        open_path(path)
        print('完成。可以继续查询下一本。')


def interactive_batch():
    print('\n— 批量模式 —')
    print('请逐行输入书名，每行一本；输入空行结束（也可一次粘贴多行）。')
    lines = []
    while True:
        try:
            s = input('  > ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not s:
            break
        lines.append(s)

    if not lines:
        print('没有输入内容，已取消。')
        return

    n = 100
    print('\n导出条数：[1] 前 50   [2] 前 100（默认）   [3] 自定义')
    sel = ask('请选择（回车=2）：', '2')
    if sel == '1':
        n = 50
    elif sel == '3':
        t = ask('请输入条数：', '100')
        n = int(t) if t.isdigit() else 100

    fmt = pick_format()
    print()

    ok, fail, stopped = core.batch_fetch(
        lines, top=n,
        on_log=lambda m: print('  ' + m),
    )

    print('\n正在导出 %d 本到 %s …' % (len(ok), EXPORT_DIR))
    for r in ok:
        print('  ✔ %s' % os.path.basename(core.export(r, EXPORT_DIR, fmt)))
    if fail:
        print('\n失败 %d 本：' % len(fail))
        for f in fail:
            print('  ✗ %s — %s' % (f['keyword'], f['error']))
    if stopped:
        print('（已手动中止）')
    open_path(EXPORT_DIR)


# --------------------------------------------------------------------------
# 命令行模式
# --------------------------------------------------------------------------
def cli(args):
    fmt = args.fmt

    # 批量
    if args.batch:
        kws = [x.strip() for x in args.keyword.replace('，', ',').split(',') if x.strip()]
        ok, fail, stopped = core.batch_fetch(
            kws, top=args.top or core.DEFAULT_TOP,
            on_log=lambda m: print('  ' + m),
        )
        for r in ok:
            print('  ✔ %s' % core.export(r, args.out, fmt))
        for f in fail:
            print('  ✗ %s — %s' % (f['keyword'], f['error']))
        return 0 if ok else 1

    # 单本
    print('正在搜索「%s」…' % args.keyword)
    r = core.fetch_book(args.keyword, top=0)
    print('选中：%s  %s' % (r['book']['title'], r['book']['author']))
    print('共 %s 条热门划线。' % r['total'])

    n = len(r['items']) if args.all else (args.top or core.DEFAULT_TOP)
    r['items'] = r['items'][:max(1, min(n, len(r['items'])))]

    path = core.export(r, args.out, fmt)
    print('✔ 已保存：%s' % path)
    if not args.no_open:
        open_path(path)
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True, description='微信读书热门划线导出')
    ap.add_argument('keyword', nargs='?', help='书名（不填则进入交互模式）')
    ap.add_argument('--top', type=int, default=0, help='导出前 N 条（默认 100）')
    ap.add_argument('--all', action='store_true', help='导出全部')
    ap.add_argument('--batch', action='store_true', help='批量模式，书名用逗号分隔')
    ap.add_argument('--fmt', default='html', choices=list(core.FORMATS.keys()),
                    help='导出格式：html / md / txt / csv / json')
    ap.add_argument('--out', default=EXPORT_DIR, help='导出目录（默认 exports/）')
    ap.add_argument('--no-open', action='store_true', help='生成后不自动打开')
    args = ap.parse_args()

    try:
        if not args.keyword:
            interactive()
            return 0
        return cli(args)
    except core.WereadError as e:
        print('出错：%s' % e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
