# -*- coding: utf-8 -*-
"""
微信读书 · 热门划线 —— 本地知识库（SQLite）
================================================================================
它解决三个问题：
  ① 缓存 —— 抓过的书存在本地，再打开秒开、零网络请求（顺带降低风控暴露面）
  ② 离线 —— 没网也能看、能导出（给别人演示时不怕网络抽风）
  ③ 趋势 —— 同一本书多次抓取会留下多份快照，可以对比出
            「哪几句正在被越来越多人划线」

表结构
  books      每本书一行（书名/作者/首次抓取/最近抓取/快照次数）
  snapshots  每一次抓取一行（一本书可有多次，用于对比）
  marks      某次快照里的每条划线

同一条划线如何跨快照对齐？
  优先级 1：接口返回的 range（书内文本区间，最稳）
  优先级 2：正文的 md5（range 缺失时的兜底）

只用标准库 sqlite3，不增加任何依赖。
"""
import os
import sqlite3
import hashlib
import datetime

def _base_dir():
    """数据库基目录。

    打包成 exe 后 __file__ 指向 PyInstaller 的临时解包目录，数据库若跟着它走，
    用户一关程序数据就没了 —— 所以要用 exe 所在目录。
    """
    try:
        import core
        return core.app_dir()
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_base_dir(), 'data', 'hotmarks.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    book_id   TEXT PRIMARY KEY,
    title     TEXT,
    author    TEXT,
    cover     TEXT,
    first_at  TEXT,
    last_at   TEXT,
    snaps     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS snapshots (
    snap_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id   TEXT NOT NULL,
    taken_at  TEXT NOT NULL,
    total     INTEGER,
    n_items   INTEGER
);
CREATE TABLE IF NOT EXISTS marks (
    snap_id     INTEGER NOT NULL,
    book_id     TEXT NOT NULL,
    seq         INTEGER,
    mark_key    TEXT,
    chapter     TEXT,
    text        TEXT,
    people      INTEGER,
    chapter_uid TEXT
);
CREATE INDEX IF NOT EXISTS idx_marks_snap  ON marks(snap_id);
CREATE INDEX IF NOT EXISTS idx_marks_key   ON marks(book_id, mark_key);
CREATE INDEX IF NOT EXISTS idx_snaps_book  ON snapshots(book_id, taken_at);

CREATE TABLE IF NOT EXISTS history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    keyword  TEXT,
    book_id  TEXT,
    title    TEXT,
    author   TEXT,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_at   ON history(at);
CREATE INDEX IF NOT EXISTS idx_hist_kind ON history(kind);

