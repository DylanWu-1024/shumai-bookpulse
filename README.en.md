<div align="center">

<img src="docs/logo.png" width="128" alt="BookPulse">

# BookPulse · 书脉

**Turn the sentences everyone highlights in WeRead into your own knowledge base**

Fetch · Archive · AI-organize · Export to 9 formats

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5%2B-41CD52?logo=qt&logoColor=white)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)](#)
[![No Tracking](https://img.shields.io/badge/Network-Read--only%20%C2%B7%20No%20Cookie-brightgreen)](#-disclaimer)

[Features](#-features) · [Quick Start](#-quick-start) · [Screenshots](#-screenshots) · [Export Formats](#-export-formats) · [FAQ](#-faq) · [中文文档](README.md)

</div>

---

## 📖 What is this

WeRead (微信读书) has millions of reader highlights, but the web version offers **no aggregated view** — you can only scroll page by page and never see *which sentence was highlighted by the most people*.

**BookPulse** pulls that data out, stores it locally, and turns it into material you actually own:

- 🔍 Search a book and **instantly judge which edition is worth reading** (recommendation score / rating count / current readers)
- 📥 Fetch all popular highlights of a book, **sorted by how many people highlighted them**
- 🗄️ Save into a local library — **opens offline**, and tracks *which sentence is gaining popularity over time*
- 🤖 One click to let an AI turn scattered quotes into structured notes (DeepSeek / Zhipu / SiliconFlow / Alibaba Cloud / local Ollama)
- 📄 Export to **Markdown / Word / PDF / EPUB / HTML and more** — nine formats in total
- 🧠 Cross-book search, cross-book deduplication, mind maps, popularity trend charts

> Real-world scale: 《活着》972 highlights ·《一地鸡毛》952 ·《人类简史》984 — retrieved in a single request, no pagination loop.

---

## ✨ Features

### Fetch & Choose
| Feature | Description |
|---|---|
| **Book metrics** | Search results show **recommendation score / rating count / rating tier / current readers / publisher / completion status** at a glance — 《活着》92.0% vs a same-titled book at 53.8% |
| **One-shot full fetch** | All popular highlights retrieved in **a single request** (nearly a thousand records measured), no pagination loop |
| **Batch queue** | One book per line, sequential fetching, live progress, cancellable; **randomized 2–4s interval** to stay low-profile |
| **Book list import** | Import from txt / csv, or just **drag the file into the window** — four formats auto-detected |
| **Cover art** | Downloaded in the background and cached locally; thumbnails in lists, large cover in details |

### Local Library (SQLite)
- **Snapshot-based storage** — each fetch adds a snapshot instead of overwriting, aligning the same highlight across snapshots by text fingerprint
- **Popularity tracking** — after two fetches you can see *which sentence is gaining traction* and which are newly rising
- **Full-text search** — FTS5 + trigram tokenizer, cross-book search returns in **0.3 ms** (vs 5.2 ms for plain `LIKE`)
- **Instant offline access** — browse everything you've saved with zero network requests
- **Activity log** — search / fetch / export / offline open are all recorded and reviewable

### Processing & Analysis
| Feature | Description |
|---|---|
| **One-click AI organize** | Turn raw quotes into structured notes. **Fully customizable prompt** — no longer limited to built-in templates; the highlights are appended automatically and never get dropped |
| **AI Outline** | Per-chapter **AI key points**, on its own page with browse / copy / export (Markdown / plain text / HTML) — see the "AI Outline" section |
| **Cross-book theme aggregation** | Pick 2–5 books and see *what each of them says about the same question* |
| **Cross-book dedup & merge** | Similarity clustering (character bigram + Jaccard) groups sentences from different books that say the same thing, ranked by consensus |
| **Popularity trend charts** | Hand-drawn line and bar charts — how a single quote's highlight count changes over time |
| **Mind map** | Hand-drawn tree view, exportable as **PNG / SVG**, plus outline export (Markdown / OPML) that **imports directly into XMind** |
| **Watch & push** | Watchlist + scheduled incremental checks; pushes newly trending highlights to **Feishu/Lark** (with signature verification and card messages) |

### Export (9 formats)
Markdown · Plain text · **Word (.docx)** · **EPUB** · **PDF** · HTML · Shareable HTML · CSV · JSON

**Templates are customizable**: font size / line height / include chapters / include numbering / accent color / page size — configured once, applied to six text formats.

> By default only the **content** is exported (no "N people highlighted this"), because the primary use case is feeding an AI. One toggle brings it back.

### Interface
- 🌗 **8 appearances** — 4 accent palettes (Violet Dusk / Fresh Mint / Peach Soda / Deep Ocean) × light/dark, plus **follow system**
- 🌏 **Bilingual UI** — every string switchable between Chinese and English (380+ entries)
- ⌨️ **Command palette** — `Ctrl+K`; low-frequency actions live here instead of cluttering the sidebar
- 🎯 **Focus mode** — `Ctrl+Shift+F` hides the sidebar and top bar
- 🪟 **Optional frameless window** — custom title bar that still **keeps native resize / snap / double-click-maximize**
- 📊 **Sorting**: by popularity or by chapter, switched **in place** in the table — no extra window; exports follow the current order
- 📖 **Jump straight into reading**: one click opens the **actual reader view** (`/web/reader/`, not the summary-only detail page) in your system browser, keeping your sign-in; right-click for the detail page
- ✨ Restrained motion: page fade, staggered card entrance, animated counters, toast slide-in — with a **global off switch**

---

## 🚀 Quick Start

### Option 1: Download (no technical background needed)

Grab `书脉.exe` (~45 MB) from the **[Releases](../../releases/latest)** page and double-click it.

- Single file, **no Python required**, no environment setup at all
- First launch takes ~2 seconds (the program self-extracts)
- Your data and exports are created next to the exe in `data/` and `exports/` — visible and easy to back up
- If Windows warns about an unknown publisher, click "More info" → "Run anyway" (personal open-source projects have no code-signing certificate)

### Option 2: Run from source (to modify code, or on non-Windows)

```bash
# 1. Clone
git clone https://github.com/DylanWu-1024/shumai-bookpulse.git
cd shumai-bookpulse

# 2. Create a virtual environment and install dependencies (PySide6 only)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt    # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 3. Launch the GUI
.venv/Scripts/python.exe src/app_gui.py
```

On Windows you can also double-click **`启动工作台.bat`** (run `setup_env.bat` once first to set up the environment).

### Option 3: CLI only (zero third-party dependencies)

The CLI uses **only the Python standard library** — not even PySide6 is needed:

```bash
python src/weread_hotmarks.py "活着" --top 100 --fmt md
```

```bash
# More usage
python src/weread_hotmarks.py "活着" --all                  # all highlights
python src/weread_hotmarks.py "活着" --fmt html --open      # export HTML and open it
python src/weread_hotmarks.py "活着,围城,一地鸡毛" --batch --fmt md   # batch
python src/weread_hotmarks.py --help                        # all options
```

Sample output (`--fmt md`):

```markdown
# 《活着》· 热门划线

- 作者：余华
- 共 972 条

---

1. [麦田新版自序] 生活是属于每个人自己的感受，不属于任何别人的看法。
2. [自序] 人是为活着本身而活着，而不是为了活着之外的任何事物而活着。
3. ...
```

---

## 🖼️ Screenshots

**Search & download** — candidates show recommendation scores and current readers; results on the right

![Search](预览截图/界面预览-搜索下载.png)

**Insight hub** — cross-book keyword search / theme aggregation / watch & push

![Insight](预览截图/界面预览-洞察台.png)

**Popularity trend** — how a single quote's highlight count evolves over time

![Trend](预览截图/界面预览-热度趋势.png)

**Mind map** — laid out by chapter, exportable to PNG / SVG / OPML

![Mind map](预览截图/界面预览-思维导图.png)

**One-click AI organize** — five LLM providers, streaming output

![AI](预览截图/界面预览-AI整理.png)

**Settings** — 8 appearances, export templates, AI and Feishu configuration

![Settings](预览截图/界面预览-设置页.png)

<details>
<summary>More screenshots (dark mode / English UI / batch queue / library / command palette …)</summary>

| Dark mode | English UI |
|---|---|
| ![Dark](预览截图/界面预览-深色模式.png) | ![English](预览截图/界面预览-英文深色.png) |

| Batch queue | Local library |
|---|---|
| ![Batch](预览截图/界面预览-批量队列.png) | ![Library](预览截图/界面预览-本地书库.png) |

| Command palette (Ctrl+K) | Browse by chapter |
|---|---|
| ![Palette](预览截图/界面预览-命令面板.png) | ![Chapters](预览截图/界面预览-按章节浏览.png) |

</details>

---

## 📤 Export Formats

| Format | Best for |
|---|---|
| **Markdown** | **Feeding an AI** (recommended), or importing into Obsidian / Notion |
| **Plain text** | Universal fallback — pastes anywhere |
| **Word (.docx)** | Assignments, reading reports, needing annotations |
| **EPUB** | Import into WeRead / Kindle / Apple Books as a "notes book" |
| **PDF** | Printing, archiving, fixed layout |
| **HTML** | Open locally and read, with a **built-in copy button** |
| **Shareable HTML** | **Sharing with friends** — mobile-friendly, grouped by chapter, with link previews in chat apps |
| **CSV** | Opens in Excel without mojibake; pivot-table friendly |
| **JSON** | For programs; complete field set |

**Export template** (configurable in Settings, applies to all formats):

| Option | Range |
|---|---|
| Body font size | 12 – 20 px |
| Line height | 1.4 – 2.4 |
| Include chapter names | on / off |
| Include numbering | on / off |
| Heading accent color | any hex color |

---

## 🧱 Project Structure

```
shumai-bookpulse/
├── 启动工作台.bat            ← double-click to open the GUI
├── 一键查热门划线.bat         ← double-click for the CLI version
├── setup_env.bat             ← one-time environment setup
├── build_exe.bat             ← build the executable
├── 使用说明.html             ← illustrated guide for end users (Chinese)
│
├── src/                      ★ all source code
│   ├── app_gui.py               main UI (pages / dialogs / interaction)
│   ├── core.py                  fetching, retries, 9-format rendering & export
│   ├── store.py                 SQLite library + FTS5 full-text index
│   ├── exporters.py             Word / EPUB / print-HTML generation (stdlib only)
│   ├── template.py              HTML templates for web and shareable pages
│   ├── theme.py                 color system and global styles (8 appearances)
│   ├── widgets.py               hand-drawn widgets: charts / mind map / motion / palette
│   ├── mindmap.py               mind map data and outline export
│   ├── merge.py                 cross-book similar-sentence clustering
│   ├── ai.py                    LLM calls (5 providers, streaming)
│   ├── feishu.py                Feishu card push
│   ├── watch.py                 watchlist and incremental checks
│   ├── i18n.py                  Chinese/English strings
│   ├── settings.py              preference persistence
│   ├── make_icon.py             app icon generated purely in code
│   ├── build_exe.py             build script
│   └── weread_hotmarks.py       CLI entry point
│
├── 浏览器版/weread-hotmarks.js  ← the original bookmarklet version (runs in the browser console)
├── docs/                       design docs and logo
├── 预览截图/                    screenshots
├── 成果样例/                    sample exports you can open directly
│
├── data/                     ★ your data (auto-generated, in .gitignore)
└── exports/                  default output folder
```

---

## 🛠️ Technical Choices

**The entire project has exactly one third-party dependency: PySide6.**

That is a deliberate decision, not laziness — this project has to ship as a single file you can hand to someone else. Every extra dependency adds both size and failure modes.

| Need | Common approach | What this project does |
|---|---|---|
| Word generation | python-docx (drags in lxml, +8 MB) | Hand-build **OOXML** (zip + XML) |
| EPUB generation | ebooklib (yet another dependency) | Hand-build **EPUB 3.0** (zip + XHTML + OPF) |
| PDF generation | reportlab (C extension) / fpdf (needs an external CJK font) | Qt's built-in **`QTextDocument` + `QPdfWriter`** |
| Full-text search | Whoosh / jieba segmentation | SQLite **FTS5 + trigram** (searches CJK substrings, no external tokenizer) |
| Charts / mind map | matplotlib / graphviz | **Hand-drawn with QPainter** |
| Icon assets | A pile of png / svg files | **Drawn entirely in code** — no asset files to lose during packaging |

Result: **45 MB** single-file build, **113 MB** onedir build, fastest launch **530 ms**.

**Measured performance** (AMD R7 7735H / 16 GB):

| Operation | Time |
|---|---|
| onedir launch | **530 ms** (single-file: 1816 ms, 3.4× slower) |
| Cross-book full-text search (3000+ records) | **0.3 ms** |
| Cross-book dedup merge (3018 records) | **218 ms** |

---

## ❓ FAQ

<details>
<details>
<summary><b>What is AI Outline, and why does it need a sign-in?</b></summary>

WeRead generates **per-chapter AI key points** for many books (the "AI Outline" feature you see in the app). It is a separate data source from popular highlights, so this project gives it its own page.

Measured (2026-10-02):

- `POST /web/book/outline/check` — chapter structure + which chapters have key points, **no sign-in needed**
- `POST /web/book/outline/inner` — the actual key-point text, **requires sign-in**; returns `HTTP 403` without a Cookie

So Settings has a "WeRead sign-in": just paste the Cookie from your browser. **Only this one feature sends it** — highlight fetching never does. The cookie stays in your local `data/settings.json`.

Also set your expectations: **not every book has an AI outline.** 活着 has none across all 13 chapters; 短线交易秘诀 has key points in 122 of 125 chapters. The app tells you which case you're in.

</details>

<summary><b>Will this get my WeRead account banned?</b></summary>

**Technically the program cannot be linked to your account**, and this is verifiable at the code level:

- It uses `urllib.request` with **no cookie handler at all — not a single cookie is sent**
- Headers contain only `User-Agent` / `Referer` / `Accept`, no identity markers
- GET requests only, against **public read-only endpoints** that need no login
- No pagination loop (a single request retrieves the whole book)

So the server gets no identifying information — the worst case is IP rate-limiting, not a ban.

**Still, be careful**: these are unofficial endpoints, and Tencent's terms of service generally prohibit unauthorized automated access. Please **do not** loop through hundreds of books, do not hammer the API, and do not publicly redistribute fetched content. Keep the default 2–4s randomized interval for batch fetching.

> Also note: the bundled **bookmarklet version** (`浏览器版/weread-hotmarks.js`) uses `credentials: 'include'` and **does send your login state** — higher risk than the desktop app. **Prefer the desktop app.**

</details>

<details>
<summary><b>Why can't I get the actual reader reviews?</b></summary>

The `/web/review/list` endpoint returns empty when not logged in, and `/web/book/info` returns error `-2010 用户不存在` — **reader review text requires an authenticated session**.

This project deliberately **does not implement login** (it would substantially raise risk-control exposure). As a substitute, use **Browse by chapter**: popular highlights within the same chapter *are* the readers voting with their actions — a sentence highlighted repeatedly in one passage is the most genuine signal at that position.

As for recommendation score, rating count, rating tier and current readers — the search endpoint already returns them for free, with zero extra requests.
</details>

<details>
<summary><b>Does it need a proxy / VPN?</b></summary>

No. The program talks directly to WeRead's public endpoints and **does not require any VPN**.

> ⚠️ **If your proxy app (Clash / v2ray, etc.) is closed, this app can get very slow.**
> Windows keeps the proxy configuration around even after the app quits, so following it means
> hitting a dead port and retrying, making everything crawl. WeRead is a domestic site — direct
> connects in a fraction of a second.
>
> **Fix**: Settings → Network → set **Connection** to **Direct (recommended)**, which is the default.
> To verify, click **Network check** on the same card: it times "Direct" against "Follow system proxy"
> and tells you which one is faster.
>
> This setting covers all outbound traffic: WeRead fetching + AI API calls + Feishu push. If you use a
> model like OpenAI that needs a proxy, switch it to "Follow system proxy".

Settings also lets you configure **timeout, retry count and a custom proxy URL**. The fetch layer has exponential backoff built in (0.8 → 1.6 → 3.2 s with jitter) and deliberately does **not** retry 4xx responses.
</details>

<details>
<summary><b>Where is my data stored? How do I migrate?</b></summary>

Everything lives in `data/`:

- `data/hotmarks.db` — SQLite library (books / snapshots / highlights / history / AI notes)
- `data/settings.json` — preferences (**contains API keys, stored locally only**)
- `data/covers/` — cover cache

**To move machines, just copy the whole `data/` folder** — library and history come along. This folder is listed in `.gitignore` and will never be committed by accident.
</details>

<details>
<summary><b>How do I build a standalone exe?</b></summary>

```bash
.venv/Scripts/python.exe -m pip install pyinstaller
.venv/Scripts/python.exe src/build_exe.py both
```

Outputs:
- `dist/WeReadHotmarks.exe` — single file, **easiest to share**
- `dist_fast/BookPulse/` — onedir, **3.4× faster startup**, zip it to share

After changing code you **must rebuild**, otherwise you're shipping the old version.
</details>

---

## ⚠️ Disclaimer

- This is an **unofficial third-party tool**. It is not affiliated with, authorized by, or endorsed by Tencent or WeRead (微信读书) in any way.
- The project reads data through publicly accessible endpoints and is intended **solely for personal study, research and organizing your own reading notes**.
- Do not use it for commercial purposes, large-scale data collection, or anything that violates Tencent's terms of service or applicable law.
- Do not publicly redistribute fetched book content — copyright belongs to the original authors and publishers.
- You assume all risks and responsibilities arising from use of this project. The author is not liable for account issues, data loss, or legal disputes.
- **If you enjoy a book, please buy a legitimate copy and support the author.**

Licensed under MIT. If you believe this project infringes your rights, please open an Issue and it will be addressed promptly.

---

## 🗺️ Roadmap

- [x] Fetching + book metrics + local library
- [x] Nine export formats + customizable templates
- [x] AI organize / cross-book aggregation / cross-book search / dedup merge
- [x] Popularity trends / mind map / watch & push / Feishu integration
- [x] Bilingual UI / 8 appearances / command palette / focus mode
- [ ] **Library backup & restore** (one-click zip export) — top priority; data currently lives on one machine only
- [ ] Long-image export (for sharing to social platforms)
- [ ] Scheduled daily digest push
- [ ] macOS / Linux support

Feature requests are welcome — please open an Issue.

---

## 🤝 Contributing

Issues and PRs are welcome. Before you start, please read the "Project Structure" section and the design docs under `docs/`.

A few project conventions (learned the hard way — written down so you don't repeat them):

1. **`.bat` files must stay pure ASCII** — cmd reads batch files as ANSI, so Chinese comments become mojibake and can break the commands.
2. **Don't move files out of `src/`** — they import each other; `core.app_dir()` is specifically written so `data/` and `exports/` always land in the project root.
3. **Never silently swallow exceptions in hand-drawn widgets** — an exception raised inside a Qt `paintEvent` crashes the whole process with a segfault. This project routes paint exceptions to stderr, which is the key to debugging them.
4. UI strings must be changed in **both** the Chinese and English blocks, and the keys must stay paired.

---

## 📄 License

[MIT License](LICENSE) © 2026 DylanWu

---

<div align="center">

**If this project helped you, a ⭐ Star is the best encouragement.**

[⬆ Back to top](#bookpulse--书脉)

</div>
