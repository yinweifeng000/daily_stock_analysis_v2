# -*- coding: utf-8 -*-
"""
PushPlus 发送提醒服务

职责：
1. 通过 PushPlus API 发送 PushPlus 消息
"""
import logging
import re
import html as _html
import time
from typing import Optional
from datetime import datetime
import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)

# PushPlus 内容上限是 2 万「字」（字符），必须以「渲染后的 HTML」为准判断，
# 否则深色卡片的内联样式会把内容放大 2~3 倍，导致 code=999 被拒但 Actions 显示成功。
PUSHPLUS_SAFE_CHARS = 18000
PUSHPLUS_SAFE_BYTES = 30000


# ---------------------------------------------------------------------------
# iPhone 15 Pro 友好排版：Markdown -> HTML（PushPlus 以 html 模板渲染）
# ---------------------------------------------------------------------------
def _escape_md_text(text: str) -> str:
    """转义 HTML 特殊字符，避免报告里的 < > & 破坏排版。"""
    return _html.escape(text, quote=False)


def _inline_to_html(text: str) -> str:
    """把行内 Markdown（已转义）转成 iPhone 友好的 HTML。"""
    # 链接 [文字](url)
    def _link(m: "re.Match") -> str:
        title = m.group(1)
        url = m.group(2)
        return f'<a href="{url}" style="color:#4dabf7;text-decoration:none;border-bottom:1px solid #4dabf7;">{title}</a>'

    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _link, text)
    # 裸链接（跳过已处于 href=" 之后的，避免重复包裹）
    s = re.sub(
        r'(?<!href=")(?<!">)(https?://[^\s<]+)',
        r'<a href="\1" style="color:#4dabf7;text-decoration:none;border-bottom:1px solid #4dabf7;">\1</a>',
        s,
    )
    # 加粗
    s = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#ffffff;">\1</strong>', s)
    # 行内代码
    s = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#1e2128;padding:1px 4px;border-radius:3px;'
        r'font-size:13px;color:#ff7b72;">\1</code>',
        s,
    )
    return s


def _strip_code_fence(md: str) -> str:
    md = md.strip()
    if md.startswith("```"):
        lines = md.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        md = "\n".join(lines)
    return md


def _render_table(rows: list) -> str:
    """rows[0]=表头, rows[1]=分隔行(忽略), rows[2:]=数据行。"""
    if not rows:
        return ""
    header = rows[0]
    body = rows[2:] if len(rows) > 2 else []
    th = "".join(
        f'<th style="border:1px solid #2a2f37;padding:6px 8px;text-align:left;'
        f'background:#1a1d23;color:#e6e8eb;font-weight:600;">{c}</th>'
        for c in header
    )
    trs = ""
    for r in body:
        tds = "".join(
            f'<td style="border:1px solid #2a2f37;padding:6px 8px;color:#e6e8eb;">{c}</td>' for c in r
        )
        trs += f"<tr>{tds}</tr>"
    return (
        '<table style="border-collapse:collapse;width:100%;font-size:13px;'
        'margin:8px 0;word-break:break-word;color:#e6e8eb;">'
        f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"
    )


def markdown_to_iphone_html(md: str) -> str:
    """将 Markdown 报告渲染为 iPhone 15 Pro 友好的 HTML（PushPlus html 模板）。"""
    md = _strip_code_fence(md)
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
        # 表格行
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                if not table_buf:
                    i += 1
                    continue
                table_buf.append(cells)
            else:
                flush_list()
                table_buf.append(cells)
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
            txt = _inline_to_html(_escape_md_text(m.group(2)))
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
                f'{_inline_to_html(_escape_md_text(raw.lstrip()[1:].strip()))}</div>'
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
            i += 1  # 跳过收尾 ```
            code = _html.escape("\n".join(buf), quote=False)
            out.append(
                f'<pre style="background:#0c0e12;border-radius:6px;padding:10px;'
                f'overflow-x:auto;font-size:12.5px;line-height:1.5;color:#e6e8eb;'
                f'white-space:pre-wrap;word-break:break-word;"><code>{code}</code></pre>'
            )
            continue
        # 无序列表
        lm = re.match(r"^\s*[-*]\s+(.*)$", raw)
        olm = re.match(r"^\s*\d+\.\s+(.*)$", raw)
        if lm:
            if list_type != "ul":
                flush_list()
                list_type = "ul"
            list_items.append(_inline_to_html(_escape_md_text(lm.group(1))))
            i += 1
            continue
        if olm:
            if list_type != "ol":
                flush_list()
                list_type = "ol"
            list_items.append(_inline_to_html(_escape_md_text(olm.group(1))))
            i += 1
            continue
        # 段落
        flush_list()
        out.append(f'<p style="margin:6px 0;">{_inline_to_html(_escape_md_text(raw))}</p>')
        i += 1

    flush_list()
    flush_table()
    body = "".join(out)
    wrapper = (
        '<div style="max-width:100%;background:#111418;color:#e6e8eb;'
        'font-family:-apple-system,BlinkMacSystemFont,'
        '&quot;PingFang SC&quot;,&quot;Helvetica Neue&quot;,Arial,sans-serif;'
        'font-size:15px;line-height:1.75;word-break:break-word;'
        'padding:14px 14px 18px;border-radius:14px;">'
        f"{body}"
        "</div>"
    )
    return wrapper


