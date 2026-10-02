# -*- coding: utf-8 -*-
"""
AI 能力层（大模型调用 / 提示词 / 整理）
================================================================================
只依赖标准库 urllib —— 打包体积零增加，且不需要任何 SDK。

所有提供商都走 **OpenAI 兼容协议**（/v1/chat/completions），
这样可以一套代码接通 DeepSeek / 硅基流动 / 智谱 / 阿里云百炼 / 本地 Ollama。

设计原则：
  · 不做任何联网校验，不校验 Key 是否有效 —— 失败时把服务端的原话返回给界面
  · 支持流式（SSE），让界面能实时逐字显示，而不是干等十几秒
  · 所有异常都收敛成 AiError，界面只需展示消息
"""
import json
import urllib.request
import urllib.error

# --------------------------------------------------------------------------
# 提供商注册表
# --------------------------------------------------------------------------
PROVIDERS = {
    'deepseek': {
        'label': 'DeepSeek',
        'base': 'https://api.deepseek.com/v1',
        'model': 'deepseek-chat',
        'models': ['deepseek-chat', 'deepseek-reasoner'],
        'key_url': 'https://platform.deepseek.com/api_keys',
        'need_key': True,
    },
    'siliconflow': {
        'label': '硅基流动',
        'base': 'https://api.siliconflow.cn/v1',
        'model': 'Qwen/Qwen3-8B',
        'models': ['Qwen/Qwen3-8B', 'Qwen/Qwen3-14B', 'Qwen/Qwen3-32B',
                   'deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1'],
        'key_url': 'https://cloud.siliconflow.cn/account/ak',
        'need_key': True,
    },
    'zhipu': {
        'label': '智谱 GLM',
        'base': 'https://open.bigmodel.cn/api/paas/v4',
        'model': 'glm-4-flash',
        'models': ['glm-4-flash', 'glm-4-plus', 'glm-4-air', 'glm-4-long'],
        'key_url': 'https://open.bigmodel.cn/usercenter/apikeys',
        'need_key': True,
    },
    'dashscope': {
        'label': '阿里云百炼',
        'base': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen-plus',
        'models': ['qwen-plus', 'qwen-turbo', 'qwen-max', 'qwen-long'],
        'key_url': 'https://bailian.console.aliyun.com/?apiKey=1',
        'need_key': True,
    },
    'ollama': {
        'label': '本地 Ollama',
        'base': 'http://127.0.0.1:11434/v1',
        'model': 'qwen3:8b',
        'models': ['qwen3:8b', 'qwen3.5:9b', 'deepseek-r1:7b'],
        'key_url': 'https://ollama.com/download',
        'need_key': False,          # 本地模型不需要 Key，随便填个占位符
    },
}

PROVIDER_ORDER = ['deepseek', 'siliconflow', 'zhipu', 'dashscope', 'ollama']

# --------------------------------------------------------------------------
# 内置提示词模板（设置页可改，也可以一键恢复）
# --------------------------------------------------------------------------
BUILTIN_PROMPTS = {
    'digest': {
        'name_zh': '精华提炼',
        'name_en': 'Distill',
        'desc_zh': '把一堆热门划线整理成结构化笔记：按主题归类、去掉重复、保留原句',
        'desc_en': 'Turn raw highlights into a structured note grouped by theme',
        'text': (
            '你是中文阅读笔记整理专家。下面是一本书的热门划线（括号里是划线人数，'
            '数字越大说明越多读者共鸣）。\n\n'
            '请把它整理成一份**结构化读书笔记**，要求：\n'
            '1. 按主题归类，每类起一个小标题（不要用「主题一」这种空话，要提炼出真正的内容点）\n'
            '2. 同一类里合并语义重复的句子，只保留最有力量的原句（保留原文，不要改写）\n'
            '3. 每类下面用「-」列出保留的原句，并在句末标注划线人数，格式：（N 人划线）\n'
            '4. 最后加一段「一句话总结」，不超过 80 字\n'
            '5. 用 Markdown 输出，不要任何开场白和结尾客套\n\n'
            '书名：《{title}》\n作者：{author}\n\n'
            '热门划线如下：\n{content}'
        ),
    },
    'theme': {
        'name_zh': '跨书主题对比',
        'name_en': 'Cross-book Themes',
        'desc_zh': '多本书放在一起，看它们对同一个问题各自怎么说',
        'desc_en': 'Compare what several books say about the same question',
        'text': (
            '你是阅读研究助手。下面有几本书的热门划线，每本书用标题分隔。\n\n'
            '请产出**跨书主题分析**，要求：\n'
            '1. 先归纳出这些书**共同关注的 3~5 个核心问题**\n'
            '2. 针对每个问题，列出各本书的立场／说法（注明来自哪本书，引用原句）\n'
            '3. 明确写出它们**互相印证**的地方和**互相矛盾**的地方\n'
            '4. 最后给一段「如果你要在这个问题上行动，优先看哪本、看哪一章」的建议\n'
            '5. 用 Markdown 输出，不要开场白\n\n{content}'
        ),
    },
    'action': {
        'name_zh': '行动清单',
        'name_en': 'Action List',
        'desc_zh': '从划线里提炼出可以直接做的事，而不是又一篇感想',
        'desc_en': 'Extract concrete actions instead of another summary',
        'text': (
            '你是目标管理教练。下面是热门划线。\n\n'
            '请把它们转化成一份**可执行的行动清单**：\n'
            '1. 用「如果……就……」的句式写 5~8 条具体行动（要能在一天内开始做）\n'
            '2. 每条行动后面用括号注明它来自哪句划线（简短引用）\n'
            '3. 标出哪 2 条是**最高杠杆**的，并说明理由（一句话）\n'
            '4. 用 Markdown 输出，不要开场白\n\n{content}'
        ),
    },
    'extract': {
        'name_zh': '关键词提取',
        'name_en': 'Keyword Extract',
        'desc_zh': '提取这本书的核心关键词与金句，适合做书签',
        'desc_en': 'Pull keywords and golden lines, good for bookmarks',
        'text': (
            '请从下面的热门划线里提取：\n'
            '1. 10 个核心关键词（每个词后用一句话解释它在这本书里的特定含义）\n'
            '2. 5 句最值得记住的金句（原文照抄，句末标划线人数）\n'
            '3. 用 Markdown 输出，不要开场白\n\n'
            '书名：《{title}》\n\n{content}'
        ),
    },
}

