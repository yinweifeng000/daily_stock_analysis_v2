# -*- coding: utf-8 -*-
"""
PushPlus 微信推送公共模块（仅标准库，供仓库根目录的 GitHub Actions 脚本共用）

背景
----
深色 iPhone 卡片排版会把 Markdown 放大 2~3 倍（内联样式 + 链接 + 表格标签）。
整篇一次性推送时极易触发 PushPlus ``code=999 发送内容过大，不能超过2万字``，
表现为 Actions 全程绿灯、但微信一条消息都没有。

解决
----
1. 以「最终发送的 HTML 字符数 / 字节数」为准做分段，而不是以 Markdown 字数为准；
2. 按 ``## / ###`` 章节和表格块切分，尽量不把一个因子卡片或一张表拆断；
3. 逐条发送并在标题标注 ``(i/N)``，卡片顶部给出完整报告链接；
4. 单条失败自动重试一次，并把成功/失败明细返回给调用方（便于 Actions 标红）。

用法
----
    from pushplus_html import send_report
    result = send_report(
        title="全球事件与资金扫描 2026-11-05",
        markdown=report,
        token=PUSHPLUS_TOKEN,
        topic=PUSHPLUS_TOPIC,
        detail_url="https://github.com/.../blob/main/global_scan/2026-11-05.md",
    )
    if not result["all_ok"]:
        ...
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.request

PUSHPLUS_API = "https://www.pushplus.plus/send"

# PushPlus 官方上限是 20000 字；留出余量以覆盖标题、转义与服务端统计口径差异
PUSHPLUS_HARD_LIMIT = 20000
PUSHPLUS_SAFE_CHARS = 18000
PUSHPLUS_SAFE_BYTES = 30000
# 分页提示（第 i/N 条 + 完整报告链接）也会占字符，分段时先预留出来
NOTE_RESERVE_CHARS = 400
NOTE_RESERVE_BYTES = 1200


# ---------------------------------------------------------------------------
# Markdown -> iPhone 15 Pro 深色卡片 HTML
# ---------------------------------------------------------------------------
def _escape(text: str) -> str:
    """转义 HTML 特殊字符，避免报告里的 < > & 破坏排版或被服务端判为非法内容。"""
    return _html.escape(text, quote=False)


def _strip_fences(md: str) -> str:
    t = md.strip()
    t = re.sub(r"```[a-zA-Z]*\s*\n(.*?)```", r"\1", t, flags=re.S)
    t = re.sub(r"^\s*```[a-zA-Z]*\s*$", "", t, flags=re.M)
    return t.strip()


def _inline(text: str) -> str:
    """行内 Markdown -> HTML。入参必须先经过 _escape。"""
    # 1) [标题](URL) -> 可点击超链接（原文可点进去）
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: (
            f'<a href="{m.group(2)}" style="color:#4dabf7;text-decoration:none;'
            f'word-break:break-all;">{m.group(1)}</a>'
        ),
        text,
    )

    # 2) 裸 URL -> 超链接。用回调跳过已写入 href="..." 的 URL，避免重复包裹
    def _bare(m: "re.Match") -> str:
        pre, url = m.group(1), m.group(2)
        if pre in ('"', ']', '=', '>'):
            return m.group(0)
        return (pre or "") + (
            f'<a href="{url}" style="color:#4dabf7;text-decoration:none;'
            f'word-break:break-all;">{url}</a>'
        )

    text = re.sub(r'(.)?(https?://[^\s<)"\']+)', _bare, text)

    # 3) 强调 / 行内代码
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#ffffff;">\1</strong>', text)
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#1e2128;padding:1px 4px;border-radius:3px;'
        r'font-size:13px;color:#ff7b72;">\1</code>',
        text,
    )

    # 4) 事件状态着色
    text = text.replace("【已确认】", '<strong style="color:#3fb950;">【已确认】</strong>')
    text = text.replace("【高可信预期】", '<strong style="color:#ffa940;">【高可信预期】</strong>')
    text = text.replace("【单一来源消息】", '<strong style="color:#c9d1d9;">【单一来源消息】</strong>')
    text = text.replace("【市场传闻】", '<strong style="color:#ff7b72;">【市场传闻】</strong>')
    return text


def _render_table(rows: list) -> str:
    if not rows:
        return ""
    header = rows[0]
    body = rows[2:] if len(rows) > 2 else []
    th = "".join(
        f'<th style="border:1px solid #2a2f37;padding:6px 8px;text-align:left;'
        f'background:#1a1d23;color:#e6e8eb;">{c}</th>'
        for c in header
    )
    trs = ""
    for r in body:
        tds = "".join(
            f'<td style="border:1px solid #2a2f37;padding:6px 8px;color:#e6e8eb;">{c}</td>'
            for c in r
        )
        trs += f"<tr>{tds}</tr>"
    return (
        '<table style="border-collapse:collapse;width:100%;font-size:13px;'
        'margin:8px 0;word-break:break-word;color:#e6e8eb;">'
        f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"
    )


def markdown_to_html(md: str, note_html: str = "") -> str:
    """把 Markdown 渲染成 iPhone 15 Pro 友好的深色 HTML 卡片。"""
    md = _strip_fences(md)
    lines = md.splitlines()
    out: list = []
    list_type = None
    list_items: list = []
    table_buf: list = []

    def flush_list():
        nonlocal list_type, list_items
        if list_type and list_items:
            tag = "ul" if list_type == "ul" else "ol"
            lis = "".join(f'<li style="margin:4px 0;">{it}</li>' for it in list_items)
            out.append(f'<{tag} style="margin:6px 0;padding-left:20px;">{lis}</{tag}>')
        list_type, list_items = None, []

    def flush_table():
        nonlocal table_buf
        if table_buf:
            out.append(_render_table(table_buf))
            table_buf = []

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i].rstrip()
        stripped = raw.strip()
        if not stripped:
            flush_list()
            flush_table()
            i += 1
            continue
        # 表格
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                if table_buf:
                    table_buf.append(cells)
            else:
                flush_list()
                table_buf.append([_inline(_escape(c)) for c in cells])
            i += 1
            continue
        flush_table()
        # 分隔线
        if re.match(r"^\s*([-*_])\1{2,}\s*$", raw):
            flush_list()
            out.append('<hr style="border:none;border-top:1px solid #2a2f37;margin:12px 0;">')
            i += 1
            continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", raw)
        if m:
            flush_list()
            level = len(m.group(1))
            txt = _inline(_escape(m.group(2)))
            if level == 1:
                out.append(
                    f'<h1 style="font-size:20px;color:#ffa940;font-weight:700;'
                    f'border-bottom:2px solid #ffa940;padding-bottom:6px;'
                    f'margin:18px 0 10px;">{txt}</h1>'
                )
            elif level == 2:
                out.append(
                    f'<h2 style="font-size:17px;color:#5cc8ff;font-weight:700;'
                    f'border-left:4px solid #ffa940;padding-left:8px;'
                    f'margin:16px 0 8px;">{txt}</h2>'
                )
            elif level == 3:
                out.append(
                    f'<h3 style="font-size:15.5px;color:#ffa940;font-weight:700;'
                    f'margin:12px 0 6px;">{txt}</h3>'
                )
            else:
                out.append(
                    f'<h4 style="font-size:14.5px;color:#c9d1d9;font-weight:700;'
                    f'margin:10px 0 4px;">{txt}</h4>'
                )
            i += 1
            continue
        # 引用
        if raw.lstrip().startswith(">"):
            flush_list()
            out.append(
                f'<div style="border-left:3px solid #3a4150;padding:4px 10px;'
                f'color:#9aa3ad;background:rgba(255,255,255,0.04);margin:6px 0;">'
                f'{_inline(_escape(raw.lstrip()[1:].strip()))}</div>'
            )
            i += 1
            continue
        # 代码块
        if stripped.startswith("```"):
            flush_list()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = _html.escape("\n".join(buf), quote=False)
            out.append(
                f'<pre style="background:#0c0e12;border-radius:6px;padding:10px;'
                f'overflow-x:auto;font-size:12.5px;line-height:1.5;color:#e6e8eb;'
                f'white-space:pre-wrap;word-break:break-word;"><code>{code}</code></pre>'
            )
            continue
        # 列表
        lm = re.match(r"^\s*[-*]\s+(.*)$", raw)
        olm = re.match(r"^\s*\d+\.\s+(.*)$", raw)
        if lm:
            if list_type != "ul":
                flush_list()
                list_type = "ul"
            list_items.append(_inline(_escape(lm.group(1))))
            i += 1
            continue
        if olm:
            if list_type != "ol":
                flush_list()
                list_type = "ol"
            list_items.append(_inline(_escape(olm.group(1))))
            i += 1
            continue
        # 段落
        flush_list()
        out.append(f'<p style="margin:6px 0;">{_inline(_escape(raw))}</p>')
        i += 1

    flush_list()
    flush_table()
    body = "".join(out)
    return (
        '<div style="max-width:100%;background:#111418;color:#e6e8eb;'
        'font-family:-apple-system,BlinkMacSystemFont,'
        '&quot;PingFang SC&quot;,&quot;Helvetica Neue&quot;,Arial,sans-serif;'
        'font-size:15px;line-height:1.75;word-break:break-word;'
        'padding:14px 14px 18px;border-radius:14px;">'
        f"{note_html}{body}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# 按「最终 HTML 长度」分段
# ---------------------------------------------------------------------------
def _split_sections(md: str) -> list:
    """以 ## / ### 为边界切成逻辑段（保留标题行）。"""
    segs, cur = [], []
    for line in md.splitlines():
        if re.match(r"^#{2,3}\s+", line) and cur:
            segs.append("\n".join(cur).strip())
            cur = [line]
        else:
            cur.append(line)
    if cur:
        segs.append("\n".join(cur).strip())
    return [s for s in segs if s]


