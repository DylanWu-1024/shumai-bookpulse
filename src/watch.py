# -*- coding: utf-8 -*-
"""
关注书单 + 定时增量检查（方向 6 的引擎）
================================================================================
「增量」怎么做才有价值：
  每次检查都抓一次最新全量 → 存成新快照 → 与上一快照比对，
  只把**新出现的**和**人数上涨的**划线挑出来。

所以这个模块真正的产出不是「又一份数据」，而是
「这几天大家开始关注什么了」——这才是值得推到飞书的东西。

依赖：core（抓取）+ store（快照比对）。刻意不依赖 Qt，
这样将来想在命令行 / GitHub Actions 里跑定时任务也能直接复用。
"""
import time
import datetime


class Watcher:
    def __init__(self, store):
        self.store = store
        self.last_error = ''

    # ------------------------------------------------------------------ 书单
    def add(self, book, note=''):
        """把一本书加入关注。book 需要含 bookId / title / author。"""
        try:
            bid = (book or {}).get('bookId') or ''
            if not bid:
                return False
            self.store.conn.execute(
                'INSERT OR REPLACE INTO watch(book_id,title,author,added_at,note,'
                'last_check,last_n) VALUES(?,?,?,?,?,'
                'COALESCE((SELECT last_check FROM watch WHERE book_id=?),\'\'),'
                'COALESCE((SELECT last_n FROM watch WHERE book_id=?),0))',
                (bid, book.get('title', ''), book.get('author', ''),
                 datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), note or '', bid, bid))
            self.store.conn.commit()
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def remove(self, book_id):
        try:
            self.store.conn.execute('DELETE FROM watch WHERE book_id=?', (book_id,))
            self.store.conn.commit()
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def list(self):
        try:
            return [dict(r) for r in self.store.conn.execute(
                'SELECT * FROM watch ORDER BY added_at DESC')]
        except Exception as e:
            self.last_error = str(e)
            return []

    def has(self, book_id):
        try:
            return self.store.conn.execute(
                'SELECT 1 FROM watch WHERE book_id=?', (book_id,)).fetchone() is not None
        except Exception:
            return False

    def count(self):
        try:
            return self.store.conn.execute('SELECT COUNT(*) n FROM watch').fetchone()['n']
        except Exception:
            return 0

    # ------------------------------------------------------------- 增量检查
    def check_one(self, row, top=0, timeout=25, interval=0.0):
        """检查一本书，返回：
            {'ok', 'err', 'book', 'title', 'author', 'trends', 'total', 'new_count'}
        刻意吞掉异常：一本书失败不能拖垮整批。
        """
        import core

        bid = row.get('book_id') or row.get('bookId') or ''
        title = row.get('title') or bid
        out = {'ok': False, 'err': '', 'book_id': bid, 'title': title,
               'author': row.get('author') or '', 'trends': [], 'total': None,
               'new_count': 0, 'up_count': 0}
        if interval:
            time.sleep(interval)

        book = {'bookId': bid, 'title': title, 'author': row.get('author') or ''}
        try:
            r = core.fetch_by_book(book, top=top, timeout=timeout)
        except Exception as e:
            out['err'] = str(e)
            return out

        out['book'] = r
        out['total'] = r.get('total')

        try:
            prev = self.store.snaps(bid)
            self.store.save(r)
            if len(prev) >= 1:          # 有历史快照才谈得上「增量」
                tr = self.store.trend(bid, top=60)
                out['trends'] = tr
                out['new_count'] = sum(1 for t in tr if t.get('kind') == 'new')
                out['up_count'] = sum(1 for t in tr if t.get('kind') == 'up')
            out['ok'] = True
        except Exception as e:
            out['err'] = '入库失败：%s' % e
            return out

        try:
            self.store.conn.execute(
                'UPDATE watch SET last_check=?, last_n=? WHERE book_id=?',
                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                 int(r.get('all_count') or 0), bid))
            self.store.conn.commit()
        except Exception:
            pass
        return out

    def check_all(self, top=0, timeout=25, gap=3.0, on_progress=None, should_stop=None):
        """逐个检查关注的书。gap 为每本之间的间隔秒数（防风控）。"""
        rows = self.list()
        results = []
        for i, row in enumerate(rows):
            if should_stop and should_stop():
                break
            if on_progress:
                try:
                    on_progress(i + 1, len(rows), row)
                except Exception:
                    pass
            res = self.check_one(row, top=top, timeout=timeout,
                                 interval=gap if i else 0.0)
            results.append(res)
        return results


# --------------------------------------------------------------------------
# 无界面的纯逻辑：把检查结果整理成一段可推送给人的摘要
# --------------------------------------------------------------------------
def summarize(results, limit_per_book=8):
    """返回 [(book_title, author, lines[])]，供飞书卡片 / 界面展示共用。"""
    out = []
    for r in results:
        if not r.get('ok'):
            continue
        lines = []
        for t in (r.get('trends') or [])[:limit_per_book]:
            text = (t.get('text') or '').replace('\n', ' ').strip()
            if len(text) > 80:
                text = text[:80] + '…'
            if t.get('kind') == 'new':
                lines.append('🆕 %s（%s 人划线）' % (text, _num(t.get('new'))))
            else:
                lines.append('🔥 %s（+%s → %s 人划线）'
                             % (text, _num(t.get('delta')), _num(t.get('new'))))
        if lines:
            out.append((r.get('title') or '', r.get('author') or '', lines))
    return out


def plain_summary(results):
    """给控制台 / 日志看的纯文本摘要。"""
    lines = []
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    lines.append('书脉 · 关注书单增量检查（%s）' % ts)
    hit = 0
    for r in results:
        if not r.get('ok'):
            lines.append('✗ 《%s》检查失败：%s' % (r.get('title'), r.get('err')))
            continue
        n_new, n_up = r.get('new_count') or 0, r.get('up_count') or 0
        if n_new or n_up:
            hit += 1
            lines.append('《%s》：新增 %d 条，上涨 %d 条'
                         % (r.get('title'), n_new, n_up))
            for t in (r.get('trends') or [])[:5]:
                text = (t.get('text') or '').replace('\n', ' ')[:60]
                if t.get('kind') == 'new':
                    lines.append('    🆕 %s' % text)
                else:
                    lines.append('    🔥 %s（+%s）' % (text, _num(t.get('delta'))))
        else:
            lines.append('《%s》：无变化' % r.get('title'))
    if not hit:
        lines.append('本次没有发现新晋热门划线。')
    return '\n'.join(lines)


def _num(n):
    try:
        n = int(n or 0)
    except Exception:
        return '0'
    if n >= 10000:
        return '%.1f万' % (n / 10000.0)
    return str(n)