PROMPT_ORDER = ['digest', 'theme', 'action', 'extract']

# 用户自定义提示词里没写 {content} 时，自动追加这一段，保证金句正文一定发出去
_CONTENT_FALLBACK = '\n\n以下是需要处理的划线内容：\n\n{content}'


class AiError(Exception):
    """AI 调用失败。消息直接面向用户，可原样展示。"""


# --------------------------------------------------------------------------
# HTTP 底层
# --------------------------------------------------------------------------
def _endpoint(provider):
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise AiError('未知的 AI 提供商：%s' % provider)
    return cfg['base'].rstrip('/') + '/chat/completions'


def _headers(provider, key):
    h = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'BookPulse/2.0 (+https://weread.qq.com)',
    }
    cfg = PROVIDERS.get(provider) or {}
    if cfg.get('need_key'):
        if not key:
            raise AiError('还没有填写 %s 的 API Key，请到「设置 → AI 助手」里填。'
                          % cfg.get('label', provider))
        h['Authorization'] = 'Bearer %s' % key
    else:
        # 本地 Ollama 不校验，但有些网关要求非空
        h['Authorization'] = 'Bearer %s' % (key or 'ollama')
    return h


def _friendly_http_error(code, body):
    """把服务端返回翻译成人话。"""
    detail = ''
    try:
        j = json.loads(body or '{}')
        detail = ((j.get('error') or {}).get('message')
                  or j.get('message') or (j.get('error') if isinstance(j.get('error'), str) else '')
                  or '')
    except Exception:
        detail = (body or '')[:200]

    hint = {
        400: '请求被拒绝（多半是模型名不对或参数不合法）',
        401: 'API Key 无效或已过期',
        402: '账户余额不足',
        403: '没有权限访问该模型',
        404: '模型不存在或地址填错',
        429: '请求太频繁 / 超出配额，稍后再试',
        500: '服务端错误',
        502: '服务端网关错误',
        503: '服务暂时不可用',
    }.get(code, 'HTTP %s' % code)
    return AiError('%s：%s' % (hint, detail or '（服务端没有给出说明）'))


def _post(url, headers, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers, method='POST')
    # 走 core 的统一出口，遵守「设置 → 网络 → 连接方式」。
    # 以前这里用裸 urlopen：代理设置改了它不跟，代理一挂这里就超时/失败。
    try:
        import core as _core
        return _core.open_request(req, timeout=timeout)
    except ImportError:
        return urllib.request.urlopen(req, timeout=timeout)


