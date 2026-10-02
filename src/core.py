# -*- coding: utf-8 -*-
"""
微信读书 · 热门划线 —— 核心逻辑层（与界面完全解耦）
================================================================================
设计原则
  · 只依赖 Python 标准库 → 任何环境都能 import，桌面版 / 命令行版共用同一套
  · 唯一真相源：抓取、格式化、导出全部收敛在这里；界面层只负责调度与展示
  · 不 print、不 input、不弹窗：进度一律通过回调上报，任何前端都能接管

公开 API
  search_books(kw)                → 候选书列表 [{bookId,title,author,cover}]
  fetch_hotmarks(book_id)         → (items, chapters, total)
  fetch_by_book(book, top)        → BookResult          指定书抓取
  fetch_book(kw, top)             → BookResult          搜索 + 抓第一本
  batch_fetch(kws, ...)           → (ok_list, fail_list) 批量，带防风控间隔
  render(result, fmt)             → str                 html / md / txt / csv / json
  export(result, out_dir, fmt)    → 落盘路径（文件名含时间戳，永不覆盖）

【风控说明 · 重要】
  本模块只发 GET、只读公开数据，且【不携带任何 Cookie】——urllib 默认的
  OpenerDirector 不含 HTTPCookieProcessor，服务端拿不到身份标识，技术层面
  无法归因到账号。但批量时仍请保留间隔（默认 2~4 秒随机），不要并发猛刷。
================================================================================
"""
import os
import sys
import csv
import io
import json
import html
import time
import random
import datetime
import urllib.parse
import urllib.request

from template import HTML_TEMPLATE, SHARE_TEMPLATE
import exporters as E


