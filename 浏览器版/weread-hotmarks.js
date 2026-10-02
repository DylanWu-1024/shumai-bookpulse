/* ============================================================================
 *  微信读书 · 热门划线查看器（浏览器控制台版）
 *  ---------------------------------------------------------------------------
 *  作用：在微信读书网页版里，一键查看「全书被划线最多」的句子，
 *        效果等同手机 App 的「热门划线」，并支持导出 HTML / 复制 Markdown。
 *
 *  用法：在 weread.qq.com 任意页面按 F12 → Console → 粘贴本文件全部内容 → 回车。
 *        详见配套的《使用说明》。
 *
 *  原理：调用微信读书网页版自身的公开接口（同源，只读，不改任何账号数据）：
 *        · 搜索：/web/search/global?keyword=书名
 *        · 热门：/web/book/bestbookmarks?bookId=xxx&count=N
 *        两条接口均【无需登录】即可返回数据。
 * ========================================================================== */
(function () {
  'use strict';

  if (!/weread\.qq\.com$/i.test(location.hostname)) {
    alert('请在微信读书网页版（weread.qq.com）里运行本脚本。');
    return;
  }

  /* ---------- 0. 清理上一次注入，避免重复运行叠加 ---------- */
  const old = document.getElementById('wr-hot-root');
  if (old) old.remove();

  /* ---------- 1. 接口封装 ---------- */
  const apiSearch = kw =>
    'https://weread.qq.com/web/search/global?keyword=' +
    encodeURIComponent(kw) + '&maxIdx=0&fragmentSize=200';

  const apiHot = (bk, n) =>
    'https://weread.qq.com/web/book/bestbookmarks?bookId=' + bk + '&count=' + n;

  // 统一的 JSON 请求（同源，自动带 cookie）
  const getJSON = async url => {
    const r = await fetch(url, { credentials: 'include' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  };

  /* ---------- 2. 容器：Shadow DOM 隔离，避免被页面样式污染 ---------- */
  const host = document.createElement('div');
  host.id = 'wr-hot-root';
  host.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;display:block;';
  (document.body || document.documentElement).appendChild(host);
  const sd = host.attachShadow({ mode: 'open' });

  sd.innerHTML = `
  <style>
    .wrap{width:400px;max-height:86vh;display:flex;flex-direction:column;
      background:#fff;border:1px solid #e3e5e8;border-radius:14px;
      box-shadow:0 12px 40px rgba(0,0,0,.18);overflow:hidden;
      font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222;}
    .hd{display:flex;align-items:center;gap:8px;padding:12px 14px;
      background:linear-gradient(135deg,#07c160,#0aa552);color:#fff;cursor:move;user-select:none;}
    .hd b{font-size:15px;flex:1;}
    .hd .x{cursor:pointer;font-size:20px;line-height:1;opacity:.9;padding:0 2px;}
    .hd .x:hover{opacity:1;}
    .bd{padding:12px 14px;overflow:auto;}
    .row{display:flex;gap:8px;}
    input[type=text]{flex:1;padding:8px 10px;border:1px solid #dcdfe4;border-radius:8px;
      font-size:14px;outline:none;}
    input[type=text]:focus{border-color:#07c160;}
    button{padding:8px 14px;border:0;border-radius:8px;background:#07c160;color:#fff;
      font-size:14px;cursor:pointer;white-space:nowrap;}
    button:hover{background:#06ad56;}
    button.ghost{background:#f2f3f5;color:#333;}
    button.ghost:hover{background:#e8eaed;}
    button:disabled{opacity:.5;cursor:not-allowed;}
    .tip{color:#999;font-size:12px;margin-top:8px;}
    .err{color:#e34d59;font-size:13px;margin-top:8px;}
    .cand{display:flex;gap:10px;padding:9px;border-radius:9px;cursor:pointer;align-items:center;}
    .cand:hover{background:#f5f7fa;}
    .cand img{width:38px;height:52px;object-fit:cover;border-radius:4px;flex:none;background:#eee;}
    .cand .t{font-weight:600;font-size:13px;}
    .cand .a{color:#999;font-size:12px;}
    .bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
      padding:10px 14px;border-top:1px solid #eef0f2;background:#fafbfc;}
    .bar .stat{flex:1;font-size:12px;color:#666;}
    .bar button{padding:6px 10px;font-size:12px;}
    .book{display:flex;gap:10px;align-items:center;padding:0 14px 10px;
      border-bottom:1px solid #eef0f2;}
    .book img{width:32px;height:44px;object-fit:cover;border-radius:4px;}
    .book .meta{flex:1;min-width:0;}
    .book .meta b{display:block;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .book .meta span{font-size:12px;color:#999;}
    .list{overflow:auto;flex:1;min-height:0;}
    .item{padding:11px 14px;border-bottom:1px solid #f2f4f6;}
    .item:hover{background:#fafcff;}
    .item .top{display:flex;align-items:center;gap:8px;margin-bottom:4px;}
    .chip{font-size:11px;color:#0a8f4c;background:#e8f8ef;border-radius:4px;padding:1px 6px;
      max-width:150px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .hot{margin-left:auto;font-size:11px;color:#fff;background:#ff8a3d;
      border-radius:10px;padding:1px 8px;flex:none;}
    .txt{font-size:13.5px;color:#333;word-break:break-word;}
    .idx{color:#c4c8cc;font-size:11px;margin-right:6px;}
    .foot{display:flex;gap:8px;padding:10px 14px;border-top:1px solid #eef0f2;background:#fafbfc;}
    .foot button{flex:1;}
    .spin{display:inline-block;width:12px;height:12px;border:2px solid #cfe9db;
      border-top-color:#07c160;border-radius:50%;animation:sp .7s linear infinite;
      vertical-align:-2px;margin-right:6px;}
    @keyframes sp{to{transform:rotate(360deg)}}
    .filter{padding:6px 10px;font-size:12px;}
    select{padding:5px 6px;border:1px solid #dcdfe4;border-radius:6px;font-size:12px;outline:none;}
  </style>

  <div class="wrap">
    <div class="hd" id="hd">
      <b>热门划线</b>
      <span class="x" id="close" title="关闭">×</span>
    </div>

    <div class="bd" id="bd">
      <div class="row">
        <input type="text" id="kw" placeholder="输入书名，如：一地鸡毛" />
        <button id="go">搜索</button>
      </div>
      <div class="tip">按划线人数从多到少排列，等同手机端「热门划线」。</div>
      <div id="cands"></div>
    </div>

    <div id="result" style="display:none;flex:1;flex-direction:column;min-height:0;">
      <div class="book" id="bookBar"></div>
      <div class="bar">
        <span class="stat" id="stat"></span>
        <select id="topN">
          <option value="50">前 50</option>
          <option value="100" selected>前 100</option>
          <option value="300">前 300</option>
          <option value="0">全部</option>
        </select>
        <button class="ghost" id="back">换书</button>
      </div>
      <input class="filter" type="text" id="filter" placeholder="在结果里筛选关键词…" />
      <div class="list" id="list"></div>
      <div class="foot">
        <button id="expHtml">导出 HTML</button>
        <button class="ghost" id="copyMd">复制 Markdown</button>
      </div>
    </div>
  </div>`;

  const $ = id => sd.getElementById(id);

  /* ---------- 3. 状态 ---------- */
  let state = { book: null, items: [], chapters: {}, total: 0 };

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const numFmt = n => (n >= 10000 ? (n / 10000).toFixed(1) + ' 万' : String(n));

  /* ---------- 4. 关闭 & 拖动 ---------- */
  let closed = false;       // 用户主动关闭后不再自愈
  let guardObs = null;
  let guardTimer = null;

  function teardown() {
    closed = true;
    try { guardObs && guardObs.disconnect(); } catch (e) { }
    if (guardTimer) clearInterval(guardTimer);
    host.remove();
  }
  $('close').onclick = teardown;
  (function drag() {
    const hd = $('hd');
    let sx, sy, ox, oy, on = false;
    hd.addEventListener('mousedown', e => {
      on = true; sx = e.clientX; sy = e.clientY;
      const r = host.getBoundingClientRect(); ox = r.left; oy = r.top;
      e.preventDefault();
    });
    window.addEventListener('mousemove', e => {
      if (!on) return;
      host.style.left = (ox + e.clientX - sx) + 'px';
      host.style.top = (oy + e.clientY - sy) + 'px';
      host.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => { on = false; });
  })();

  /* ---------- 5. 搜索 ---------- */
  async function doSearch() {
    const kw = $('kw').value.trim();
    if (!kw) { $('kw').focus(); return; }
    const box = $('cands');
    box.innerHTML = '<div class="tip"><span class="spin"></span>搜索中…</div>';
    try {
      const d = await getJSON(apiSearch(kw));
      const books = (d.books || []).map(b => b.bookInfo).filter(Boolean);
      if (!books.length) { box.innerHTML = '<div class="err">没搜到，换个关键词试试。</div>'; return; }
      box.innerHTML = '';
      books.forEach(b => {
        const el = document.createElement('div');
        el.className = 'cand';
        el.innerHTML =
          '<img src="' + esc(b.cover) + '" alt="">' +
          '<div><div class="t">' + esc(b.title) + '</div>' +
          '<div class="a">' + esc(b.author || '') + '</div></div>';
        el.onclick = () => loadHot(b);
        box.appendChild(el);
      });
    } catch (e) {
      box.innerHTML = '<div class="err">搜索失败：' + esc(e.message) + '</div>';
    }
  }
  $('go').onclick = doSearch;
  $('kw').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

  /* ---------- 6. 拉取热门划线 ---------- */
  async function loadHot(book) {
    $('cands').innerHTML = '<div class="tip"><span class="spin"></span>正在拉取「' + esc(book.title) + '」的热门划线…</div>';
    try {
      const d = await getJSON(apiHot(book.bookId, 100000));
      const bb = d.bestBookMarks || {};
      const items = bb.items || [];
      const chapters = {};
      (bb.chapters || []).forEach(c => { chapters[c.chapterUid] = c.title; });

      state = {
        book: book,
        items: items,
        chapters: chapters,
        total: bb.totalCount || items.length
      };

      // 书籍信息条
      $('bookBar').innerHTML =
        '<img src="' + esc(book.cover) + '" alt="">' +
        '<div class="meta"><b>' + esc(book.title) + '</b>' +
        '<span>' + esc(book.author || '') + '</span></div>';

      $('bd').style.display = 'none';
      $('result').style.display = 'flex';
      $('filter').value = '';
      render();
    } catch (e) {
      $('cands').innerHTML = '<div class="err">拉取失败：' + esc(e.message) + '</div>';
    }
  }

  /* ---------- 7. 渲染列表 ---------- */
  function currentItems() {
    const kw = $('filter').value.trim();
    const topN = parseInt($('topN').value, 10);
    let arr = state.items.slice();
    if (kw) {
      arr = arr.filter(it =>
        (it.markText || '').includes(kw) ||
        (state.chapters[it.chapterUid] || '').includes(kw));
    }
    if (topN > 0) arr = arr.slice(0, topN);
    return arr;
  }

  function render() {
    const arr = currentItems();
    $('stat').textContent = '共 ' + state.total + ' 条 · 显示 ' +
      arr.length + ' 条' + (state.book ? ' · ' + state.book.title : '');

    const list = $('list');
    list.innerHTML = '';
    if (!arr.length) { list.innerHTML = '<div class="tip" style="padding:14px;">没有匹配的划线。</div>'; return; }

    arr.forEach((it, i) => {
      const ch = state.chapters[it.chapterUid] || '';
      const el = document.createElement('div');
      el.className = 'item';
      el.innerHTML =
        '<div class="top">' +
          '<span class="idx">#' + (i + 1) + '</span>' +
          (ch ? '<span class="chip" title="' + esc(ch) + '">' + esc(ch) + '</span>' : '') +
          '<span class="hot">' + numFmt(it.totalCount || 0) + ' 人划线</span>' +
        '</div>' +
        '<div class="txt">' + esc(it.markText) + '</div>';
      list.appendChild(el);
    });
  }
  $('filter').addEventListener('input', render);
  $('topN').addEventListener('change', render);
  $('back').onclick = () => {
    $('result').style.display = 'none';
    $('bd').style.display = 'block';
    $('cands').innerHTML = '';
    $('kw').focus();
  };

  /* ---------- 8. 导出：单文件 HTML（带复制工具栏，与桌面版同构） ---------- */
  const HTML_TPL = `<!DOCTYPE html>
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

<script type="application/json" id="wrData">{{DATA}}<\/script>
<script>
(function () {
  var D;
  try { D = JSON.parse(document.getElementById('wrData').textContent); }
  catch (e) { return; }

  var msg = document.getElementById('msg');
  var ta = document.getElementById('raw');
  var wrap = document.getElementById('rawWrap');

  function md() {
    var L = ['# 《' + D.title + '》· 热门划线', ''];
    if (D.author) L.push('- 作者：' + D.author);
    L.push('- 导出：共 ' + D.total + ' 条，本页 ' + D.count + ' 条（按划线人数从多到少）');
    L.push('- 生成：' + D.generated);
    L.push('', '---', '');
    D.items.forEach(function (it) {
      L.push(it.i + '. ' + (it.ch ? '[' + it.ch + '] ' : '') + it.text + '（' + it.n + ' 人划线）');
    });
    return L.join('\\n');
  }

  function txt() {
    var L = ['《' + D.title + '》 热门划线' + (D.author ? '（' + D.author + '）' : ''), ''];
    D.items.forEach(function (it) {
      L.push(it.i + '. ' + (it.ch ? '[' + it.ch + '] ' : '') + it.text + '（' + it.n + ' 人划线）');
    });
    L.push('', '共 ' + D.count + ' 条 · 生成于 ' + D.generated);
    return L.join('\\n');
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

  function dl(name, s) {
    var blob = new Blob(['\\ufeff' + s], { type: 'text/markdown;charset=utf-8' });
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
    dl(D.filename, md());
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
<\/script>
</body>
</html>
`;

  function buildHTML() {
    const arr = currentItems();
    const b = state.book || { title: '', author: '', cover: '' };
    const rows = arr.map((it, i) => {
      const ch = state.chapters[it.chapterUid] || '';
      return '<article>' +
        '<div class="m"><span class="n">#' + (i + 1) + '</span>' +
        (ch ? '<span class="c">' + esc(ch) + '</span>' : '') +
        '<span class="h">' + numFmt(it.totalCount || 0) + ' 人划线</span></div>' +
        '<p>' + esc(it.markText) + '</p></article>';
    }).join('');

    /* 卡片与「复制出来的文字」同源于这份数据，保证两边永远一致 */
    const data = {
      title: b.title,
      author: b.author || '',
      total: state.total,
      count: arr.length,
      generated: new Date().toLocaleString('zh-CN'),
      filename: (b.title || 'book').replace(/[\\/:*?"<>|]/g, '_') + '-热门划线.md',
      items: arr.map((it, i) => ({
        i: i + 1,
        ch: state.chapters[it.chapterUid] || '',
        text: it.markText || '',
        n: it.totalCount || 0
      }))
    };
    /* 转义 </ 防止正文里出现 </script> 时提前闭合标签 */
    const payload = JSON.stringify(data).replace(/<\//g, '<\\/');

    return HTML_TPL
      .replace(/\{\{TITLE\}\}/g, esc(b.title))
      .replace(/\{\{AUTHOR\}\}/g, esc(b.author || ''))
      .replace(/\{\{N\}\}/g, String(arr.length))
      .replace(/\{\{TOTAL\}\}/g, String(state.total))
      .replace(/\{\{ROWS\}\}/g, rows)
      .replace(/\{\{GEN\}\}/g, esc(data.generated))
      .replace(/\{\{DATA\}\}/g, payload);
  }

  function download(name, text) {
    const blob = new Blob([text], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  }

  $('expHtml').onclick = () => {
    if (!state.book) return;
    const safe = (state.book.title || 'book').replace(/[\\/:*?"<>|]/g, '_');
    download(safe + '-热门划线.html', buildHTML());
  };

  /* ---------- 9. 复制 Markdown ---------- */
  $('copyMd').onclick = async () => {
    if (!state.book) return;
    const arr = currentItems();
    let md = '# ' + state.book.title + ' · 热门划线\n\n';
    arr.forEach((it, i) => {
      const ch = state.chapters[it.chapterUid] || '';
      md += (i + 1) + '. ' + (ch ? '**[' + ch + ']** ' : '') +
        it.markText + ' —— *' + (it.totalCount || 0) + ' 人划线*\n';
    });
    try {
      await navigator.clipboard.writeText(md);
      const btn = $('copyMd');
      const old = btn.textContent;
      btn.textContent = '已复制 ✓';
      setTimeout(() => { btn.textContent = old; }, 1500);
    } catch (e) {
      alert('复制失败，可改用「导出 HTML」。');
    }
  };

  /* ---------- 10. 预填书名（阅读器页面标题即书名） ---------- */
  (function prefill() {
    let t = (document.title || '').replace(/\s*[-|·]\s*微信读书.*$/, '').trim();
    if (t && t !== '微信读书' && !/^微信读书/.test(t)) $('kw').value = t;
    $('kw').focus();
    $('kw').select();
  })();

  /* ---------- 11. 自愈守护：页面重渲染把面板删掉时，自动装回来 ---------- */
  function ensureMounted() {
    if (closed || host.isConnected) return;
    (document.body || document.documentElement).appendChild(host);
  }
  let rafPending = false;
  function scheduleEnsure() {
    if (closed || rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => { rafPending = false; ensureMounted(); });
  }
  try {
    guardObs = new MutationObserver(scheduleEnsure);
    guardObs.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) { }
  guardTimer = setInterval(ensureMounted, 1000);   // 双保险

  // 逃生口：万一还是被清掉，控制台执行 __wrHotmarks.show() 即可唤回
  window.__wrHotmarks = {
    show() { closed = false; ensureMounted(); },
    hide: teardown,
    el: host
  };

  console.log('%c[热门划线] 已就绪：输入书名 → 搜索 → 选书 → 导出。', 'color:#07c160;font-weight:bold');
  console.log('%c若面板被页面清掉，控制台执行 __wrHotmarks.show() 可重新唤出。', 'color:#999');
})();
