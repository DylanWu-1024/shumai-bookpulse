# -*- coding: utf-8 -*-
"""
导出引擎扩展：Word / EPUB / 打印版 HTML
================================================================================
设计原则与 core 一致：**只依赖标准库**，不引入 python-docx / ebooklib 这类第三方库。

为什么不用第三方库？
  · python-docx 要拖 lxml（打包体积 +8MB），而我们只需要写，不需要解析
  · .docx 本质就是 zip + 几份 XML；EPUB 本质就是 zip + XHTML
  自己拼反而能**精确控制排版**（字号、主题色、章节分组全按模板来）

PDF 不在这里 —— 它由界面层用 Qt 的 QTextDocument + QPdfWriter 渲染，
core 只负责产出「打印版 HTML」（见 build_print_html）。
"""
import io
import re
import html
import time
import uuid
import zipfile

# --------------------------------------------------------------------------
# 导出模板默认值（设置页可改）
# --------------------------------------------------------------------------
DEFAULT_STYLE = {
    'font_size': 15,        # 正文字号（pt）
    'show_chapter': True,   # 是否分组/显示章节名
    'accent': '#7C3AED',    # 标题主题色
    'ink': '#22203F',       # 正文色
    'line_height': 1.8,     # 行高倍数
    'show_index': True,     # 是否给每条加序号
    'page': 'A4',           # 纸张（PDF / Word 用）
}


def make_style(raw=None):
    """把设置里读到的字典补齐成完整模板；缺项一律回落默认。"""
    s = dict(DEFAULT_STYLE)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in s and v is not None:
                s[k] = v
    try:
        s['font_size'] = max(8, min(30, int(s['font_size'])))
    except Exception:
        s['font_size'] = DEFAULT_STYLE['font_size']
    try:
        s['line_height'] = max(1.0, min(3.0, float(s['line_height'])))
    except Exception:
        s['line_height'] = DEFAULT_STYLE['line_height']
    if not re.match(r'^#[0-9A-Fa-f]{6}$', str(s['accent'])):
        s['accent'] = DEFAULT_STYLE['accent']
    if not re.match(r'^#[0-9A-Fa-f]{6}$', str(s['ink'])):
        s['ink'] = DEFAULT_STYLE['ink']
    return s


def esc(s):
    return html.escape(str(s or ''), quote=True)


def _hex(color):
    """'#7C3AED' → '7C3AED'（OOXML 不带 #）。"""
    return str(color or '').lstrip('#').upper()[:6] or '7C3AED'


# --------------------------------------------------------------------------
# 公共：把结果整理成「章节 → 条目」的中间结构
# --------------------------------------------------------------------------
def grouped(result, style):
    """返回 [(章节名 or '', [(序号, 文本)])]，章节为空时只有一组。"""
    items = result.get('items') or []
    ch_map = result.get('chapters') or {}
    numbered = list(enumerate(items, 1))

    if not style.get('show_chapter'):
        return [('', numbered)]

    buckets = []
    order = {}
    for i, it in numbered:          # 注意：要遍历带序号的那份，不是原始 items
        uid = it.get('chapterUid') or ''
        if uid not in order:
            order[uid] = []
            buckets.append((ch_map.get(uid) or '', order[uid]))
        order[uid].append((i, it))
    if not buckets:
        return [('', [])]
    return buckets


def _body_items(group):
    return [(i, (it.get('markText') or '').strip()) for i, it in group]


# ==========================================================================
# Word（.docx）—— 最小合规 OOXML
# ==========================================================================
_CT = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''

_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