def _split_line_blocks(section: str) -> list:
    """段内再按行切块；连续表格行合并成一块，避免把表头和表体拆到两条消息。"""
    lines = section.splitlines()
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append("\n".join(lines[i:j]))
            i = j
        else:
            blocks.append(lines[i])
            i += 1
    return blocks


def _fits(md: str, max_chars: int, max_bytes: int) -> bool:
    html = markdown_to_html(md)
    return len(html) <= max_chars and len(html.encode("utf-8")) <= max_bytes


def split_for_push(md: str, max_chars: int = PUSHPLUS_SAFE_CHARS,
                   max_bytes: int = PUSHPLUS_SAFE_BYTES) -> list:
    """把 Markdown 切成若干段，保证每段渲染成 HTML 后都在 PushPlus 限制内。"""
    md = _strip_fences(md)
    # 给页眉（页码 + 完整报告链接）预留额度，避免加上页眉后刚好越线
    max_chars = max(1000, max_chars - NOTE_RESERVE_CHARS)
    max_bytes = max(2000, max_bytes - NOTE_RESERVE_BYTES)
    if _fits(md, max_chars, max_bytes):
        return [md]

    chunks, buf = [], ""
    for section in _split_sections(md):
        candidate = (buf + "\n\n" + section) if buf else section
        if _fits(candidate, max_chars, max_bytes):
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if _fits(section, max_chars, max_bytes):
            buf = section
            continue
        # 单个章节仍然超长：按行块贪心
        sub = ""
        for block in _split_line_blocks(section):
            cand = (sub + "\n" + block) if sub else block
            if _fits(cand, max_chars, max_bytes):
                sub = cand
            else:
                if sub:
                    chunks.append(sub)
                if _fits(block, max_chars, max_bytes):
                    sub = block
                else:
                    # 极端情况：单行就超标，按字符硬切（HTML 仍需完整闭合）
                    sub = block[:max(1, max_chars // 3)]
        if sub:
            buf = sub
    if buf:
        chunks.append(buf)
    return chunks or [md[:max(1, max_chars // 3)]]


# ---------------------------------------------------------------------------
# 发送
# ---------------------------------------------------------------------------
def _note_html(page: str, detail_url: str) -> str:
    parts = []
    if page:
        parts.append(page)
    if detail_url:
        parts.append(
            f'<a href="{_html.escape(detail_url, quote=True)}" '
            f'style="color:#4dabf7;text-decoration:none;">点击查看完整报告</a>'
        )
    if not parts:
        return ""
    return (
        '<div style="color:#9aa3ad;font-size:13px;margin:0 0 10px;'
        'padding-bottom:8px;border-bottom:1px solid #2a2f37;">'
        + " · ".join(parts)
        + "</div>"
    )


def _post(payload: dict) -> str:
    """返回 '成功' 或 '失败(...)'。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PUSHPLUS_API, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    if obj.get("code") == 200:
        return "成功"
    return f"失败(code={obj.get('code')}): {obj.get('data') or obj.get('msg')}"


def send_report(title: str, markdown: str, token: str, topic: str = "",
                detail_url: str = "", *, max_chars: int = PUSHPLUS_SAFE_CHARS,
                max_bytes: int = PUSHPLUS_SAFE_BYTES, log=print) -> dict:
    """分段推送整篇报告；返回 total / success / all_ok / details。"""
    if not token:
        log("[pushplus] 跳过（未配置 PUSHPLUS_TOKEN）")
        return {"total": 0, "success": 0, "all_ok": False, "details": ["跳过：未配置 PUSHPLUS_TOKEN"]}

    chunks = split_for_push(markdown, max_chars, max_bytes)
    total = len(chunks)
    details, success = [], 0
    log(f"[pushplus] 报告分 {total} 条推送（Markdown {len(markdown)} 字，单条 HTML 上限 {max_chars} 字符）")

    for idx, chunk in enumerate(chunks, 1):
        page = f"第 {idx}/{total} 条" if total > 1 else ""
        html_content = markdown_to_html(chunk, _note_html(page, detail_url))
        msg_title = f"{title} ({idx}/{total})" if total > 1 else title
        payload = {
            "token": token,
            "title": msg_title,
            "content": html_content,
            "template": "html",
        }
        if topic:
            payload["topic"] = topic

        status = ""
        for attempt in (1, 2):
            try:
                status = _post(payload)
            except Exception as exc:  # noqa: BLE001
                status = f"异常: {exc}"
            if status == "成功":
                break
            if attempt == 1:
                log(f"[pushplus] {idx}/{total} 第一次发送未成功（{status}），3 秒后重试")
                time.sleep(3)

        ok = status == "成功"
        if ok:
            success += 1
        detail = f"{idx}/{total} {msg_title}：{status}（HTML {len(html_content)} 字符）"
        details.append(detail)
        log(f"[pushplus] {detail}")
        if idx < total:
            time.sleep(1.2)  # PushPlus 频率限制，避免连续发送被拦

    return {
        "total": total,
        "success": success,
        "all_ok": success == total and total > 0,
        "details": details,
    }
