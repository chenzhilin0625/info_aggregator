import re
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from src.crawler.feed_fetcher import RawContent


class HtmlRenderer:
    def __init__(self, template_dir: str = "templates"):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html"]),
        )

    def render(
        self,
        report_date: str,
        total_items: int,
        relevant_items: int,
        summary: str,
        relevant_contents: List[RawContent],
        cost_tracker: dict,
        elapsed_seconds: float,
    ) -> str:
        template = self.env.get_template("report.html.j2")

        summary_html = _convert_markdown_sections(summary)

        ctype_map = {"answer": "回答", "article": "文章", "pin": "想法"}
        sources = []
        for idx, c in enumerate(relevant_contents, 1):
            sources.append({
                "num": idx,
                "title": c.title or "(想法)",
                "url": c.url,
                "author": c.author or "匿名",
                "time": c.time_display,
                "type": ctype_map.get(c.content_type, c.content_type),
            })

        return template.render(
            report_date=report_date,
            total_items=total_items,
            relevant_items=relevant_items,
            summary_html=summary_html,
            sources=sources,
            elapsed_seconds=int(elapsed_seconds),
            api_cost=f"{cost_tracker.get('cost_usd', 0):.4f}",
        )


def _convert_markdown_sections(md: str) -> str:
    """将 markdown 逐篇总结转为 HTML 卡片"""
    sections = re.split(r"\n(?=## )", md)

    if len(sections) <= 1:
        return _md_to_html(sections[0] if sections else md)

    html_parts = []
    card_idx = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        title_match = re.match(r"^##\s+(.+)$", section, re.MULTILINE)
        if not title_match:
            # 非标题段落（无内容提示等），作为普通文本
            html_parts.append(f'<div class="summary-card">{_md_to_html(section)}</div>')
            continue

        card_idx += 1
        title = title_match.group(1)
        body = section[title_match.end():].strip()

        # 解析：**作者名** · 类型 · [原文链接](url)
        author_html = ""
        author_match = re.match(r"^\*\*(.+?)\*\*\s*·\s*(.+?)\s*·\s*\[原文链接\]\((.+?)\)", body)
        if author_match:
            author_name = author_match.group(1)
            ctype = author_match.group(2).strip()
            url = author_match.group(3)
            badge_class = {"回答": "badge-answer", "文章": "badge-article", "想法": "badge-pin"}.get(ctype, "badge-article")
            author_html = (
                f'<div class="article-meta">'
                f'<span class="type-badge {badge_class}">{ctype}</span>'
                f' <span style="font-weight:600;color:#555;">{author_name}</span>'
                f' <a href="{url}" style="font-size:12px;color:#999;margin-left:6px;">查看原文 →</a>'
                f'</div>'
            )
            body = body[author_match.end():].strip()

        # 图标
        icon = "📄"; icon_class = "icon-article"
        if "💬" in title:
            icon = "💬"; icon_class = "icon-answer"
        elif "💡" in title:
            icon = "💡"; icon_class = "icon-pin"

        clean_title = title
        for e in ["💬 ", "📄 ", "💡 "]:
            clean_title = clean_title.replace(e, "")

        html_parts.append(f'''
<div class="article-card" id="item-{card_idx}">
  <div class="article-header">
    <div class="article-icon {icon_class}">{icon}</div>
    <div class="article-info">
      <div class="article-title">{clean_title}</div>
      {author_html}
    </div>
  </div>
  <div class="article-body">
    {_md_to_html(body)}
  </div>
</div>''')

    return "\n".join(html_parts)


def _md_to_html(text: str) -> str:
    """简单 markdown → HTML"""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"(<li>.*?</li>\n?)+", r"<ul>\g<0></ul>", text)
    text = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", text, flags=re.MULTILINE)

    paragraphs = text.split("\n\n")
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if re.match(r"^<(ul|blockquote|h3|li)", p):
            result.append(p)
        else:
            result.append(f"<p>{p.replace(chr(10), '<br>')}</p>")
    return "\n".join(result)