_DOC_HEAD = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>'''

_DOC_TAIL = '''<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>
<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>
</w:body></w:document>'''

_FONT = 'Microsoft YaHei'


def _docx_p(text, size_pt=15, bold=False, color='22203F', align=None,
            before=0, after=120, indent=0):
    """生成一个段落。sz 的单位是「半磅」，所以 pt 要乘 2。"""
    ppr = ['<w:spacing w:before="%d" w:after="%d"/>' % (int(before), int(after))]
    if align:
        ppr.append('<w:jc w:val="%s"/>' % align)
    if indent:
        ppr.append('<w:ind w:left="%d"/>' % int(indent))
    rpr = ['<w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s"/>' % (_FONT, _FONT, _FONT),
           '<w:sz w:val="%d"/>' % int(round(float(size_pt) * 2)),
           '<w:szCs w:val="%d"/>' % int(round(float(size_pt) * 2)),
           '<w:color w:val="%s"/>' % color]
    if bold:
        rpr.append('<w:b/>')
    # 保留首尾空格（中文里少见，但英文引文会出现）
    return ('<w:p><w:pPr>%s</w:pPr><w:r><w:rPr>%s</w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
            % (''.join(ppr), ''.join(rpr), esc(text)))


def _docx_rule(color):
    """一条横线：用段落下边框实现，比画表格轻。"""
    return ('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" '
            'w:color="%s"/></w:pBdr><w:spacing w:before="60" w:after="160"/></w:pPr></w:p>'
            % color)


def build_docx(result, with_people=True, style=None):
    """返回 .docx 的字节内容。"""
    st = make_style(style)
    book = result.get('book') or {}
    title = book.get('title') or '热门划线'
    author = book.get('author') or ''
    accent = _hex(st['accent'])
    ink = _hex(st['ink'])
    size = st['font_size']

    body = [_docx_p('《%s》' % title, size_pt=size + 9, bold=True,
                    color=accent, align='center', before=240, after=80)]
    sub = author or ''
    if with_people:
        sub = (sub + '   ·   ' if sub else '') + '共 %s 条热门划线' % result.get('total', 0)
    elif sub:
        sub += '   ·   热门划线'
    if sub:
        body.append(_docx_p(sub, size_pt=size - 3, color='8A89A8',
                            align='center', before=0, after=60))
    body.append(_docx_rule(accent))

    for chap, group in grouped(result, st):
        rows = _body_items(group)
        if not rows:
            continue
        if chap:
            body.append(_docx_p(chap, size_pt=size + 2, bold=True,
                                color=accent, before=260, after=90))
        for i, text in rows:
            line = ('%d. %s' % (i, text)) if st.get('show_index') else text
            if with_people:
                n = ''
                try:
                    n = group[[x[0] for x in rows].index(i)][1].get('totalCount')
                except Exception:
                    n = ''
                if n:
                    line += '（%s 人划线）' % n
            body.append(_docx_p(line, size_pt=size, color=ink,
                                before=0, after=100))
            # Word 没有行高属性直接对应 line_height，用段前段后间距近似

    doc = _DOC_HEAD + ''.join(body) + _DOC_TAIL

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CT)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('word/document.xml', doc)
    return buf.getvalue()


# ==========================================================================
# EPUB 3.0
# ==========================================================================
_EPUB_CSS = '''@charset "utf-8";
body { font-family: "PingFang SC","Microsoft YaHei",sans-serif; color: %(ink)s;
       line-height: %(lh)s; margin: 0 6%%; }