# --------------------------------------------------------------------------
# 对外主接口
# --------------------------------------------------------------------------
def chat(messages, provider='deepseek', model=None, key='', timeout=180,
         temperature=0.5, max_tokens=4096, on_delta=None):
    """调一次对话补全。

    on_delta(text) 不为空时走**流式**：每收到一小段就回调一次，返回完整文本。
    否则一次性返回。返回值为模型输出的完整文本。
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise AiError('未知的 AI 提供商：%s' % provider)
    model = model or cfg['model']
    url = _endpoint(provider)
    headers = _headers(provider, key)

    payload = {
        'model': model,
        'messages': messages,
        'temperature': float(temperature),
        'max_tokens': int(max_tokens),
        'stream': bool(on_delta),
    }

    try:
        resp = _post(url, headers, payload, timeout)
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')
        except Exception:
            pass
        raise _friendly_http_error(e.code, body)
    except urllib.error.URLError as e:
        reason = getattr(e, 'reason', e)
        if 'ollama' == provider:
            raise AiError('连不上本地 Ollama（%s）。请先确认 Ollama 已在运行。' % reason)
        raise AiError('网络不通：%s。如果你在用代理，请确认代理允许该域名。' % reason)
    except Exception as e:
        raise AiError('请求失败：%s' % e)

    if on_delta:
        return _read_stream(resp, on_delta)

    try:
        raw = resp.read().decode('utf-8', 'replace')
        data = json.loads(raw)
    except Exception as e:
        raise AiError('返回内容无法解析：%s' % e)

    return _pick_text(data)


def _pick_text(data):
    try:
        return (data['choices'][0]['message'].get('content') or '').strip()
    except Exception:
        pass
    # 有些网关把错误塞在 200 里
    err = ''
    if isinstance(data, dict):
        err = ((data.get('error') or {}).get('message') if isinstance(data.get('error'), dict)
               else data.get('error')) or data.get('message') or ''
    raise AiError('模型没有返回内容%s' % ('：%s' % err if err else ''))


def _read_stream(resp, on_delta):
    """读 SSE 流，逐段回调。"""
    buf = []
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.decode('utf-8', 'replace').strip()
        if not line or not line.startswith('data:'):
            continue
        chunk = line[5:].strip()
        if chunk == '[DONE]':
            break
        try:
            j = json.loads(chunk)
            delta = (j.get('choices') or [{}])[0].get('delta') or {}
            piece = delta.get('content') or ''
            if piece:
                buf.append(piece)
                try:
                    on_delta(piece)
                except Exception:
                    pass
        except Exception:
            continue
    text = ''.join(buf).strip()
    if not text:
        raise AiError('模型没有返回任何内容（可能是内容被安全策略拦截）')
    return text


# --------------------------------------------------------------------------
# 提示词组装
# --------------------------------------------------------------------------
def build_prompt(template, result=None, results=None, max_items=200, max_chars=24000):
    """把抓取结果渲染进提示词模板。

    template: 'digest' / 'theme' / 'action' / 'extract'，或**用户自己写的整段提示词**
    result:   单本书的结果
    results:  多本书的结果列表（跨书聚合用）

    两个必须保证的事情（用户自定义提示词之后尤其重要）：
      ① 划线正文一定要发出去 —— 用户很可能不写 {content} 占位符，
         检测不到就自动把正文附在提示词末尾，而不是静默丢掉内容。
      ② 用户提示词里若出现别的花括号（比如写了个 JSON 示例），
         str.format 会抛错 —— 这时退化成占位符替换，不因为一个花括号全盘失败。
    """
    text = _template_text(template)

    if results:
        blocks = []
        for r in results:
            blocks.append('## 《%s》（%s）\n%s' % (
                (r.get('book') or {}).get('title', ''),
                (r.get('book') or {}).get('author', '') or '佚名',
                render_lines(r, max_items=max_items)))
        content = _clip('\n\n'.join(blocks), max_chars)
        title, author = '', ''
    else:
        r = result or {}
        book = r.get('book') or {}
        content = _clip(render_lines(r, max_items=max_items), max_chars)
        title = book.get('title', '')
        author = book.get('author', '') or '佚名'

    if '{content}' not in text:
        text = text.rstrip() + _CONTENT_FALLBACK

    try:
        return text.format(content=content, title=title, author=author)
    except (KeyError, IndexError, ValueError):
        out = text.replace('{content}', content)
        out = out.replace('{title}', title)
        out = out.replace('{author}', author)
        return out


def _template_text(template):
    if template in BUILTIN_PROMPTS:
        return BUILTIN_PROMPTS[template]['text']
    if isinstance(template, str) and template.strip():
        return template
    return BUILTIN_PROMPTS['digest']['text']


def render_lines(result, max_items=200):
    """把结果渲染成「序号. [章节] 原文（N 人划线）」的纯文本。"""
    items = result.get('items') or []
    ch = result.get('chapters') or {}
    lines = []
    for i, it in enumerate(items[:max_items], 1):
        chapter = ch.get(it.get('chapterUid')) or ''
        prefix = '[%s] ' % chapter if chapter else ''
        lines.append('%d. %s%s（%s 人划线）' % (
            i, prefix, (it.get('markText') or '').strip(),
            _num(it.get('totalCount'))))
    if len(items) > max_items:
        lines.append('……（还有 %d 条未列出）' % (len(items) - max_items))
    return '\n'.join(lines)


def _num(n):
    try:
        n = int(n or 0)
    except Exception:
        return '0'
    if n >= 100000:
        return '%.1f万' % (n / 10000.0)
    if n >= 10000:
        return '%.1f万' % (n / 10000.0)
    return str(n)


def _clip(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + '\n\n……（内容过长已截断）'


def prompt_label(key):
    """给界面用的显示名。"""
    p = BUILTIN_PROMPTS.get(key)
    return p['name_zh'] if p else str(key)
