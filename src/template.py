# -*- coding: utf-8 -*-
"""
微信读书 · 热门划线 —— HTML 输出模板
================================================================
单文件、内联 CSS/JS、零外链，可直接双击在浏览器里打开。

占位符（由 core.to_html 填充）：
    {{TITLE}}   书名             {{AUTHOR}}  作者
    {{N}}       本页条数          {{TOTAL}}   总计条数
    {{ROWS}}    卡片列表 HTML     {{GEN}}     生成时间
    {{DATA}}    内嵌 JSON 数据（供复制/下载按钮使用）

为什么数据要内嵌而不是直接拼文本？
    卡片与「复制出来的文字」必须永远一致。两者同源于
    <script id="wrData"> 里的那份 JSON，以后改格式只改一处，
    不会出现「看的和复制的不一样」。
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}} · 热门划线</title>
<style>
body{margin:0;background:#f4f6f8;font:16px/1.85 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}
header{background:linear-gradient(135deg,#07c160,#0aa552);color:#fff;padding:30px 20px}
header h1{margin:0;font-size:22px}
header p{margin:8px 0 0;opacity:.92;font-size:14px}
.bar{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid #e6e9ec;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.bar .in{max-width:760px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button{font-family:inherit;font-size:14px;padding:8px 14px;border:0;border-radius:8px;cursor:pointer;background:#07c160;color:#fff}
button:hover{background:#06ad56}
button.g{background:#f2f3f5;color:#333}
button.g:hover{background:#e6e9ec}
button:disabled{cursor:default}
.msg{font-size:13px;color:#0a8f4c;margin-left:auto;min-height:18px}
.msg.warn{color:#e34d59}
#rawWrap{max-width:760px;margin:14px auto 0;padding:0 16px}
#raw{width:100%;box-sizing:border-box;height:280px;padding:14px;border:1px solid #dcdfe4;border-radius:10px;
background:#fff;color:#333;font:13px/1.7 ui-monospace,Consolas,"Courier New",monospace;resize:vertical}
main{max-width:760px;margin:24px auto;padding:0 16px}
article{background:#fff;border-radius:12px;padding:16px 18px;margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
article p{margin:8px 0 0;font-size:16px;line-height:1.9}
.m{display:flex;align-items:center;gap:8px;font-size:12px;color:#999}
.n{color:#c4c8cc}.c{background:#e8f8ef;color:#0a8f4c;border-radius:4px;padding:1px 7px}
.h{margin-left:auto;background:#ff8a3d;color:#fff;border-radius:10px;padding:1px 9px}
footer{text-align:center;color:#9aa0a6;font-size:12px;padding:22px}
</style>
</head>
<body>

<header><h1>{{TITLE}}</h1><p>{{AUTHOR}} · 热门划线 {{N}} 条 / 总计 {{TOTAL}} 条</p></header>

<div class="bar"><div class="in">
  <button id="bMd" title="带序号的 Markdown，直接粘贴给 DeepSeek 整理">复制 Markdown</button>
  <button id="bTxt" class="g" title="无 Markdown 标记的纯净版">复制纯文本</button>
  <button id="bDl" class="g" title="保存为 .md 文件">下载 .md</button>
  <button id="bRaw" class="g" title="展开可手动全选的文本框">整合文本区</button>
  <span class="msg" id="msg"></span>
</div></div>

<div id="rawWrap" hidden><textarea id="raw" readonly spellcheck="false"></textarea></div>

<main>{{ROWS}}</main>

<footer>由「微信读书 · 热门划线导出工具」生成 · {{GEN}}</footer>

<script type="application/json" id="wrData">{{DATA}}</script>
<script>
(function () {
  var D;
  try { D = JSON.parse(document.getElementById('wrData').textContent); }
  catch (e) { return; }

  var msg = document.getElementById('msg');
  var ta = document.getElementById('raw');
  var wrap = document.getElementById('rawWrap');

  /* 整合文本 · Markdown 版（主推，喂给 LLM） */
  function md() {
    var L = ['# 《' + D.title + '》· 热门划线', ''];
    if (D.author) L.push('- 作者：' + D.author);
    L.push('- 导出：共 ' + D.total + ' 条，本页 ' + D.count + ' 条（按划线人数从多到少）');
    L.push('- 生成：' + D.generated);
    L.push('', '---', '');
    D.items.forEach(function (it) {
      L.push(it.i + '. ' + (it.ch ? '[' + it.ch + '] ' : '') + it.text
              + (it.n ? '（' + it.n + ' 人划线）' : ''));
    });
    return L.join('\n');
  }

  /* 整合文本 · 纯文本版（兜底用） */
  function txt() {
    var L = ['《' + D.title + '》 热门划线' + (D.author ? '（' + D.author + '）' : ''), ''];
    D.items.forEach(function (it) {
      L.push(it.i + '. ' + (it.ch ? '[' + it.ch + '] ' : '') + it.text
              + (it.n ? '（' + it.n + ' 人划线）' : ''));
    });
    L.push('', '共 ' + D.count + ' 条 · 生成于 ' + D.generated);
    return L.join('\n');
  }

  function say(s, warn) {
    msg.textContent = s || '';
    msg.className = 'msg' + (warn ? ' warn' : '');
  }

  function pill(btn, s) {
    var old = btn.textContent;
    btn.textContent = s;
    btn.disabled = true;
    setTimeout(function () { btn.textContent = old; btn.disabled = false; }, 1600);
  }

  /* 兜底：展开文本区 + 全选 + execCommand('copy') */
  function fallbackCopy(s) {
    wrap.hidden = false;
    document.getElementById('bRaw').textContent = '收起文本区';
    ta.value = s;
    try { ta.focus(); ta.select(); } catch (e) {}
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    return ok;
  }

  function copy(s, btn) {
    function done(ok) {
      if (ok) {
        pill(btn, '已复制 ' + (s.length >= 1000 ? (s.length / 1000).toFixed(1) + 'k' : s.length) + ' 字');
        say('已复制，直接粘贴给 DeepSeek 即可。');
      } else {
        pill(btn, '请手动复制');
        say('浏览器拒绝了自动复制：文本已在下方全选，按 Ctrl+C 即可。', true);
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(s).then(function () { done(true); },
                                            function () { done(fallbackCopy(s)); });
    } else {
      done(fallbackCopy(s));
    }
  }

  function download(name, s) {
    var blob = new Blob(['\ufeff' + s], { type: 'text/markdown;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  document.getElementById('bMd').onclick = function () { copy(md(), this); };
  document.getElementById('bTxt').onclick = function () { copy(txt(), this); };
  document.getElementById('bDl').onclick = function () {
    download(D.filename, md());
    say('已下载：' + D.filename);
  };
  document.getElementById('bRaw').onclick = function () {
    if (wrap.hidden) {
      if (!ta.value) ta.value = md();
      wrap.hidden = false;
      this.textContent = '收起文本区';
      ta.focus(); ta.select();
    } else {
      wrap.hidden = true;
      this.textContent = '整合文本区';
    }
  };
})();
</script>
</body>
</html>
"""


