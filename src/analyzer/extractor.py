"""
第二阶段：逐篇总结（每篇用同一个 prompt，然后合并为最终报告）
"""
import logging
import re

from src.analyzer.deepseek_client import DeepSeekClient
from src.crawler.feed_fetcher import RawContent

logger = logging.getLogger("zhihu_analyst")

SUMMARIZE_SYSTEM = "你是一个资深的投资研究助手，请总结以下内容，字数在1000字以内。"

# AI 回复中常见的元文本前缀，需要清理
_META_PREFIXES = [
    r"好的[，,].*?总结[：:]\s*",
    r"以下是.*?总结[：:]\s*",
    r"根据您提供的.*?[，,]\s*",
    r"以下是对.*?的总结[，,].*?(?:字[数数]?控制.{0,10})?[：:]\s*",
    r"基于资深投资研究助手.*?[：:]\s*",
    r"好的[，,].*?以下是对.*?的总结[：:]\s*",
    r"\*\*总结\*\*[：:]\s*",
    r"\*\*文章总结[：:].*?\*\*\s*",
    r"\*\*核心观点[：:]\*\*\s*",
]


def _clean_summary(text: str) -> str:
    """清理 AI 回复中的元文本前缀"""
    for pattern in _META_PREFIXES:
        text = re.sub(r"^" + pattern, "", text.strip(), flags=re.IGNORECASE)
    return text.strip()


class ContentSummarizer:
    """内容总结器：逐篇总结，然后合并"""

    def __init__(self, client: DeepSeekClient):
        self.client = client

    def summarize(self, contents: list[RawContent]) -> str:
        if not contents:
            return "今日无相关财经内容。"

        summaries = []
        ctype_map = {"answer": "回答", "article": "文章", "pin": "想法"}
        type_icon = {"回答": "💬", "文章": "📄", "想法": "💡"}
        total = len(contents)

        for i, c in enumerate(contents, 1):
            ctype = ctype_map.get(c.content_type, c.content_type)
            icon = type_icon.get(ctype, "📌")
            title = c.title or "(无标题)"
            logger.info(f"总结 {i}/{total}: [{ctype}] {title[:30]} by {c.author}")

            user_prompt = (
                f"类型：{ctype}\n"
                f"作者：{c.author}\n"
                f"标题：{title}\n\n"
                f"{c.body_truncated}"
            )

            try:
                result = self.client.complete(
                    system=SUMMARIZE_SYSTEM,
                    user=user_prompt,
                    model=self.client.synthesize_model,
                    max_tokens=1024,
                )
                result = _clean_summary(result)
            except Exception as e:
                logger.error(f"总结失败 [{c.content_id}]: {e}")
                result = f"*（总结失败）*"

            summaries.append({
                "index": i,
                "icon": icon,
                "type": ctype,
                "title": title,
                "author": c.author,
                "url": c.url,
                "summary": result,
            })

        # 合并为最终报告
        lines = []
        for s in summaries:
            lines.append(f"## {s['icon']} {s['title']}")
            lines.append("")
            lines.append(f"**{s['author']}** · {s['type']} · [原文链接]({s['url']})")
            lines.append("")
            lines.append(s["summary"])
            lines.append("")
            lines.append("---")
            lines.append("")

        report = "\n".join(lines)
        logger.info(f"逐篇总结完成：{len(summaries)} 篇")
        return report
