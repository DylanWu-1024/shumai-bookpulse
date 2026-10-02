# -*- coding: utf-8 -*-
"""
跨书去重合并 —— 把不同书里「说同一件事」的句子归到一起
================================================================================
为什么需要它：同一个道理常常被好几本书用不同的措辞讲。分开看是碎片，
合到一起才看得出「这一点被反复强调」——而这正是最值得记住的部分。

算法：字符 bigram 集合 + Jaccard 相似度 + 并查集
  · 为什么不用编辑距离：3000 条两两比较是 O(n²·m²)，会卡住界面
  · 为什么不用分词：中文分词要拖 jieba（几十 MB），而我们只关心"像不像"
  · bigram 的实测表现：3000 条毫秒级出结果，且对"换个说法"足够敏感

纯标准库，不依赖 Qt —— 将来想放到命令行或定时任务里也能直接用。
"""
import re

# 标点与空白：比较前一律去掉，否则「，」位置不同就会判为不相似
_STRIP = re.compile(
    r'[\s，。、；：！？""\u201c\u201d\u2018\u2019（）《》【】〈〉「」'
    r',\.!\?;:"\'\(\)\[\]<>—\-…·~`]')

# 这些虚词构成的 bigram 太常见，不参与倒排（否则候选集爆炸）
_STOP_GRAMS = {
    '的', '是', '了', '我', '你', '他', '她', '它', '们', '在', '有', '和',
    '就', '都', '而', '也', '不', '这', '那', '一个', '什么', '自己',
}


def normalize(text):
    return _STRIP.sub('', (text or '').lower())


def bigrams(s):
    if not s:
        return set()
    if len(s) < 2:
        return {s}
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def similar_groups(rows, threshold=0.52, min_len=8, min_people=2, max_items=8000):
    """把 rows 里语义相近的划线聚成组。

    rows: [{'book_id','title','author','chapter','text','people'}]
    threshold: 相似度阈值（0.35 宽松 / 0.52 适中 / 0.7 严格）
    min_len:  太短的句子不参与（「做人要善良」这种几乎跟谁都像，没信息量）

    返回按「覆盖书数 → 最大共鸣」排序的组列表：
        [{'items': [...], 'books': n, 'size': n, 'top': int, 'rep': str}]
    只返回 size >= 2 的组（孤立的句子谈不上"合并"）。
    """
    cands = []
    for r in (rows or [])[:max_items]:
        text = (r.get('text') or '').strip()
        norm = normalize(text)
        if len(norm) < int(min_len):
            continue
        try:
            if int(r.get('people') or 0) < int(min_people):
                continue
        except Exception:
            pass
        cands.append({'row': r, 'norm': norm})

    n = len(cands)
    if n < 2:
        return []

    grams = [bigrams(c['norm']) for c in cands]

    # 倒排：bigram → 出现过的条目
    inv = {}
    for i, g in enumerate(grams):
        for x in g:
            if x in _STOP_GRAMS:
                continue
            inv.setdefault(x, []).append(i)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Jaccard >= t 时交集至少占较小的那个集合的 t/(1+t) 左右，
    # 用这个下界先剪掉绝大多数不可能的组合。
    for i in range(n):
        gi = grams[i]
        if not gi:
            continue
        need = max(2, int(len(gi) * threshold / (1.0 + threshold)))
        shared = {}
        for x in gi:
            if x in _STOP_GRAMS:
                continue
            for j in inv.get(x, ()):
                if j > i:                      # 只跟后面的比，避免重复
                    shared[j] = shared.get(j, 0) + 1
        for j, c in shared.items():
            if c < need:
                continue
            if jaccard(gi, grams[j]) >= threshold:
                union(i, j)

    buckets = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)

    out = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        items = [cands[i]['row'] for i in members]
        # 代表句：取最长的那条（信息通常最完整）
        items.sort(key=lambda r: (-int(r.get('people') or 0)))
        rep = max(items, key=lambda r: len(r.get('text') or '')).get('text') or ''
        books = len({r.get('book_id') for r in items})
        out.append({
            'items': items,
            'size': len(items),
            'books': books,
            'top': max(int(r.get('people') or 0) for r in items),
            'rep': rep,
        })

    # 跨的书越多越有价值；同分时看单条共鸣
    out.sort(key=lambda g: (-g['books'], -g['top'], -g['size']))
    return out


def dedup_ratio(rows, groups):
    """返回 (原始条数, 合并后条数, 压缩率)。用来告诉用户"省掉了多少"。"""
    total = len(rows or [])
    merged = total
    for g in groups:
        merged -= (g['size'] - 1)
    return total, max(0, merged), (1 - merged / float(total)) if total else 0.0


def to_markdown(groups, book_count=0, threshold=None):
    """把合并结果导成 Markdown —— 既可以存档，也可以直接喂给 AI。"""
    L = ['# 跨书观点合并', '']
    if book_count:
        L.append('- 覆盖书目：%d 本' % book_count)
    if threshold is not None:
        L.append('- 相似度阈值：%.2f' % threshold)
    L.append('- 合并出 %d 组共同观点' % len(groups))
    L += ['', '---', '']
    for gi, g in enumerate(groups, 1):
        L.append('## %d. %s' % (gi, (g['rep'] or '').strip()))
        L.append('')
        L.append('> 出现在 %d 本书 · %d 条 · 最高 %s 人划线'
                 % (g['books'], g['size'], g['top']))
        L.append('')
        for r in g['items']:
            L.append('- 《%s》%s  %s' % (r.get('title') or '', 
                                       ('· ' + r.get('chapter')) if r.get('chapter') else '',
                                       (r.get('text') or '').strip()))
        L.append('')
    return '\n'.join(L)
