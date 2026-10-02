# -*- coding: utf-8 -*-
"""
思维导图：把热门划线组织成树，再导出成各种通用格式
================================================================================
树结构刻意做得很浅（书名 → 章节 → 划线），因为深度超过三层就不叫导图了，
叫目录。想更深的层次用 AI 整理结果去生成。

导出三种形态：
  · Markdown 大纲 —— XMind / 幕布 / 飞书文档 都能直接粘贴导入
  · OPML         —— 通用大纲交换格式，几乎所有的脑图软件都认
  · 图片         —— 由界面层的自绘控件出 PNG / SVG

纯标准库，不依赖 Qt。
"""
import html


def _clip(text, n):
    t = (text or '').strip().replace('\n', ' ')
    return t if len(t) <= n else t[:n] + '…'


def build_from_result(result, max_per_chapter=8, max_chars=26, max_chapters=40):
    """一本书 → 树。章节按「该章最热一条」排序，每章只取最热的若干条。"""
    book = result.get('book') or {}
    ch_map = result.get('chapters') or {}

    buckets = {}
    for it in (result.get('items') or []):
        uid = it.get('chapterUid') or ''
        buckets.setdefault(uid, []).append(it)

    ordered = sorted(
        buckets.items(),
        key=lambda kv: -max(int(x.get('totalCount') or 0) for x in kv[1]))[:max_chapters]

    root = {'title': '《%s》' % (book.get('title') or ''), 'level': 0,
            'note': book.get('author') or '', 'children': []}
    for uid, items in ordered:
        items = sorted(items, key=lambda x: -int(x.get('totalCount') or 0))[:max_per_chapter]
        node = {'title': _clip(ch_map.get(uid) or '未分章', max_chars + 6),
                'level': 1, 'children': []}
        for it in items:
            node['children'].append({
                'title': _clip(it.get('markText'), max_chars),
                'full': (it.get('markText') or '').strip(),
                'level': 2,
                'value': int(it.get('totalCount') or 0),
            })
        root['children'].append(node)
    return root


def build_from_groups(groups, root_title='跨书共同观点', max_groups=40, max_chars=26):
    """跨书合并结果 → 树：根 → 组 → 各书原文。"""
    root = {'title': root_title, 'level': 0, 'note': '', 'children': []}
    for g in (groups or [])[:max_groups]:
        node = {'title': _clip(g.get('rep'), max_chars),
                'note': '%d 本 · %d 条' % (g.get('books', 0), g.get('size', 0)),
                'level': 1, 'children': []}
        seen = set()
        for r in g.get('items') or []:
            key = r.get('book_id') or r.get('title')
            if key in seen:
                continue
            seen.add(key)
            node['children'].append({
                'title': _clip(r.get('text'), max_chars),
                'full': (r.get('text') or '').strip(),
                'level': 2,
                'value': int(r.get('people') or 0),
            })
        root['children'].append(node)
    return root


def stats(tree):
    """返回 (章节数, 叶子数, 最大深度)。"""
    chapters = len(tree.get('children') or [])
    leaves = sum(len(c.get('children') or []) for c in (tree.get('children') or []))
    return chapters, leaves, 2 if leaves else (1 if chapters else 0)


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def to_markdown_outline(tree):
    """Markdown 大纲：XMind / 幕布 / 飞书 可直接粘贴成脑图。"""
    L = ['# %s' % tree.get('title', '')]
    if tree.get('note'):
        L.append('')
        L.append('_%s_' % tree['note'])
    for ch in tree.get('children') or []:
        L.append('')
        note = ('（%s）' % ch['note']) if ch.get('note') else ''
        L.append('## %s%s' % (ch.get('title', ''), note))
        for leaf in ch.get('children') or []:
            L.append('- %s' % leaf.get('title', ''))
    return '\n'.join(L)


def to_opml(tree):
    """OPML 大纲 —— 几乎所有的思维导图 / 大纲软件都支持导入。"""
    def node(n, depth):
        pad = '  ' * depth
        out = ['%s<outline text="%s"' % (pad, html.escape(n.get('title') or '', quote=True))]
        if n.get('note'):
            out.append(' _note="%s"' % html.escape(n['note'], quote=True))
        kids = n.get('children') or []
        if not kids:
            out.append('/>')
            return '\n'.join(out)
        out.append('>')
        for k in kids:
            out.append(node(k, depth + 1))
        out.append('%s</outline>' % pad)
        return '\n'.join(out)

    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<opml version="2.0">\n<head><title>%s</title></head>\n<body>\n%s\n</body>\n</opml>'
            % (html.escape(tree.get('title') or '', quote=True), node(tree, 1)))