# ==========================================================================
# 分享版模板（方向 7）
# ==========================================================================
# 与上面那份「工具版」的区别：
#   · 工具版给作者自己用 —— 带复制按钮、整合文本区、下载 Markdown
#   · 分享版给朋友看   —— 纯阅读、移动端优先、带 OG 标签（微信/飞书里发链接有预览图）
# 两者都是**单文件、零外链**，对方双击/收文件即可打开，不需要任何环境。
#
# 占位符：
#     {{TITLE}} {{AUTHOR}} {{DESC}} {{STAT}} {{SECTIONS}} {{GEN}}
SHARE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{{TITLE}} · 热门划线</title>
<meta name="description" content="{{DESC}}">
<meta property="og:type" content="article">
<meta property="og:title" content="《{{TITLE}}》热门划线">
<meta property="og:description" content="{{DESC}}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%236366F1'/%3E%3Cpath d='M20 18h24M20 18v28M44 18v28M20 32h24' stroke='%23fff' stroke-width='4' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#F6F7FC;color:#171635;
font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.hero{background:linear-gradient(140deg,#4F46E5 0%,#7C3AED 52%,#DB2777 100%);
color:#fff;padding:46px 22px 40px}
.hero .tag{display:inline-block;font-size:12px;letter-spacing:.14em;text-transform:uppercase;
opacity:.85;border:1px solid rgba(255,255,255,.45);border-radius:99px;padding:3px 12px}
.hero h1{margin:16px 0 8px;font-size:27px;line-height:1.32;font-weight:800;letter-spacing:-.01em}
.hero .by{opacity:.9;font-size:14px}
.hero .stat{margin-top:20px;display:flex;gap:22px;flex-wrap:wrap}
.hero .stat b{display:block;font-size:21px;font-weight:800;letter-spacing:-.01em}
.hero .stat span{font-size:12px;opacity:.82}
main{max-width:760px;margin:0 auto;padding:22px 16px 10px}
section{margin-bottom:26px}
.sechead{display:flex;align-items:baseline;gap:10px;margin:0 0 12px}
.sechead h2{margin:0;font-size:16px;font-weight:700;color:#2B2A55}
.sechead .cnt{font-size:12px;color:#8B8AAE;margin-left:auto;white-space:nowrap}
.bar{height:4px;border-radius:99px;background:#E6E7F4;overflow:hidden;margin-bottom:14px}
.bar i{display:block;height:100%;border-radius:99px;
background:linear-gradient(90deg,#6366F1,#A855F7)}
article{background:#fff;border-radius:14px;padding:15px 17px;margin-bottom:11px;
box-shadow:0 2px 10px rgba(35,32,90,.06)}
article .meta{display:flex;align-items:center;gap:8px;font-size:12px;color:#9A99B8}
article .n{color:#C6C5DA;font-variant-numeric:tabular-nums}
article .hot{margin-left:auto;background:#EDEBFE;color:#6D28D9;font-weight:600;
border-radius:99px;padding:2px 10px;white-space:nowrap}
article p{margin:9px 0 0;font-size:16.5px;line-height:1.85;color:#22203F}
footer{text-align:center;color:#9A99B8;font-size:12px;padding:26px 20px 40px;line-height:2}
footer b{color:#6D28D9}
@media (max-width:430px){
 .hero{padding:36px 18px 32px}.hero h1{font-size:22px}
 article{padding:13px 15px}article p{font-size:16px}
}
@media print{
 body{background:#fff}.hero{background:#fff;color:#000}
 article{box-shadow:none;border:1px solid #E6E7F4;break-inside:avoid}
}
</style>
</head>
<body>
<header class="hero">
  <span class="tag">WeRead Highlights</span>
  <h1>《{{TITLE}}》</h1>
  <div class="by">{{AUTHOR}}</div>
  <div class="stat">{{STAT}}</div>
</header>
<main>{{SECTIONS}}</main>
<footer>
  由 <b>书脉 BookPulse</b> 整理 · 内容来自微信读书读者公开划线<br>
  生成于 {{GEN}}
</footer>
</body>
</html>
"""
