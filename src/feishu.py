# -*- coding: utf-8 -*-
"""
飞书推送（自定义机器人 Webhook）
================================================================================
只依赖标准库。支持两种消息：
  · text        纯文本，最稳
  · interactive 卡片（带标题、分隔线、按钮链接），观感好得多

自定义机器人注意：若开启了「签名校验」，需要把 secret 一起填进来；
这里实现了飞书官方要求的 HMAC-SHA256 + Base64 签名算法。
"""
import time
import json
import hmac
import base64
import hashlib
import urllib.request
import urllib.error


class FeishuError(Exception):
    """推送失败。消息可直接展示给用户。"""


def _sign(secret, timestamp):
    """飞书签名：以 '{timestamp}\\n{secret}' 为密钥，对空串做 HmacSHA256 后 base64。"""
    string_to_sign = '%s\n%s' % (timestamp, secret)
    h = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256)
    return base64.b64encode(h.digest()).decode('utf-8')


def _post(webhook, payload, timeout=15):
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST')
    try:
        # 走 core 的统一出口，遵守「设置 → 网络 → 连接方式」；
        # core 缺席时（独立调用本模块）退回系统默认。
        try:
            import core as _core
            opener = _core.open_request
        except ImportError:
            opener = urllib.request.urlopen
        with opener(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        raise FeishuError('飞书返回 HTTP %s' % e.code)
    except urllib.error.URLError as e:
        raise FeishuError('网络不通：%s' % getattr(e, 'reason', e))
    except Exception as e:
        raise FeishuError('请求失败：%s' % e)

    try:
        j = json.loads(raw)
    except Exception:
        raise FeishuError('飞书返回内容无法解析：%s' % raw[:120])

    code = j.get('code', j.get('StatusCode', 0))
    if code not in (0, None):
        msg = j.get('msg') or j.get('StatusMessage') or ''
        raise FeishuError('飞书拒绝（code=%s）：%s' % (code, msg))
    return True


def _auth(webhook, secret):
    """把签名参数拼进 URL。"""
    if not secret:
        return webhook
    ts = str(int(time.time()))
    sign = _sign(secret, ts)
    sep = '&' if '?' in webhook else '?'
    return '%s%stimestamp=%s&sign=%s' % (webhook, sep, ts, sign)


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def send_text(webhook, text, secret='', timeout=15):
    webhook = (webhook or '').strip()
    if not webhook:
        raise FeishuError('还没有配置飞书 Webhook 地址')
    payload = {'msg_type': 'text', 'content': {'text': text}}
    return _post(_auth(webhook, secret), payload, timeout)


def send_rich_text(webhook, title, lines, secret='', timeout=15):
    """富文本（post）：标题 + 若干行，行内支持加粗。"""
    webhook = (webhook or '').strip()
    if not webhook:
        raise FeishuError('还没有配置飞书 Webhook 地址')
    content = []
    if title:
        content.append([{'tag': 'text', 'text': title}])
    for ln in lines:
        if isinstance(ln, (list, tuple)):
            content.append([{'tag': 'text', 'text': str(x)} for x in ln])
        else:
            content.append([{'tag': 'text', 'text': str(ln)}])
    payload = {'msg_type': 'post',
               'content': {'post': {'zh_cn': {'title': title or '', 'content': content}}}}
    return _post(_auth(webhook, secret), payload, timeout)


def send_card(webhook, title, sections, button=None, secret='', timeout=15):
    """交互卡片。

    sections: [{'title': str, 'lines': [str, ...]}, ...]
    button:   {'text': str, 'url': str} 可选
    """
    webhook = (webhook or '').strip()
    if not webhook:
        raise FeishuError('还没有配置飞书 Webhook 地址')

    elements = []
    for i, sec in enumerate(sections):
        if i:
            elements.append({'tag': 'hr'})
        if sec.get('title'):
            elements.append({'tag': 'div',
                             'text': {'tag': 'lark_md', 'content': '**%s**' % sec['title']}})
        if sec.get('lines'):
            body = '\n'.join(str(x) for x in sec['lines'])
            elements.append({'tag': 'div', 'text': {'tag': 'lark_md', 'content': body}})

    if button and button.get('url'):
        elements.append({
            'tag': 'action',
            'actions': [{'tag': 'button', 'text': {'tag': 'plain_text',
                                                   'content': button.get('text', '查看')},
                         'type': 'primary', 'url': button['url']}],
        })

    elements.append({'tag': 'note',
                     'elements': [{'tag': 'plain_text',
                                   'content': time.strftime('%Y-%m-%d %H:%M')}]})

    payload = {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True},
            'header': {'title': {'tag': 'plain_text', 'content': title or '消息'},
                       'template': 'indigo'},
            'elements': elements,
        },
    }
    return _post(_auth(webhook, secret), payload, timeout)


# --------------------------------------------------------------------------
# 业务封装：把「新晋热门划线」推成一条卡片
# --------------------------------------------------------------------------
def push_trend_card(webhook, title, book_title, book_author, trends,
                    total=None, secret='', button_url=None, limit=12):
    """把 watch.check_all() 里一本书的结果推成飞书卡片。"""
    lines = []
    for t in trends[:limit]:
        text = (t.get('text') or '').replace('\n', ' ').strip()
        if len(text) > 78:
            text = text[:78] + '…'
        if t.get('kind') == 'new':
            lines.append('• 🆕 %s（%s 人划线）' % (text, _num(t.get('new'))))
        else:
            lines.append('• 🔥 %s（+%s → %s 人划线）'
                         % (text, _num(t.get('delta')), _num(t.get('new'))))
    if not lines:
        lines = ['（本次检查没有发现新晋热门划线）']
    if len(trends) > limit:
        lines.append('……还有 %d 条' % (len(trends) - limit))

    head = '《%s》%s' % (book_title, ('· ' + book_author) if book_author else '')
    sec = [{'title': head, 'lines': lines}]
    if total is not None:
        sec.append({'title': '当前总量', 'lines': ['%s 条热门划线' % _num(total)]})
    btn = {'text': '打开书脉', 'url': button_url} if button_url else None
    return send_card(webhook, title, sec, button=btn, secret=secret)


def _num(n):
    try:
        n = int(n or 0)
    except Exception:
        return '0'
    if n >= 10000:
        return '%.1f万' % (n / 10000.0)
    return str(n)