CREATE TABLE IF NOT EXISTS watch (
    book_id    TEXT PRIMARY KEY,
    title      TEXT,
    author     TEXT,
    added_at   TEXT,
    last_check TEXT,
    last_n     INTEGER DEFAULT 0,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS ai_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    kind     TEXT,
    prompt   TEXT,
    provider TEXT,
    model    TEXT,
    title    TEXT,
    book_ids TEXT,
    content  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_at ON ai_log(at);
"""

# 全文索引单独建：万一这台机器的 SQLite 没编译 FTS5，
# 也不能让整个建表脚本挂掉 —— 那种情况自动降级回 LIKE。
#
# 用 trigram 分词器而不是 unicode61：后者会把整句中文当成一个 token，
# 搜「复利」永远搜不到；trigram 按三字滑窗建索引，中文子串检索才正常。
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS marks_fts USING fts5(
    text, book_id UNINDEXED, chapter UNINDEXED, people UNINDEXED, mark_key UNINDEXED,
    tokenize='trigram'
);
"""


def mark_key(item):
    """给一条划线算跨快照稳定的指纹。"""
    r = item.get('range')
    if r:
        return 'r:%s' % r
    t = item.get('markText') or ''
    return 'h:%s' % hashlib.md5(t.encode('utf-8')).hexdigest()[:16]


class Store:
    """本地知识库。所有方法都不抛异常给界面，失败时返回空值并记录在 self.last_error。"""

    def __init__(self, path=DB_PATH):
        self.path = path
        self.last_error = ''
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

        # 全文索引（可选能力，失败不影响主功能）
        self.fts_ok = False
        try:
            self.conn.executescript(_FTS_SCHEMA)
            self.conn.commit()
            self.fts_ok = True
        except Exception:
            self.fts_ok = False
        if self.fts_ok:
            self._ensure_fts()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ 写
    def save(self, result):
        """把一次抓取结果存成一份快照，返回 snap_id；失败返回 None。

        注意：每次抓取都会新增一份快照（而不是覆盖），这样才能做趋势对比。
        """
        try:
            book = result['book']
            bid = book.get('bookId') or ''
            if not bid:
                return None
            now = result.get('fetched_at') or datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            c = self.conn

            row = c.execute('SELECT book_id, snaps FROM books WHERE book_id=?', (bid,)).fetchone()
            if row:
                c.execute(
                    'UPDATE books SET title=?, author=?, cover=?, last_at=?, snaps=? WHERE book_id=?',
                    (book.get('title', ''), book.get('author', ''), book.get('cover', ''),
                     now, (row['snaps'] or 0) + 1, bid))
            else:
                c.execute(
                    'INSERT INTO books(book_id,title,author,cover,first_at,last_at,snaps) '
                    'VALUES(?,?,?,?,?,?,1)',
                    (bid, book.get('title', ''), book.get('author', ''), book.get('cover', ''),
                     now, now))

            cur = c.execute(
                'INSERT INTO snapshots(book_id,taken_at,total,n_items) VALUES(?,?,?,?)',
                (bid, now, int(result.get('total') or 0), len(result.get('items') or [])))
            sid = cur.lastrowid

            chapters = result.get('chapters') or {}
            rows = []
            for i, it in enumerate(result.get('items') or [], 1):
                uid = it.get('chapterUid') or ''
                rows.append((sid, bid, i, mark_key(it),
                             chapters.get(uid, ''),
                             it.get('markText') or '',
                             int(it.get('totalCount') or 0),
                             uid))
            c.executemany(
                'INSERT INTO marks(snap_id,book_id,seq,mark_key,chapter,text,people,chapter_uid) '
                'VALUES(?,?,?,?,?,?,?,?)', rows)
            c.commit()
            self._reindex_book(bid, sid)     # 同步全文索引
            return sid
        except Exception as e:
            self.last_error = str(e)
            return None

    # ------------------------------------------------------------ 全文索引
    def _reindex_book(self, book_id, snap_id=None):
        """把一本书**最新快照**的划线写进全文索引（先清后写）。"""
        if not self.fts_ok:
            return
        try:
            c = self.conn
            c.execute('DELETE FROM marks_fts WHERE book_id=?', (book_id,))
            sid = snap_id
            if sid is None:
                row = c.execute(
                    'SELECT snap_id FROM snapshots WHERE book_id=? '
                    'ORDER BY taken_at DESC, snap_id DESC LIMIT 1', (book_id,)).fetchone()
                sid = row['snap_id'] if row else None
            if sid is None:
                c.commit()
                return
            for r in c.execute(
                    'SELECT mark_key, chapter, text, people FROM marks WHERE snap_id=?', (sid,)):
                c.execute(
                    'INSERT INTO marks_fts(text, book_id, chapter, people, mark_key) '
                    'VALUES(?,?,?,?,?)',
                    (r['text'] or '', book_id, r['chapter'] or '',
                     int(r['people'] or 0), r['mark_key'] or ''))
            c.commit()
        except Exception as e:
            self.last_error = str(e)

    def _ensure_fts(self):
        """老库升级：索引表是空的但已有书 → 全量重建一次。"""
        try:
            n = self.conn.execute('SELECT COUNT(*) n FROM marks_fts').fetchone()['n']
            if n:
                return
            for r in self.conn.execute('SELECT book_id FROM books'):
                self._reindex_book(r['book_id'])
        except Exception:
            pass

    def delete(self, book_id):
        """从书库彻底移除一本书（含所有快照）。"""
        try:
            c = self.conn
            c.execute('DELETE FROM marks WHERE book_id=?', (book_id,))
            c.execute('DELETE FROM snapshots WHERE book_id=?', (book_id,))
            c.execute('DELETE FROM books WHERE book_id=?', (book_id,))
            if self.fts_ok:
                c.execute('DELETE FROM marks_fts WHERE book_id=?', (book_id,))
            c.commit()
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    # ------------------------------------------------------------------ 读
    def has(self, book_id):
        try:
            return self.conn.execute(
                'SELECT 1 FROM books WHERE book_id=?', (book_id,)).fetchone() is not None
        except Exception:
            return False

    def books(self):
        """书库列表（按最近抓取倒序），含每本最新快照的划线数。"""
        sql = """
        SELECT b.book_id, b.title, b.author, b.cover, b.first_at, b.last_at, b.snaps,
               (SELECT COUNT(*) FROM marks m WHERE m.snap_id = (
                    SELECT s.snap_id FROM snapshots s WHERE s.book_id = b.book_id
                    ORDER BY s.taken_at DESC, s.snap_id DESC LIMIT 1)) AS n_marks
        FROM books b
        ORDER BY b.last_at DESC
        """
        try:
            return [dict(r) for r in self.conn.execute(sql)]
        except Exception as e:
            self.last_error = str(e)
            return []

    def latest(self, book_id):
        """取最新一份快照，转换成与 core.fetch_by_book 相同的结构，可直接用于预览/导出。"""
        try:
            c = self.conn
            b = c.execute('SELECT * FROM books WHERE book_id=?', (book_id,)).fetchone()
            if not b:
                return None
            s = c.execute(
                'SELECT * FROM snapshots WHERE book_id=? '
                'ORDER BY taken_at DESC, snap_id DESC LIMIT 1', (book_id,)).fetchone()
            if not s:
                return None

            items, chapters = [], {}
            for m in c.execute('SELECT * FROM marks WHERE snap_id=? ORDER BY seq', (s['snap_id'],)):
                uid = m['chapter_uid'] or ''
                items.append({'chapterUid': uid,
                              'markText': m['text'],
                              'totalCount': m['people']})
                if uid and m['chapter']:
                    chapters[uid] = m['chapter']

            return {
                'book': {'bookId': b['book_id'], 'title': b['title'],
                         'author': b['author'], 'cover': b['cover'] or ''},
                'items': items,
                'chapters': chapters,
                'total': s['total'],
                'all_count': len(items),
                'fetched_at': s['taken_at'],
                'from_cache': True,
                'snap_id': s['snap_id'],
            }
        except Exception as e:
            self.last_error = str(e)
            return None

    def snaps(self, book_id):
        try:
            return [dict(r) for r in self.conn.execute(
                'SELECT snap_id, taken_at, total, n_items FROM snapshots '
                'WHERE book_id=? ORDER BY taken_at DESC, snap_id DESC', (book_id,))]
        except Exception:
            return []

    def trend(self, book_id, top=30):
        """对比最近两份快照，返回热度涨幅榜。

        返回项：
            {'kind':'new'|'up', 'text', 'chapter', 'old', 'new', 'delta'}
            kind='new' 表示这条划线是新出现的（上一份快照里没有）
        """
        try:
            c = self.conn
            ss = c.execute(
                'SELECT snap_id FROM snapshots WHERE book_id=? '
                'ORDER BY taken_at DESC, snap_id DESC LIMIT 2', (book_id,)).fetchall()
            if len(ss) < 2:
                return []
            new_id, old_id = ss[0]['snap_id'], ss[1]['snap_id']

            old = {r['mark_key']: r['people'] for r in c.execute(
                'SELECT mark_key, people FROM marks WHERE snap_id=?', (old_id,))}

            out = []
            for r in c.execute(
                    'SELECT mark_key, chapter, text, people FROM marks WHERE snap_id=?', (new_id,)):
                prev = old.get(r['mark_key'])
                if prev is None:
                    out.append({'kind': 'new', 'chapter': r['chapter'], 'text': r['text'],
                                'old': None, 'new': r['people'], 'delta': None})
                elif r['people'] > prev:
                    out.append({'kind': 'up', 'chapter': r['chapter'], 'text': r['text'],
                                'old': prev, 'new': r['people'],
                                'delta': r['people'] - prev})
            # 新出现的最优先，其后按涨幅降序
            out.sort(key=lambda x: (0 if x['kind'] == 'new' else 1,
                                    -(x['delta'] if x['delta'] is not None else 0)))
            return out[:top]
        except Exception as e:
            self.last_error = str(e)
            return []

    def stats(self):
        try:
            nb = self.conn.execute('SELECT COUNT(*) n FROM books').fetchone()['n']
            nm = self.conn.execute('SELECT COUNT(*) n FROM marks').fetchone()['n']
            ns = self.conn.execute('SELECT COUNT(*) n FROM snapshots').fetchone()['n']
            try:
                nh = self.conn.execute('SELECT COUNT(*) n FROM history').fetchone()['n']
            except Exception:
                nh = 0
            return {'books': nb, 'marks': nm, 'snaps': ns, 'hist': nh,
                    'size': os.path.getsize(self.path) if os.path.exists(self.path) else 0}
        except Exception:
            return {'books': 0, 'marks': 0, 'snaps': 0, 'hist': 0, 'size': 0}

    # ------------------------------------------------------------ 使用记录
    def log(self, kind, keyword='', book=None, detail=''):
        """记一条使用记录。失败静默 —— 记录不该影响主流程。"""
        try:
            b = book or {}
            self.conn.execute(
                'INSERT INTO history(at,kind,keyword,book_id,title,author,detail) '
                'VALUES(?,?,?,?,?,?,?)',
                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 kind, keyword or '', b.get('bookId') or '', b.get('title') or '',
                 b.get('author') or '', detail or ''))
            self.conn.commit()
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def history(self, limit=200):
        try:
            return [dict(r) for r in self.conn.execute(
                'SELECT * FROM history ORDER BY id DESC LIMIT ?', (int(limit),))]
        except Exception:
            return []

    def recent_keywords(self, limit=12):
        """最近搜过的关键词（去重、倒序）—— 给搜索框做历史提示。"""
        try:
            seen, out = set(), []
            for r in self.conn.execute(
                    "SELECT keyword FROM history WHERE kind='search' AND keyword<>'' "
                    "ORDER BY id DESC LIMIT 300"):
                k = r['keyword']
                if k and k not in seen:
                    seen.add(k)
                    out.append(k)
                    if len(out) >= limit:
                        break
            return out
        except Exception:
            return []

    def recent_books(self, limit=12):
        """最近抓取 / 打开过的书（去重、倒序）。"""
        try:
            seen, out = set(), []
            for r in self.conn.execute(
                    "SELECT book_id,title,author FROM history WHERE book_id<>'' "
                    "ORDER BY id DESC LIMIT 400"):
                if r['book_id'] not in seen:
                    seen.add(r['book_id'])
                    out.append({'bookId': r['book_id'], 'title': r['title'],
                                'author': r['author']})
                    if len(out) >= limit:
                        break
            return out
        except Exception:
            return []

    def clear_history(self):
        try:
            self.conn.execute('DELETE FROM history')
            self.conn.commit()
            return True
        except Exception:
            return False

    # ------------------------------------------------- 跨书检索（方向 4）
    _LATEST_SNAP = ('m.snap_id = (SELECT s.snap_id FROM snapshots s '
                    'WHERE s.book_id = m.book_id '
                    'ORDER BY s.taken_at DESC, s.snap_id DESC LIMIT 1)')

    def search_marks(self, keyword, limit=300, min_people=0):
        """在所有已收藏书里做关键词检索（只取每本书的**最新快照**）。

        优先走 FTS5 全文索引；两种情况下自动回落 LIKE：
          · 查询串短于 3 个字 —— trigram 索引按三字滑窗建，2 字查询打不中
          · 本机 SQLite 没编译 FTS5
        两条路径的结果集语义完全一致（都只来自最新快照）。
        """
        kw = (keyword or '').strip()
        if not kw:
            return []

        out = []
        if self.fts_ok and len(kw) >= 3:
            try:
                # 用双引号包成短语，避免用户输入的 - ^ * " 被当成 FTS 语法
                q = '"%s"' % kw.replace('"', '""')
                rows = self.conn.execute(
                    'SELECT m.book_id, b.title, b.author, m.chapter, m.text, m.people '
                    'FROM marks_fts m JOIN books b ON b.book_id = m.book_id '
                    'WHERE marks_fts MATCH ? ORDER BY m.people DESC LIMIT ?',
                    (q, int(limit))).fetchall()
                out = [dict(r) for r in rows]
            except Exception as e:
                self.last_error = str(e)
                out = []

        if not out:
            out = self._search_like(kw, limit)

        if min_people and int(min_people) > 1:
            out = [r for r in out if int(r.get('people') or 0) >= int(min_people)]
        return out

    def _search_like(self, kw, limit):
        try:
            sql = ('SELECT m.book_id, b.title, b.author, m.chapter, m.text, m.people '
                   'FROM marks m JOIN books b ON b.book_id = m.book_id '
                   'WHERE ' + self._LATEST_SNAP + ' AND m.text LIKE ? '
                   'ORDER BY m.people DESC LIMIT ?')
            return [dict(r) for r in self.conn.execute(sql, ('%' + kw + '%', int(limit)))]
        except Exception as e:
            self.last_error = str(e)
            return []

    def all_latest_marks(self, limit=20000, min_people=2):
        """取**所有**书最新快照里的划线（跨书去重合并的输入）。"""
        try:
            sql = ('SELECT m.book_id, b.title, b.author, m.chapter, m.text, m.people '
                   'FROM marks m JOIN books b ON b.book_id = m.book_id '
                   'WHERE ' + self._LATEST_SNAP + ' AND m.people >= ? '
                   'ORDER BY m.people DESC LIMIT ?')
            return [dict(r) for r in self.conn.execute(
                sql, (max(1, int(min_people or 1)), int(limit)))]
        except Exception as e:
            self.last_error = str(e)
            return []

    def marks_for_books(self, book_ids, per_book=60, min_people=0):
        """取多本书各自最新的高热划线（方向 3 主题聚合用）。

        返回 {book_id: {'title','author','items':[{text,chapter,people,mark_key}]}}
        """
        out = {}
        c = self.conn
        for bid in (book_ids or []):
            try:
                b = c.execute('SELECT * FROM books WHERE book_id=?', (bid,)).fetchone()
                if not b:
                    continue
                s = c.execute('SELECT snap_id FROM snapshots WHERE book_id=? '
                              'ORDER BY taken_at DESC, snap_id DESC LIMIT 1',
                              (bid,)).fetchone()
                if not s:
                    continue
                rows = c.execute(
                    'SELECT mark_key, chapter, text, people FROM marks '
                    'WHERE snap_id=? AND people >= ? ORDER BY people DESC LIMIT ?',
                    (s['snap_id'], max(2, int(min_people or 0)), int(per_book))).fetchall()
                out[bid] = {
                    'title': b['title'], 'author': b['author'] or '',
                    'items': [{'mark_key': r['mark_key'], 'chapter': r['chapter'],
                               'text': r['text'], 'people': r['people']} for r in rows],
                }
            except Exception as e:
                self.last_error = str(e)
        return out

    # ------------------------------------------------- 趋势序列（方向 5）
    def snap_series(self, book_id, top=8):
        """给趋势图准备数据。

        返回：
          {'labels': ['10-01 14:05', ...],          # 每个快照的时间
           'totals': [972, 975, ...],               # 每个快照的划线条数
           'lines': [{'key','text','chapter','points':[int|None, ...]}, ...]}
        其中 points 为 None 表示那一次快照里这条划线还不存在。
        """
        try:
            c = self.conn
            snaps = [dict(r) for r in c.execute(
                'SELECT snap_id, taken_at, total, n_items FROM snapshots '
                'WHERE book_id=? ORDER BY taken_at ASC, snap_id ASC', (book_id,))]
            if not snaps:
                return {'labels': [], 'totals': [], 'lines': []}

            labels, totals = [], []
            per_snap = {}
            for s in snaps:
                labels.append(_short_time(s['taken_at']))
                totals.append(int(s['n_items'] or 0))
                d = {}
                for r in c.execute(
                        'SELECT mark_key, chapter, text, people FROM marks WHERE snap_id=?',
                        (s['snap_id'],)):
                    d[r['mark_key']] = r
                per_snap[s['snap_id']] = d

            # 以最新快照里最热的 N 条作为「关注线」，回溯它们在每一份快照里的人数
            last = snaps[-1]['snap_id']
            hot = sorted(per_snap[last].values(),
                         key=lambda r: -(r['people'] or 0))[:int(top)]

            lines = []
            for h in hot:
                pts = []
                for s in snaps:
                    row = per_snap[s['snap_id']].get(h['mark_key'])
                    pts.append(int(row['people']) if row else None)
                lines.append({'key': h['mark_key'], 'text': h['text'],
                              'chapter': h['chapter'] or '', 'points': pts})
            return {'labels': labels, 'totals': totals, 'lines': lines,
                    'n_snaps': len(snaps)}
        except Exception as e:
            self.last_error = str(e)
            return {'labels': [], 'totals': [], 'lines': [], 'n_snaps': 0}

    # ------------------------------------------------- AI 结果存档（方向 2/3）
    def save_ai(self, kind, content, title='', prompt='', provider='', model='',
                book_ids=None):
        try:
            cur = self.conn.execute(
                'INSERT INTO ai_log(at,kind,prompt,provider,model,title,book_ids,content) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 kind or '', prompt or '', provider or '', model or '', title or '',
                 ','.join(book_ids or []), content or ''))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.last_error = str(e)
            return None

    def ai_history(self, limit=200):
        try:
            return [dict(r) for r in self.conn.execute(
                'SELECT id, at, kind, provider, model, title, book_ids, '
                'LENGTH(content) AS size FROM ai_log ORDER BY id DESC LIMIT ?',
                (int(limit),))]
        except Exception:
            return []

    def ai_get(self, ai_id):
        try:
            r = self.conn.execute('SELECT * FROM ai_log WHERE id=?', (int(ai_id),)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None

    def ai_delete(self, ai_id):
        try:
            self.conn.execute('DELETE FROM ai_log WHERE id=?', (int(ai_id),))
            self.conn.commit()
            return True
        except Exception:
            return False


def _short_time(t):
    """'2026-10-02 15:40' → '10-02 15:40'；短时间原样返回。"""
    t = (t or '').strip()
    if len(t) >= 16:
        return t[5:16]
    return t


# 全局单例，供 GUI 直接用
_store = None


def get_store():
    global _store
    if _store is None:
        _store = Store()
    return _store
