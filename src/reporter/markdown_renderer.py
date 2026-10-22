"""
Markdown 报告生成 - 简洁版：AI 总结 + 来源列表
"""
from datetime import datetime
from typing import List

import pytz

from src.crawler.feed_fetcher import RawContent

CST = pytz.timezone("Asia/Shanghai")


def render_markdown(
    report_date: str,
    total_items: int,
    relevant_items: int,
    summary: str,
    relevant_contents: List[RawContent],
    cost_tracker: dict,
    elapsed_seconds: float,
) -> str:
    lines = []
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    lines.append(f"# A股每日分析报告 - {report_date}")
    lines.append("")
    lines.append(f"> 生成时间：{now} | 抓取：{total_items}条 | "
                 f"相关：{relevant_items}条 | "
                 f"耗时：{elapsed_seconds:.0f}s | "
                 f"API费用：${cost_tracker.get('cost_usd', 0):.4f}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append(summary)
    lines.append("")
    lines.append("---")
    lines.append("")

    # 来源列表
    lines.append(f"## 原始来源（共 {len(relevant_contents)} 条）")
    lines.append("")
    if relevant_contents:
        for c in relevant_contents:
            title = c.title or "(想法)"
            ctype = {"answer": "回答", "article": "文章", "pin": "想法"}.get(
                c.content_type, c.content_type)
            lines.append(f"- [{ctype}] [{title}]({c.url}) - **{c.author}** · {c.time_display}")
    else:
        lines.append("*今日无相关财经内容*")
    lines.append("")

    lines.append("---")
    lines.append("*本报告由AI自动生成，仅供参考，不构成投资建议。*")

    return "\n".join(lines)