def _safe_markdown_to_html(content: str) -> str:
    """把 Markdown 渲染成 iPhone 友好 HTML；失败则原样返回（退回 markdown）。"""
    try:
        return markdown_to_iphone_html(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PushPlus iPhone HTML 渲染失败，回退为原文: %s", exc)
        return content


def _blocks(md: str) -> list:
    """按行切块；连续表格行合并成一块，避免表头和表体被拆到两条消息里。"""
    lines = md.splitlines()
    result, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            result.append("\n".join(lines[i:j]))
            i = j
        else:
            result.append(lines[i])
            i += 1
    return result


def _chunk_by_rendered_length(md: str, max_chars: int = PUSHPLUS_SAFE_CHARS) -> list:
    """按「渲染后 HTML 字符数」切分 Markdown，保证每一批都在 PushPlus 限制内。"""
    if len(_safe_markdown_to_html(md)) <= max_chars:
        return [md]
    chunks, buf = [], ""
    for block in _blocks(md):
        candidate = (buf + "\n" + block) if buf else block
        if len(_safe_markdown_to_html(candidate)) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
        if len(_safe_markdown_to_html(block)) <= max_chars:
            buf = block
        else:
            buf = block[:max(1, max_chars // 2)]  # 极端情况：单行就超长，硬切
    if buf:
        chunks.append(buf)
    return chunks or [md[:max(1, max_chars // 2)]]


class PushplusSender:
    
    def __init__(self, config: Config):
        """
        初始化 PushPlus 配置

        Args:
            config: 配置对象
        """
        self._pushplus_token = getattr(config, 'pushplus_token', None)
        self._pushplus_topic = getattr(config, 'pushplus_topic', None)
        self._pushplus_max_bytes = getattr(config, 'pushplus_max_bytes', 20000)
        
    def send_to_pushplus(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 PushPlus

        PushPlus API 格式：
        POST http://www.pushplus.plus/send
        {
            "token": "用户令牌",
            "title": "消息标题",
            "content": "消息内容",
            "template": "html/txt/json/markdown"
        }

        PushPlus 特点：
        - 国内推送服务，免费额度充足
        - 支持微信公众号推送
        - 支持多种消息格式

        Args:
            content: 消息内容（Markdown 格式）
            title: 消息标题（可选）

        Returns:
            是否发送成功
        """
        if not self._pushplus_token:
            logger.warning("PushPlus Token 未配置，跳过推送")
            return False

        api_url = "http://www.pushplus.plus/send"

        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        sanitized_content = strip_hidden_markdown_metadata(content).strip()

        try:
            rendered = _safe_markdown_to_html(sanitized_content)
            rendered_bytes = len(rendered.encode('utf-8'))
            if (len(rendered) > PUSHPLUS_SAFE_CHARS
                    or rendered_bytes > PUSHPLUS_SAFE_BYTES):
                logger.info(
                    "PushPlus 渲染后内容超长(%s字符/%s字节)，将分批发送",
                    len(rendered), rendered_bytes,
                )
                return self._send_pushplus_chunked(
                    api_url, sanitized_content, title, PUSHPLUS_SAFE_CHARS,
                )

            return self._send_pushplus_message(
                api_url, sanitized_content, title,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            logger.error(f"发送 PushPlus 消息失败: {e}")
            return False

    def _send_pushplus_message(
        self,
        api_url: str,
        content: str,
        title: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        html_content = _safe_markdown_to_html(content)
        if len(html_content) > 20000:
            logger.warning(
                "PushPlus 单条 HTML 达 %s 字符，超过 2 万字上限，可能被服务端拒绝",
                len(html_content),
            )
        payload = {
            "token": self._pushplus_token,
            "title": title,
            "content": html_content,
            "template": "html",
        }

        if self._pushplus_topic:
            payload["topic"] = self._pushplus_topic

        response = requests.post(api_url, json=payload, timeout=timeout_seconds or 10)

        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 200:
                logger.info("PushPlus 消息发送成功")
                return True

            error_msg = result.get('msg', '未知错误')
            logger.error(f"PushPlus 返回错误: {error_msg}")
            return False

        logger.error(f"PushPlus 请求失败: HTTP {response.status_code}")
        return False

    def _send_pushplus_chunked(self, api_url: str, content: str, title: str,
                               max_chars: int = PUSHPLUS_SAFE_CHARS) -> bool:
        """分批发送长 PushPlus 消息。

        注意：这里必须传「原始 Markdown」给 _send_pushplus_message，由它渲染一次。
        旧实现先转 HTML 再传入，会被二次渲染并转义成乱码，且长度翻倍导致 code=999。
        """
        chunks = _chunk_by_rendered_length(content, max(1000, max_chars - 400))
        total_chunks = len(chunks)
        success_count = 0

        logger.info(f"PushPlus 分批发送：共 {total_chunks} 批（按渲染后 HTML 长度切分）")

        for i, chunk in enumerate(chunks):
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            if self._send_pushplus_message(api_url, chunk, chunk_title):
                success_count += 1
                logger.info(f"PushPlus 第 {i+1}/{total_chunks} 批发送成功")
            else:
                logger.error(f"PushPlus 第 {i+1}/{total_chunks} 批发送失败")

            if i < total_chunks - 1:
                time.sleep(1.2)  # PushPlus 实名用户 1 分钟 5 条的频率限制

        return success_count == total_chunks