def app_dir():
    """返回「数据与导出文件应该放在哪」。

    三种情况分别处理：
      · 打包成 exe —— 用 exe 自身所在目录。__file__ 在 PyInstaller 里指向临时
        解包目录（_MEIxxxx），跟着它走的话用户一关程序文件就没了。
      · 源码放在 src/ 子目录 —— 仍然用**项目根**。这样目录重整之后，
        已有的 data/（书库）与 exports/（导出结果）不会忽然"消失"。
      · 其它 —— 就用脚本所在目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here).lower() == 'src':
        return os.path.dirname(here)
    return here

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

API_SEARCH = 'https://weread.qq.com/web/search/global?keyword={kw}&maxIdx=0&fragmentSize=200'
API_HOT = 'https://weread.qq.com/web/book/bestbookmarks?bookId={bk}&count={n}'

# 支持导出的格式 → 文件扩展名
FORMATS = {'html': '.html', 'md': '.md', 'txt': '.txt', 'csv': '.csv', 'json': '.json',
           'share': '.html', 'docx': '.docx', 'epub': '.epub', 'pdf': '.pdf'}
FORMAT_LABELS = {
    'html': '网页（带复制按钮，可直接看）',
    'md': 'Markdown（喂给 DeepSeek 整理）',
    'txt': '纯文本（万能兜底）',
    'csv': '表格 CSV（Excel 可用）',
    'json': 'JSON（给程序用）',
    'share': '分享版网页（移动端自适应，发给朋友）',
    'docx': 'Word 文档（可继续编辑）',
    'epub': '电子书 EPUB（导入阅读器）',
    'pdf': 'PDF（打印 / 归档）',
}

# 需要以二进制写盘的格式（其余都是纯文本）
BINARY_FORMATS = {'docx', 'epub', 'pdf'}

DEFAULT_TOP = 100          # 默认导出条数
DEFAULT_INTERVAL = (2.0, 4.0)   # 批量抓取间隔（秒），防风控


class WereadError(Exception):
    """业务异常：搜索无结果、无划线数据、网络失败等。"""


# --------------------------------------------------------------------------
# 网络层
# --------------------------------------------------------------------------
# 网络配置。core 不 import settings（命令行版也要能用），
# 所以由界面层在启动时通过 set_net() 灌进来。
#
# proxy_mode 三种取值（这是「越用越慢」那个坑的根治点）：
#   'direct' —— 直连，**显式忽略**系统/环境代理。默认值。
#   'system' —— 跟随环境变量 / Windows 系统代理设置。
#   'custom' —— 用 proxy 里填的地址。
#
# 为什么默认 direct：微信读书是国内站点，直连本来就只有 0.2~0.4 秒。
# 而 Windows 上系统代理的注册表值（ProxyServer）在 Clash 关掉后**不会清空**，
# 只把 ProxyEnable 置 0；可只要代理程序还留着环境变量、或者代理在跑但规则把
# 国内域名也绕到境外节点，请求就会先撞死端口、再退避重试四次 —— 单次最坏等
# 十几秒。实测：吃死代理 2.05s 直接失败 vs 直连 0.32s 成功。
# --------------------------------------------------------------------------
NET = {'timeout': 25, 'retries': 3, 'proxy': '', 'proxy_mode': 'direct'}

PROXY_MODES = ('direct', 'system', 'custom')


def set_net(timeout=None, retries=None, proxy=None, proxy_mode=None):
    """由界面层调用，把设置里的网络选项同步下来。"""
    try:
        if timeout is not None:
            NET['timeout'] = max(3, min(180, int(timeout)))
        if retries is not None:
            NET['retries'] = max(0, min(8, int(retries)))
        if proxy is not None:
            NET['proxy'] = str(proxy or '').strip()
        if proxy_mode is not None:
            m = str(proxy_mode or '').strip().lower()
            NET['proxy_mode'] = m if m in PROXY_MODES else 'direct'
        # 填了地址就说明用户想用自定义代理，自动切过去，省得再点一次
        if proxy is not None and str(proxy).strip() and proxy_mode is None:
            NET['proxy_mode'] = 'custom'
        _reset_opener()
    except Exception:
        pass


_OPENER = None
_OPENER_PROXY = None


def _reset_opener():
    global _OPENER, _OPENER_PROXY
    _OPENER = None
    _OPENER_PROXY = None


def build_opener_for(proxy_mode, proxy=''):
    """按指定模式造一个 opener。

    单独抽出来是为了让「网络自检」能在不改全局状态的前提下逐个试。
    """
    mode = (proxy_mode or 'direct').strip().lower()
    p = (proxy or '').strip()
    if mode == 'custom' and p:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': p, 'https': p}))
    if mode == 'system':
        # 不带参数 = 用 urllib 默认链，会读环境变量与系统设置
        return urllib.request.build_opener()
    # direct：空 ProxyHandler = 明确禁用所有代理，环境变量也不起作用
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _opener():
    global _OPENER, _OPENER_PROXY
    mode = NET.get('proxy_mode') or 'direct'
    p = (NET.get('proxy') or '').strip()
    if _OPENER is None or _OPENER_PROXY != (mode, p):
        _OPENER = build_opener_for(mode, p)
        _OPENER_PROXY = (mode, p)
    return _OPENER


def open_request(req, timeout=None):
    """**所有对外请求的统一出口**。

    其他模块（ai.py 调大模型、feishu.py 推飞书）都走这里，
    这样「设置 → 网络 → 连接方式」一处生效、全局一致 ——
    不会再出现「抓取走了代理、封面/AI 各自走另一套」这种分裂。
    """
    return _opener().open(req, timeout=int(timeout or NET['timeout']))


def system_proxy_hint():
    """当前系统/环境里到底有没有代理，给界面显示用（不联网）。"""
    try:
        px = urllib.request.getproxies() or {}
    except Exception:
        return {'has': False, 'http': '', 'https': ''}
    h = (px.get('https') or px.get('http') or '').strip()
    return {'has': bool(h), 'http': px.get('http') or '', 'https': px.get('https') or ''}


def net_selftest(timeout=8):
    """逐个试「直连 / 系统代理 / 自定义」，量出真实耗时。

    返回 [{'mode':..., 'ok':bool, 'ms':int, 'note':str}, ...]
    用途：用户的代理时开时关、端口还可能换，靠这个一键看出哪种最快。
    """
    url = API_SEARCH.format(kw=urllib.parse.quote('活着'))
    out = []
    plans = [('direct', ''), ('system', '')]
    if (NET.get('proxy') or '').strip():
        plans.append(('custom', NET['proxy'].strip()))
    for mode, p in plans:
        t0 = time.time()
        note = ''
        ok = False
        try:
            op = build_opener_for(mode, p)
            req = urllib.request.Request(url, headers=_headers())
            with op.open(req, timeout=max(3, int(timeout))) as r:
                body = r.read()
            ok = bool(body)
            note = '%d 字节' % len(body)
        except Exception as e:
            note = str(e)[:58]
        out.append({'mode': mode, 'ok': ok,
                    'ms': int((time.time() - t0) * 1000), 'note': note})
    return out


def _headers():
    # 刻意不带 Cookie：服务端拿不到身份标识，技术层面无法归因到账号
    return {
        'User-Agent': UA,
        'Referer': 'https://weread.qq.com/',
        'Accept': 'application/json, text/plain, */*',
    }


def fetch_json(url, timeout=None, retries=None):
    """发一个不带 Cookie 的只读 GET，返回解析后的 JSON。

    失败会**指数退避重试**（0.8s / 1.6s / 3.2s…，带随机抖动）：
    公众号接口偶尔抽风是常态，一次失败就中断整批太脆。
    4xx（除 429）属于「请求本身有问题」，重试没意义，直接抛出。
    """
    timeout = int(timeout or NET['timeout'])
    tries = int(NET['retries'] if retries is None else retries)
    last = None

    for attempt in range(max(1, tries + 1)):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with _opener().open(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last = 'HTTP %s' % e.code
            else:
                raise WereadError('服务端返回 HTTP %s（这个请求本身有问题，重试无用）' % e.code)
        except urllib.error.URLError as e:
            last = str(getattr(e, 'reason', e))
        except json.JSONDecodeError:
            raise WereadError('返回内容不是合法 JSON（可能被网络中间层拦截了）')
        except Exception as e:
            last = str(e)

        if attempt < tries:
            time.sleep(min(8.0, (2 ** attempt) * 0.8 + random.random() * 0.4))

    raise WereadError('连续 %d 次请求都失败了：%s' % (tries + 1, last))


def post_json(url, payload, cookie='', timeout=None, retries=None):
    """发一个 POST（JSON body）。

    刻意与 fetch_json 分开：只有 AI 大纲这类**需要登录态**的接口才传 cookie；
    抓热门划线等公开接口一律不带 —— 保住「服务端无法归因到账号」这条底线。
    """
    timeout = int(timeout or NET['timeout'])
    tries = int(NET['retries'] if retries is None else retries)
    body = json.dumps(payload).encode('utf-8')
    h = dict(_headers())
    h['Content-Type'] = 'application/json'
    h['Origin'] = 'https://weread.qq.com'
    if cookie:
        h['Cookie'] = normalize_cookie(cookie) or cookie
    last = None

    for attempt in range(max(1, tries + 1)):
        try:
            req = urllib.request.Request(url, data=body, headers=h, method='POST')
            with _opener().open(req, timeout=timeout) as r:
                raw = r.read().decode('utf-8')
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise WereadError(
                    'HTTP 403 —— 微信读书拒绝了这个请求。\n'
                    'AI 大纲需要登录态：请到「设置 → 微信读书登录」填入 Cookie 后重试。')
            if e.code == 429 or e.code >= 500:
                last = 'HTTP %s' % e.code
            else:
                raise WereadError('服务端返回 HTTP %s（这个请求本身有问题）' % e.code)
        except urllib.error.URLError as e:
            last = str(getattr(e, 'reason', e))
        except json.JSONDecodeError:
            raise WereadError('返回内容不是合法 JSON（可能被网络中间层拦截了）')
        except Exception as e:
            last = str(e)

        if attempt < tries:
            time.sleep(min(8.0, (2 ** attempt) * 0.8 + random.random() * 0.4))

    raise WereadError('连续 %d 次请求都失败了：%s' % (tries + 1, last))


# --------------------------------------------------------------------------
# AI 大纲（书里每章的总结性要点，需要登录态）
# --------------------------------------------------------------------------
API_OUTLINE_CHECK = 'https://weread.qq.com/web/book/outline/check'
API_OUTLINE_INNER = 'https://weread.qq.com/web/book/outline/inner'


def fetch_outline_chapters(book_id, cookie='', timeout=None):
    """章节结构 + 每章有没有 AI 要点。

    实测（2026-10-02）：`POST /web/book/outline/check` **不带 Cookie 也返回 200**，
    内容是 chapterInfos 数组，每项形如：
        {"text": "第1章 …", "chapterUid": 4, "level": 1,
         "hasKeyPoint": 1, "version": 30012}
    `hasKeyPoint == 1` 表示这一章有 AI 大纲（-1 表示没有）。

    另外实测：**不是每本书都有 AI 大纲** ——《活着》13 章无一章有要点，
    《短线交易秘诀》则有多章。所以「有没有」这件事本身也得靠这个接口问。
    """
    data = post_json(API_OUTLINE_CHECK, {'bookId': str(book_id)},
                     cookie=cookie, timeout=timeout)
    return data.get('chapterInfos') or []


def fetch_outline_content(book_id, chapter_uids, cookie='', timeout=None):
    """取指定章节的 AI 大纲正文（这是需要登录的那一步）。

    实测要点：
      · 必须 **POST**（GET 一律 404）
      · 参数必须是 `{"bookId": "...", "chapterUids": [4]}` —— chapterUids 是**数组**
      · 不带登录态会返回 HTTP 403
    """
    uids = [int(u) for u in (chapter_uids or [])]
    if not uids:
        return {}
    if not cookie:
        raise WereadError('取 AI 大纲需要登录态：请到「设置 → 微信读书登录」填入 Cookie')
    return post_json(API_OUTLINE_INNER,
                     {'bookId': str(book_id), 'chapterUids': uids},
                     cookie=cookie, timeout=timeout)


_OUTLINE_TEXT_KEYS = ('keyPoint', 'keyPoints', 'items', 'itemArray',
                      'content', 'text', 'outline', 'points', 'summary')


def outline_parse(data):
    """把 outline/inner 的返回宽松解析成 {chapterUid: [文本, …]}。

    官方没有公开返回结构，所以这里不写死字段名 —— 递归找出所有
    「挂在某个 chapterUid 下、看起来像正文的字符串」。
    认不出来时返回空 dict（界面会显示「该章暂无内容」），不会抛异常。
    """
    out = {}

    def add(uid, s):
        if isinstance(s, str) and s.strip():
            out.setdefault(uid, []).append(s.strip())

    def walk(node, cur_uid=None):
        if isinstance(node, dict):
            uid = node.get('chapterUid')
            if uid is None:
                uid = node.get('chapter_uid')
            if uid is None:
                uid = cur_uid
            for k in _OUTLINE_TEXT_KEYS:
                v = node.get(k)
                if isinstance(v, str):
                    add(uid, v)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            add(uid, x)
                        else:
                            walk(x, uid)
            for k, v in node.items():
                if k in _OUTLINE_TEXT_KEYS:
                    continue
                walk(v, uid)
        elif isinstance(node, list):
            for x in node:
                walk(x, cur_uid)

    walk(data)
    return {k: v for k, v in out.items() if v}


def search_books(keyword, timeout=None):
    """按书名搜索，返回候选列表。

    除书名/作者/封面外，还会带上**可读性指标** —— 这些字段搜索接口本来就返回，
    属于「顺手拿来」，不增加任何额外请求：

        rating         推荐值（0–1000，除以 10 得百分比）
        rating_count   评价人数
        rating_label   评价等级标签，如「神作」「好评如潮」
        reading_count  在读人数
        publisher      出版社
        intro          简介
        finished       是否完结
    """
    url = API_SEARCH.format(kw=urllib.parse.quote(keyword))
    data = fetch_json(url, timeout=timeout)
    out = []
    for b in (data.get('books') or []):
        info = b.get('bookInfo') or {}
        if not info.get('bookId'):
            continue
        detail = info.get('newRatingDetail') or {}
        out.append({
            'bookId': info.get('bookId'),
            'title': info.get('title') or '(无题)',
            'author': info.get('author') or '',
            'cover': info.get('cover') or '',
            'rating': info.get('newRating'),
            'rating_count': info.get('newRatingCount'),
            'rating_label': (detail.get('title') if isinstance(detail, dict) else '') or '',
            'reading_count': b.get('readingCount'),
            'publisher': info.get('publisher') or '',
            'intro': info.get('intro') or '',
            'finished': info.get('finished'),
            'price': info.get('price'),
            # 官方书籍页链接，形如 https://weread.qq.com/book-detail?type=1&v=<infoId>
            # 坑：URL 里的 v 是 infoId，和 bookId 不是一回事 —— 用 bookId 拼
            # bookDetail/<bookId> 实测返回 404，所以只能原样保存这个字段。
            'deepLink': info.get('deepLink') or '',
            # 从 deepLink 里抠出 infoId，供阅读器地址使用（见 book_reader_url）。
            'infoId': _info_id_from_link(info.get('deepLink') or ''),
        })
    return out


# 微信读书登录态里真正起作用的几个字段（其余字段带不带都行）
COOKIE_KEY_NAMES = ('wr_vid', 'wr_skey', 'wr_rt', 'wr_localvid',
                    'wr_gid', 'wr_fp', 'wr_uid', 'wr_name')


def cookie_keys(cookie):
    """从粘贴进来的内容里认出含哪些关键字段。

    用户可能从 DevTools 复制成好几种样子，这里都认：
      · 标准串      wr_vid=123; wr_skey=abc;
      · 一行一个    每行「名字=值」
      · JSON        {"wr_vid": "123", "wr_skey": "abc"}（某些插件导出成这个）
      · 带路径域    名字=值; Path=/; Domain=.weread.qq.com
    """
    s = cookie or ''
    if not s.strip():
        return []
    names = set()
    # JSON 形态
    st = s.strip()
    if st.startswith('{') or st.startswith('['):
        try:
            import json as _json
            obj = _json.loads(st)
            if isinstance(obj, dict):
                names |= {str(k).strip() for k in obj.keys()}
            elif isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict) and it.get('name'):
                        names.add(str(it['name']).strip())
        except Exception:
            pass
    # 常规「名=值」形态（; 或换行分隔）
    for chunk in s.replace('\r', '\n').replace('\n', ';').split(';'):
        chunk = chunk.strip()
        if not chunk or '=' not in chunk:
            continue
        nm = chunk.split('=', 1)[0].strip()
        if nm:
            names.add(nm)
    return [k for k in COOKIE_KEY_NAMES if k in names]


def normalize_cookie(cookie):
    """把用户粘的内容整理成标准 Cookie 头（顺带丢掉 Path/Domain 等属性）。

    这样即使他从 DevTools 整行复制（含 Path=/; Domain=.weread.qq.com），
    也能正常当 Cookie 发出去。
    """
    s = (cookie or '').strip()
    if not s:
        return ''
    # JSON 形态（某些浏览器插件导出成这样），先转成「名=值」串
    if s.startswith('{') or s.startswith('['):
        try:
            import json as _json
            obj = _json.loads(s)
            items = []
            if isinstance(obj, dict):
                items = list(obj.items())
            elif isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict) and it.get('name') is not None:
                        items.append((it.get('name'), it.get('value', '')))
            if items:
                s = '; '.join('%s=%s' % (k, v) for k, v in items)
        except Exception:
            pass
    pairs = []
    for chunk in s.replace('\r', '\n').replace('\n', ';').split(';'):
        chunk = chunk.strip()
        if not chunk or '=' not in chunk:
            continue
        nm, val = chunk.split('=', 1)
        nm, val = nm.strip(), val.strip()
        # 跳过 Cookie 属性，它们不该出现在请求头里
        if nm.lower() in ('path', 'domain', 'expires', 'max-age',
                          'samesite', 'secure', 'httponly', 'priority'):
            continue
        if nm:
            pairs.append('%s=%s' % (nm, val))
    return '; '.join(pairs)


def _info_id_from_link(link):
    """从 book-detail / reader 链接里取出 infoId（形如 5ff32970721696fb5ffc757）。

    微信读书有两套 ID：
      · bookId  —— 纯数字（35034875），接口用
      · infoId  —— 24 位十六进制（5ff32970721696fb5ffc757），URL 用
    两者不能互推，只能用接口直给的 deepLink。
    """
    s = (link or '').strip()
    if not s:
        return ''
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
        v = (q.get('v') or [''])[0].strip()
        if v:
            return v
        # 已是 /web/reader/<infoId> 形态，取最后一段
        path = urllib.parse.urlparse(s).path.rstrip('/')
        seg = path.rsplit('/', 1)[-1]
        if seg and seg != 'reader':
            return seg.split('k')[0]
    except Exception:
        pass
    return ''


def book_reader_url(book):
    """这本书**可以直接开始阅读**的地址（「在微信读书打开」按钮用这个）。

    实测（2026-10-03，三本书交叉验证）：
      · /book-detail?type=1&v=<infoId>  → 126KB，<title> 就是「微信读书」→ **详情页**
      · /web/reader/<infoId>            → 201KB，<title> 是「书名 - 作者 - 微信读书」，
                                          页面含 renderTarget → **阅读器**（可点可读）
    所以要直达阅读界面，必须拼 /web/reader/，不能用接口给的 deepLink 原样打开。
    """
    b = book or {}
    inf = (b.get('infoId') or '').strip() or _info_id_from_link(b.get('deepLink') or '')
    if inf:
        return 'https://weread.qq.com/web/reader/' + inf
    # 兜底：详情页（至少能进书）
    return book_url(b)


def book_url(book):
    """这本书的**详情页**地址（书架信息、简介、评分那一页）。

    优先 deepLink（接口直给）；万一没有，退回按书名搜索页 ——
    一定打得开，总比 404 强。
    """
    b = book or {}
    dl = (b.get('deepLink') or '').strip()
    if dl.startswith('http'):
        return dl
    title = (b.get('title') or '').strip()
    if title:
        return ('https://weread.qq.com/web/search/books?keyword='
                + urllib.parse.quote(title))
    return ''


def rating_percent(book):
    """把推荐值换算成百分比字符串（如 '92.0%'）；拿不到时返回空串。"""
    try:
        r = int(book.get('rating') or 0)
        if r <= 0:
            return ''
        return '%.1f%%' % (r / 10.0)
    except Exception:
        return ''


def fetch_hotmarks(book_id, count=100000, timeout=None):
    """拉取全书热门划线，返回 (items, chapters, total)。

    注意：count 必须显式传大值，不传只会返回 10 条。
    """
    url = API_HOT.format(bk=book_id, n=count)
    data = fetch_json(url, timeout=timeout)
    bb = data.get('bestBookMarks') or {}
    items = bb.get('items') or []
    chapters = {}
    for c in (bb.get('chapters') or []):
        chapters[c.get('chapterUid')] = c.get('title') or ''
    return items, chapters, bb.get('totalCount') or len(items)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')


def stamp():
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def num_fmt(n):
    n = int(n or 0)
    return ('%.1f 万' % (n / 10000.0)) if n >= 10000 else str(n)


def safe_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip() or 'book'


def json_for_script(obj):
    """安全嵌入 <script>：转义 </ 防止正文里出现 </script> 提前闭合标签。"""
    return json.dumps(obj, ensure_ascii=False,
                      separators=(',', ':')).replace('</', '<\\/')


# --------------------------------------------------------------------------
# 抓取（高层）
# --------------------------------------------------------------------------
def fetch_by_book(book, top=DEFAULT_TOP, timeout=None):
    """对一本已知的书抓取热门划线，返回 BookResult。"""
    items, chapters, total = fetch_hotmarks(book['bookId'], timeout=timeout)
    if not items:
        raise WereadError('《%s》暂无热门划线数据' % book['title'])
    n = len(items) if not top else max(1, min(int(top), len(items)))
    return {
        'book': book,
        'keyword': book.get('title', ''),
        'items': items[:n],
        'all_count': len(items),     # 接口实际返回的全部条数
        'total': total,              # 官方标注的总数
        'chapters': chapters,
        'fetched_at': now_str(),
    }


def fetch_book(keyword, top=DEFAULT_TOP, timeout=None):
    """按书名搜索并抓取第一本。"""
    books = search_books(keyword, timeout=timeout)
    if not books:
        raise WereadError('没搜到「%s」，换个关键词试试' % keyword)
    r = fetch_by_book(books[0], top=top, timeout=timeout)
    r['keyword'] = keyword
    r['candidates'] = books
    return r


def batch_fetch(keywords, top=DEFAULT_TOP, interval=DEFAULT_INTERVAL,
                on_log=None, on_item=None, on_start=None,
                should_stop=None, timeout=None):
    """顺序批量抓取，带随机间隔与失败隔离。

    参数
      keywords    : 书名列表（重复项会被自动去重，保持原顺序）
      interval    : (最小, 最大) 秒，两本之间随机休眠，避免高频触发风控
      on_log(msg) : 日志回调
      on_item(r)  : 每成功一本回调一次
      on_start(i, total, kw) : 开始抓某一本时回调
      should_stop(): 返回 True 则尽快中止（休眠期间也能响应）

    返回 (ok_list, fail_list, stopped)
    """
    def log(m):
        if on_log:
            on_log(m)

    def stopped():
        return bool(should_stop and should_stop())

    # 去重但保持顺序
    seen, queue = set(), []
    for k in keywords:
        k = (k or '').strip()
        if k and k not in seen:
            seen.add(k)
            queue.append(k)

    ok, fail = [], []
    total = len(queue)
    if not total:
        log('队列为空，没有要抓取的书。')
        return ok, fail, False

    log('开始批量抓取，共 %d 本。' % total)
    for idx, kw in enumerate(queue, 1):
        if stopped():
            log('已被手动中止（已完成 %d/%d）。' % (idx - 1, total))
            return ok, fail, True

        if on_start:
            on_start(idx, total, kw)
        log('[%d/%d] 正在抓取「%s」…' % (idx, total, kw))
        try:
            r = fetch_book(kw, top=top, timeout=timeout)
            r['seq'] = idx
            r['keyword'] = kw
            ok.append(r)
            log('      ✓《%s》共 %d 条，已取 %d 条'
                % (r['book']['title'], r['all_count'], len(r['items'])))
            if on_item:
                on_item(r)
        except Exception as e:
            fail.append({'keyword': kw, 'error': str(e)})
            log('      ✗ 失败：%s' % e)

        # 最后一本不用等
        if idx < total and not stopped():
            d = random.uniform(*interval)
            log('      等待 %.1f 秒（防风控）…' % d)
            slept = 0.0
            while slept < d:
                if stopped():
                    log('已被手动中止（已完成 %d/%d）。' % (idx, total))
                    return ok, fail, True
                time.sleep(0.2)
                slept += 0.2

    log('批量结束：成功 %d 本，失败 %d 本。' % (len(ok), len(fail)))
    return ok, fail, False


# --------------------------------------------------------------------------
# 渲染：把 BookResult 变成各种文本格式
# --------------------------------------------------------------------------
def _rows_html(result, with_people=True):
    rows = []
    for i, it in enumerate(result['items'], 1):
        ch = result['chapters'].get(it.get('chapterUid'), '')
        hot = ('<span class="h">%s 人划线</span>' % num_fmt(it.get('totalCount'))
               ) if with_people else ''
        rows.append(
            '<article>'
            '<div class="m"><span class="n">#%d</span>%s%s</div>'
            '<p>%s</p></article>' % (
                i,
                ('<span class="c">%s</span>' % esc(ch)) if ch else '',
                hot,
                esc(it.get('markText'))
            )
        )
    return ''.join(rows)


def _payload(result, with_people=True):
    """界面与复制文本共用的数据源，保证「看到的」和「复制的」永远一致。

    with_people=False 时彻底不输出划线人数 —— 导出给别人看时，
    「多少人划过」是平台内部指标，不是内容本身。
    """
    book = result['book']
    items = []
    for i, it in enumerate(result['items'], 1):
        d = {
            'i': i,
            'ch': result['chapters'].get(it.get('chapterUid'), ''),
            'text': it.get('markText') or '',
        }
        if with_people:
            d['n'] = int(it.get('totalCount') or 0)
        items.append(d)
    return {
        'title': book['title'],
        'author': book['author'],
        'total': result['total'],
        'count': len(result['items']),
        'generated': result['fetched_at'],
        'filename': '《%s》热门划线.md' % safe_filename(book['title']),
        'with_people': bool(with_people),
        'items': items,
    }


def _idx_prefix(it, st):
    """条目前缀：序号 +（可选）章节标签。模板里两个开关分别控制。"""
    out = ''
    if st.get('show_index'):
        out += '%d. ' % it['i']
    if st.get('show_chapter') and it['ch']:
        out += '[%s] ' % it['ch']
    return out


def _people_tail(it, with_people):
    return ('（%d 人划线）' % it['n']) if (with_people and 'n' in it) else ''


def to_html(result, with_people=True, style=None):
    st = E.make_style(style)
    book = result['book']
    d = _payload(result, with_people)
    text = (HTML_TEMPLATE
            .replace('{{TITLE}}', esc(book['title']))
            .replace('{{AUTHOR}}', esc(book['author']))
            .replace('{{N}}', str(d['count']))
            .replace('{{TOTAL}}', str(d['total']))
            .replace('{{ROWS}}', _rows_html(result, with_people))
            .replace('{{GEN}}', esc(result['fetched_at']))
            .replace('{{DATA}}', json_for_script(d)))
    # 模板不带样式占位符，直接在 </style> 前追加一层覆盖，优先级更高
    css = ('body{font-size:%dpx;} header{background:linear-gradient(135deg,%s,%s);}'
           % (st['font_size'], st['accent'], st['accent']))
    return text.replace('</style>', css + '</style>')


def to_markdown(result, with_people=True, style=None):
    """与 HTML 页面里「复制 Markdown」输出完全同构。"""
    st = E.make_style(style)
    d = _payload(result, with_people)
    L = ['# 《%s》· 热门划线' % d['title'], '']
    if d['author']:
        L.append('- 作者：%s' % d['author'])
    L.append('- 共 %s 条，本页 %d 条' % (d['total'], d['count'])
             + ('（按划线人数从多到少）' if with_people else ''))
    L.append('- 生成：%s' % d['generated'])
    L += ['', '---', '']
    for it in d['items']:
        L.append('%s%s%s' % (_idx_prefix(it, st), it['text'], _people_tail(it, with_people)))
    return '\n'.join(L)


def to_plain(result, with_people=True, style=None):
    st = E.make_style(style)
    d = _payload(result, with_people)
    L = ['《%s》 热门划线%s' % (d['title'], '（%s）' % d['author'] if d['author'] else ''), '']
    for it in d['items']:
        L.append('%s%s%s' % (_idx_prefix(it, st), it['text'], _people_tail(it, with_people)))
    L += ['', '共 %d 条 · 生成于 %s' % (d['count'], d['generated'])]
    return '\n'.join(L)


def to_csv(result, with_people=True, style=None):
    st = E.make_style(style)
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ['序号'] if st.get('show_index') else []
    if st.get('show_chapter'):
        head.append('章节')
    head.append('划线内容')
    if with_people:
        head.append('划线人数')
    w.writerow(head)
    for it in _payload(result, with_people)['items']:
        row = [it['i']] if st.get('show_index') else []
        if st.get('show_chapter'):
            row.append(it['ch'])
        row.append(it['text'])
        if with_people:
            row.append(it['n'])
        w.writerow(row)
    return buf.getvalue()


def to_json(result, with_people=True, style=None):
    d = _payload(result, with_people)
    d['book_id'] = result['book'].get('bookId', '')
    d['all_count'] = result.get('all_count', d['count'])
    d['source'] = API_HOT.split('?')[0]
    return json.dumps(d, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 新格式
def to_docx(result, with_people=True, style=None):
    return E.build_docx(result, with_people, style)


def to_epub(result, with_people=True, style=None):
    return E.build_epub(result, with_people, style)


def to_print_html(result, with_people=True, style=None):
    """打印版 HTML —— PDF 渲染器（界面层）会消费它。"""
    return E.build_print_html(result, with_people, style)


def to_share(result, with_people=True, style=None):
    """分享版网页（方向 7）。

    与「工具版」的区别：纯阅读、移动端优先、按章节分组、
    带 OG 标签（在微信/飞书里发出去会有预览），单文件零外链。
    """
    book = result['book']
    d = _payload(result, with_people)
    groups = group_by_chapter(result)
    idx_map = {id(it): i for i, it in enumerate(result.get('items') or [], 1)}

    parts = []
    for g in groups:
        rows = []
        for it in g['items']:
            hot = ('<span class="hot">%s 人划线</span>'
                   % num_fmt(it.get('totalCount'))) if with_people else ''
            rows.append(
                '<article><div class="meta"><span class="n">#%d</span>%s</div>'
                '<p>%s</p></article>'
                % (idx_map.get(id(it), 0), hot, esc(it.get('markText'))))
        parts.append(
            '<section><div class="sechead"><h2>%s</h2>'
            '<span class="cnt">%d 条</span></div>'
            '<div class="bar"><i style="width:%d%%"></i></div>%s</section>'
            % (esc(g['chapter']), g['count'], g['heat'], ''.join(rows)))
    sections = ''.join(parts) or '<p style="color:#8B8AAE">没有可分享的划线。</p>'

    first = (result.get('items') or [{}])[0].get('markText') or ''
    desc = first.replace('\n', ' ').replace('\r', ' ').strip()[:60] or '微信读书热门划线'

    stat = ('<div><b>%s</b><span>热门划线</span></div>'
            '<div><b>%d</b><span>覆盖章节</span></div>'
            % (num_fmt(d['count']), len(groups)))
    if with_people:
        people_list = [int(it.get('totalCount') or 0) for it in (result.get('items') or [])]
        stat += ('<div><b>%s</b><span>最高共鸣</span></div>'
                 % num_fmt(max(people_list or [0])))

    st = E.make_style(style)
    text = (SHARE_TEMPLATE
            .replace('{{TITLE}}', esc(book['title']))
            .replace('{{AUTHOR}}', esc(book['author'] or '—'))
            .replace('{{DESC}}', esc(desc))
            .replace('{{STAT}}', stat)
            .replace('{{SECTIONS}}', sections)
            .replace('{{GEN}}', esc(result['fetched_at'])))
    fs = st['font_size'] + 1
    css = 'body{font-size:%dpx}article p{font-size:%dpx}' % (fs, fs)
    return text.replace('</style>', css + '</style>')


_RENDERERS = {
    'html': to_html,
    'md': to_markdown,
    'txt': to_plain,
    'csv': to_csv,
    'json': to_json,
    'share': to_share,
    'docx': to_docx,
    'epub': to_epub,
}

# 运行期才能实现的渲染器（例如 PDF 要依赖 Qt）。
# 由界面层在启动时注册 —— 这样 core 依然保持「零第三方依赖」，
# 命令行版就算没注册也能正常跑其它格式。
_EXTRA = {}


def register_renderer(fmt, fn, ext=None, binary=None):
    """注册一个外部渲染器。返回是否注册成功。"""
    fmt = (fmt or '').lower().lstrip('.')
    if not fmt or not callable(fn):
        return False
    _EXTRA[fmt] = fn
    if ext:
        FORMATS[fmt] = ext
    if binary is not None:
        if binary:
            BINARY_FORMATS.add(fmt)
        else:
            BINARY_FORMATS.discard(fmt)
    return True


def has_renderer(fmt):
    fmt = (fmt or '').lower().lstrip('.')
    return fmt in _RENDERERS or fmt in _EXTRA


def available_formats():
    out = list(_RENDERERS.keys())
    out += [k for k in _EXTRA.keys() if k not in out]
    return out


def render(result, fmt='html', with_people=True, style=None):
    fmt = (fmt or 'html').lower().lstrip('.')
    fn = _RENDERERS.get(fmt) or _EXTRA.get(fmt)
    if not fn:
        raise WereadError('不支持的格式：%s' % fmt)
    return fn(result, with_people, style)


def apply_min_people(result, min_people=0):
    """按「划线人数下限」过滤，返回新的 result 副本（不改原对象）。

    默认导出规则：低于下限的划线不进导出文件 —— 热门划线里
    「1 人划线」的条目占了很大比例，属于噪声，默认过滤掉（≥2 人）。
    """
    try:
        n = int(min_people)
    except Exception:
        n = 0
    if n <= 1:
        return result
    r = dict(result)
    r['items'] = [it for it in (result.get('items') or [])
                  if int(it.get('totalCount') or 0) >= n]
    r['filtered_from'] = len(result.get('items') or [])
    return r


def group_by_chapter(result):
    """把热门划线按章节聚合。

    这既是**章节热度**（哪几章最戳人），也是「同章共鸣」——
    同一章节里的其他热门划线，正是读者在这个段落里共同关注的东西。

    返回 [{uid, chapter, items, count, top, avg, heat}]，按该章最热一条排序。
    heat 为 0–100 的相对热度，方便直接画条形。
    """
    ch = result.get('chapters') or {}
    buckets = {}
    for it in (result.get('items') or []):
        uid = it.get('chapterUid')
        buckets.setdefault(uid, []).append(it)

    groups = []
    for uid, items in buckets.items():
        items = sorted(items, key=lambda x: int(x.get('totalCount') or 0), reverse=True)
        people = [int(i.get('totalCount') or 0) for i in items]
        groups.append({
            'uid': uid,
            'chapter': ch.get(uid) or '—',
            'items': items,
            'count': len(items),
            'top': people[0] if people else 0,
            'avg': int(sum(people) / len(people)) if people else 0,
        })
    groups.sort(key=lambda g: g['top'], reverse=True)

    top_max = max([g['top'] for g in groups] or [1]) or 1
    for g in groups:
        g['heat'] = int(round(g['top'] * 100.0 / top_max))
    return groups


def export_text(text, out_dir, stem, ext='.md'):
    """把一段现成文本落盘（跨书合并结果、AI 笔记等用它导出）。"""
    os.makedirs(out_dir, exist_ok=True)
    name = '%s-%s%s' % (safe_filename(stem), stamp(), ext)
    path = os.path.join(out_dir, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text or '')
    return path


def export(result, out_dir, fmt='html', with_people=True, style=None):
    """写盘。文件名带时间戳 → 同一本书反复导出也不会互相覆盖。"""
    os.makedirs(out_dir, exist_ok=True)
    ext = FORMATS.get(fmt, '.txt')
    tag = '分享版' if fmt == 'share' else ''
    name = '《%s》热门划线%s-%s%s' % (safe_filename(result['book']['title']), tag, stamp(), ext)
    path = os.path.join(out_dir, name)

    data = render(result, fmt, with_people, style)
    if isinstance(data, bytes) or fmt in BINARY_FORMATS:
        if isinstance(data, str):
            data = data.encode('utf-8')
        with open(path, 'wb') as f:
            f.write(data)
    else:
        # CSV 用 utf-8-sig，Excel 打开中文才不乱码
        enc = 'utf-8-sig' if fmt == 'csv' else 'utf-8'
        with open(path, 'w', encoding=enc, newline='' if fmt == 'csv' else None) as f:
            f.write(data)
    return path