h1 { color: %(accent)s; font-size: 1.6em; text-align: center; margin: .8em 0 .2em; }
.sub { color: #8A89A8; text-align: center; font-size: .85em; margin-bottom: 1.6em; }
h2 { color: %(accent)s; font-size: 1.12em; margin: 1.6em 0 .6em;
     border-left: 4px solid %(accent)s; padding-left: .5em; }
p.item { font-size: %(size).3fpt; margin: .75em 0; text-indent: 0; }
p.item .n { color: #B9B8CF; margin-right: .35em; }
p.item .h { color: #8A89A8; font-size: .8em; }
'''


def _xhtml(title, body_html, css='style.css'):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">\n'
            '<head><meta charset="utf-8"/><title>%s</title>'
            '<link rel="stylesheet" type="text/css" href="%s"/></head>\n'
            '<body>%s</body></html>' % (esc(title), css, body_html))


def build_epub(result, with_people=True, style=None):
    """返回 .epub 的字节内容（EPUB 3.0，带 nav 与 ncx 双目录）。"""
    st = make_style(style)
    book = result.get('book') or {}
    title = book.get('title') or '热门划线'
    author = book.get('author') or ''
    accent = st['accent'] if re.match(r'^#[0-9A-Fa-f]{6}$', str(st['accent'])) else '#7C3AED'
    ink = st['ink'] if re.match(r'^#[0-9A-Fa-f]{6}$', str(st['ink'])) else '#22203F'
    uid = 'urn:uuid:%s' % uuid.uuid4()
    modified = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    groups = grouped(result, st)
    chapters = []           # [(文件名, 章节名, xhtml)]
    all_items = []

    for idx, (chap, group) in enumerate(groups, 1):
        rows = _body_items(group)
        if not rows:
            continue
        name = 'text/chap%d.xhtml' % idx
        parts = []
        if st.get('show_chapter') and chap:
            parts.append('<h2>%s</h2>' % esc(chap))
        for i, text in rows:
            line = '<span class="n">%d.</span>' % i if st.get('show_index') else ''
            all_items.append(text)
            hot = ''
            if with_people:
                try:
                    hot = '<span class="h">（%s 人划线）</span>' % _people_of(result, i)
                except Exception:
                    hot = ''
            parts.append('<p class="item">%s%s%s</p>' % (line, esc(text), hot))
        chapters.append((name, chap or ('第 %d 节' % idx), _xhtml(title, ''.join(parts))))

    if not chapters:
        chapters.append(('text/chap1.xhtml', title,
                         _xhtml(title, '<p class="item">（没有可导出的划线）</p>')))

    # 封面页
    sub = author or ''
    if with_people:
        sub = (sub + '   ·   ' if sub else '') + '共 %s 条' % result.get('total', 0)
    cover_body = ('<h1>《%s》</h1>%s<p class="sub">%s</p>'
                  % (esc(title), '<p class="sub">%s</p>' % esc(author) if author else '',
                     esc(sub)))
    cover_name = 'text/cover.xhtml'

    css = _EPUB_CSS % {'ink': ink, 'lh': st['line_height'],
                       'accent': accent, 'size': float(st['font_size'])}

    # nav.xhtml（EPUB3 导航）
    nav_lis = ''.join('<li><a href="%s">%s</a></li>' % (n, esc(t))
                      for n, t, _ in chapters)
    nav = _xhtml('目录',
                 '<nav epub:type="toc" id="toc"><h1>目录</h1><ol>%s</ol></nav>' % nav_lis)

    # toc.ncx（兼容旧阅读器）
    navpoints = ''.join(
        '<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, i + 1, esc(t), n)
        for i, (n, t, _) in enumerate(chapters, 1))
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           '<head><meta name="dtb:uid" content="%s"/>'
           '<meta name="dtb:depth" content="1"/></head>'
           '<docTitle><text>%s</text></docTitle><navMap>%s</navMap></ncx>'
           % (uid, esc(title), navpoints))

    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>',
                '<item id="cover" href="%s" media-type="application/xhtml+xml"/>' % cover_name]
    spine = ['<itemref idref="cover"/>']
    for i, (n, _t, _x) in enumerate(chapters, 1):
        manifest.append('<item id="c%d" href="%s" media-type="application/xhtml+xml"/>' % (i, n))
        spine.append('<itemref idref="c%d"/>' % i)

    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           'unique-identifier="bookid" xml:lang="zh-CN">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:identifier id="bookid">%s</dc:identifier>'
           '<dc:title>《%s》热门划线</dc:title>'
           '<dc:creator>%s</dc:creator>'
           '<dc:language>zh-CN</dc:language>'
           '<meta property="dcterms:modified">%s</meta>'
           '</metadata><manifest>%s</manifest>'
           '<spine toc="ncx">%s</spine></package>'
           % (uid, esc(title), esc(author or '书脉整理'),
              modified, ''.join(manifest), ''.join(spine)))

    container = ('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<container version="1.0" '
                 'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                 'media-type="application/oebps-package+xml"/></rootfiles></container>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # mimetype 必须是第一个条目且**不压缩**，否则阅读器不认
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                   compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', nav)
        z.writestr('OEBPS/toc.ncx', ncx)
        z.writestr('OEBPS/style.css', css)
        z.writestr('OEBPS/%s' % cover_name, cover_body_html(title, author, sub))
        for n, _t, x in chapters:
            z.writestr('OEBPS/%s' % n, x)
    return buf.getvalue()


def cover_body_html(title, author, sub):
    return _xhtml(title,
                  '<h1>《%s》</h1>%s<p class="sub">%s</p>'
                  % (esc(title),
                     '<p class="sub">%s</p>' % esc(author) if author else '',
                     esc(sub)))


def _people_of(result, seq):
    items = result.get('items') or []
    if 1 <= seq <= len(items):
        n = items[seq - 1].get('totalCount')
        if n:
            return n
    return ''


# ==========================================================================
# 打印版 HTML（给 PDF 渲染用）
# ==========================================================================
def build_print_html(result, with_people=True, style=None):
    """QTextDocument 只认 HTML/CSS 的一个子集（没有 flex / grid / 渐变），
    所以这里刻意写得非常朴素：标题 + 段落 + 内联样式。
    """
    st = make_style(style)
    book = result.get('book') or {}
    title = book.get('title') or '热门划线'
    author = book.get('author') or ''
    accent = st['accent']
    ink = st['ink']
    size = st['font_size']
    lh = st['line_height']

    out = ['<h1 style="color:%s;font-size:%dpt;text-align:center;">《%s》</h1>'
           % (accent, size + 9, esc(title))]
    if author:
        out.append('<p style="color:#8A89A8;font-size:%dpt;text-align:center;">%s</p>'
                   % (max(8, size - 3), esc(author)))
    meta = '共 %s 条热门划线' % result.get('total', 0)
    out.append('<p style="color:#8A89A8;font-size:%dpt;text-align:center;">%s</p>'
               % (max(8, size - 3), esc(meta)))
    out.append('<hr style="border:none;border-top:1px solid %s;"/>' % accent)

    for chap, group in grouped(result, st):
        rows = _body_items(group)
        if not rows:
            continue
        if chap:
            out.append('<h2 style="color:%s;font-size:%dpt;margin-top:14pt;">%s</h2>'
                       % (accent, size + 2, esc(chap)))
        for i, text in rows:
            line = '%d. %s' % (i, text) if st.get('show_index') else text
            hot = ''
            if with_people:
                n = _people_of(result, i)
                hot = (' <span style="color:#8A89A8;">（%s 人划线）</span>' % n) if n else ''
            out.append('<p style="color:%s;font-size:%dpt;line-height:%s;">%s%s</p>'
                       % (ink, size, lh, esc(line), hot))

    return ('<html><head><meta charset="utf-8"/></head><body>%s</body></html>'
            % ''.join(out))
