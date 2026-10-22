"""
第三阶段：按行业板块汇总观点 + 生成每日总览

流程：
  1. 按板块分组所有凝练后的观点
  2. 对每个有数据的板块，整合各方观点（保留作者原意）
  3. 生成一个大的每日总结，按行业板块分点
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict

import pytz

from src.analyzer.deepseek_client import DeepSeekClient
from src.analyzer.extractor import CondensedContent

logger = logging.getLogger("zhihu_analyst")
CST = pytz.timezone("Asia/Shanghai")

# ── 缩写/黑话解码 ──
DECODE_SYSTEM = """你是A股市场术语专家。识别以下内容中的缩写、黑话、谜语或行业暗语，将其解码。
常见示例：汪汪队=银行板块/金融股, 狗庄=操纵股价的庄家, 韭菜=散户, 抄底/逃顶, YYDS=永远的神,
DS=DeepSeek/深度求索, 渣男=券商板块, 三傻=银行保险地产, 吃药喝酒=医药白酒,
丐帮=中概互联, 煤飞色舞=煤炭有色行情, 电老虎=电力股, 渣男券=券商, 铁公鸡=高分红不涨,
打新=新股申购, ST=特别处理, 北交=北交所, 科创=科创板, 双创=科创+创业, ETF=交易型开放式指数基金,
宁王=宁德时代, 迪王=比亚迪, 茅王=贵州茅台, 海王=中远海控, 药茅=药明康德,
猪茅=牧原股份, 券茅=东方财富, 锂王=赣锋锂业/天齐锂业, 光茅=隆基绿能,
H股=港股, 中概=中概股, 大A=A股, 缅A=戏称A股, 大霄=李大霄, 但总=但斌,
两融=融资融券, 北向=北向资金, 南下=南向资金, 量化=量化交易,
T+0/T+1=交易结算规则, IPO=新股上市, 定增=定向增发, 解禁=限售股解禁,
蓝筹=大盘蓝筹股, 白马=白马股, 黑马=黑马股, 妖股=异常波动个股.
请输出原文中出现的缩写/谜语及其解码，JSON数组格式：[{"term": "原文", "meaning": "含义"}]"""

SYSTEM_DATE_TEMPLATE = """你是专业的财经信息汇总研究员。今日日期：{date}（北京时间）。

你的任务是将各方作者的观点按行业板块整合，进行总结方便投资者参考。
注意：
- 保留作者原文的关键表述
- 如果不同作者对同一话题有不同看法，都列出来

严格输出JSON，不含任何解释或代码块标记。"""


@dataclass
class SectorDigest:
    """单个板块的每日观点汇总"""
    sector: str = ""
    has_data: bool = False
    discussion_heat: str = "低"          # 高/中/低
    key_themes: List[str] = field(default_factory=list)
    author_viewpoints: List[dict] = field(default_factory=list)
    mentioned_stocks: List[str] = field(default_factory=list)
    sector_overview: str = ""            # 该板块今日讨论的一句话概括

    @classmethod
    def from_json(cls, raw_json: str, sector: str) -> "SectorDigest":
        try:
            cleaned = re.sub(r"```[a-z]*\n?", "", raw_json).strip()
            data = json.loads(cleaned)
            return cls(
                sector=sector,
                has_data=True,
                discussion_heat=data.get("discussion_heat", "低"),
                key_themes=data.get("key_themes", []),
                author_viewpoints=data.get("author_viewpoints", []),
                mentioned_stocks=data.get("mentioned_stocks", []),
                sector_overview=data.get("sector_overview", ""),
            )
        except Exception as e:
            logger.warning(f"板块汇总解析失败 [{sector}]: {e}")
            return cls(sector=sector, has_data=True, discussion_heat="低")


@dataclass
class DailyDigest:
    """每日总览"""
    overview: str = ""                          # 今日市场总览
    hot_topics: List[str] = field(default_factory=list)   # 今日最热话题
    summary_by_sector: List[dict] = field(default_factory=list)  # [{sector, one_liner}]

    @classmethod
    def from_json(cls, raw_json: str) -> "DailyDigest":
        try:
            cleaned = re.sub(r"```[a-z]*\n?", "", raw_json).strip()
            data = json.loads(cleaned)
            return cls(
                overview=data.get("overview", ""),
                hot_topics=data.get("hot_topics", []),
                summary_by_sector=data.get("summary_by_sector", []),
            )
        except Exception as e:
            logger.warning(f"每日总览解析失败: {e}")
            return cls(overview="今日分析完成")


def group_by_sector(
    condensed_list: List[CondensedContent],
    sector_configs: List[dict]
) -> Dict[str, List[CondensedContent]]:
    """按板块分组凝练后的内容"""
    sector_names = [s["name"] for s in sector_configs]
    groups: Dict[str, List[CondensedContent]] = {name: [] for name in sector_names}

    for cc in condensed_list:
        if cc.parse_error:
            continue
        for sector in cc.sectors:
            if sector in groups:
                groups[sector].append(cc)

    return groups


class Digester:
    """每日汇总器：按板块整合观点，生成总览"""

    def __init__(self, client: DeepSeekClient, cfg: dict = None):
        self.client = client

    # ── 缩写解码 ──

    def decode_abbreviations(self, text: str) -> List[dict]:
        """识别一段文本中的A股缩写、黑话、谜语"""
        if not text or len(text) < 20:
            return []
        try:
            raw = self.client.complete(
                system=DECODE_SYSTEM,
                user=f"请识别以下内容中的缩写/黑话/谜语：\n\n{text[:1500]}",
                model=self.client.extract_model,
                max_tokens=300,
            )
            cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()
            return json.loads(cleaned)
        except Exception as e:
            logger.debug(f"缩写解码失败: {e}")
            return []

    # ── 解码所有内容的缩写 ──

    def decode_all(self, condensed_list: List[CondensedContent]) -> Dict[str, List[dict]]:
        """解码所有内容的缩写，返回 {content_id: [abbrs]}"""
        result = {}
        for cc in condensed_list:
            if cc.parse_error:
                continue
            abbrs = self.decode_abbreviations(cc.source.body)
            if abbrs:
                result[cc.source.content_id] = abbrs
        return result

    # ── 按板块汇总观点 ──

    def digest_sector(
        self, sector: str, condensed_list: List[CondensedContent]
    ) -> SectorDigest:
        """对单个板块的所有讨论进行观点整合"""
        if not condensed_list:
            return SectorDigest(sector=sector)

        # 构建输入：列出每位作者的核心观点
        items = []
        for cc in condensed_list:
            for vp in cc.viewpoints:
                items.append({
                    "author": cc.author,
                    "url": cc.url,
                    "title": cc.title,
                    "topic": vp.topic,
                    "opinion": vp.opinion,
                    "evidence": vp.evidence,
                    "stance_note": vp.stance_note,
                })

        if not items:
            return SectorDigest(sector=sector, has_data=True)

        # 组装 prompt
        items_text = "\n".join(
            f"- [{it['author']}]《{it['title'][:40]}》\n"
            f"  话题：{it['topic']}\n"
            f"  观点：{it['opinion']}\n"
            f"  论据：{it['evidence']}\n"
            f"  倾向：{it['stance_note']}"
            for it in items
        )

        today = datetime.now(CST).strftime("%Y年%m月%d日")
        user = f"""以下是今日关于【{sector}】板块的所有讨论（共 {len(items)} 条观点）。请整合各方观点，忠实呈现不同作者的看法。

{items_text}

请输出以下JSON：
{{
  "discussion_heat": "高/中/低",
  "key_themes": ["核心讨论主题（最多5个）"],
  "sector_overview": "该板块今日讨论的一句话概括（30字内）",
  "author_viewpoints": [
    {{
      "author": "作者名",
      "url": "原文链接",
      "theme": "讨论主题",
      "viewpoint": "作者具体观点（保留原意和关键表述）"
    }}
  ],
  "mentioned_stocks": ["明确提及的A股或港股相关标的（最多10个）"]
}}

要点：
- author_viewpoints 中每个作者至少一条，保留他们的核心观点
- 如果同一主题被多位作者讨论，可以将它们放在相近位置
- mentioned_stocks 只列出明确被讨论到的个股/ETF，不要编造"""

        try:
            raw = self.client.complete(
                system=SYSTEM_DATE_TEMPLATE.format(date=today),
                user=user,
                model=self.client.synthesize_model,
                max_tokens=1200,
            )
            return SectorDigest.from_json(raw, sector)
        except Exception as e:
            logger.error(f"板块汇总失败 [{sector}]: {e}")
            # 降级：用原始数据构建一个基本的 digest
            return self._fallback_digest(sector, condensed_list)

    def _fallback_digest(
        self, sector: str, condensed_list: List[CondensedContent]
    ) -> SectorDigest:
        """降级方案：不调用 AI，直接汇总原始数据"""
        themes = list(set(
            vp.topic for cc in condensed_list
            for vp in cc.viewpoints if vp.topic
        ))
        stocks = []
        seen_stocks = set()
        for cc in condensed_list:
            for vp in cc.viewpoints:
                # 从 evidence 和 opinion 中简单提取可能的股票名
                pass  # 不靠谱，跳过

        viewpoints = []
        for cc in condensed_list:
            for vp in cc.viewpoints:
                viewpoints.append({
                    "author": cc.author,
                    "url": cc.url,
                    "theme": vp.topic,
                    "viewpoint": vp.opinion,
                })

        return SectorDigest(
            sector=sector,
            has_data=True,
            discussion_heat="中" if len(condensed_list) >= 3 else "低",
            key_themes=themes[:5],
            author_viewpoints=viewpoints,
            mentioned_stocks=[],
            sector_overview=f"今日 {len(condensed_list)} 位作者讨论了该板块",
        )

    # ── 处理所有板块 ──

    def digest_all(
        self,
        sector_groups: Dict[str, List[CondensedContent]],
    ) -> List[SectorDigest]:
        """处理所有有数据的板块，返回按热度排序的 digest 列表"""
        digests = []
        active_sectors = [
            (sector, items)
            for sector, items in sector_groups.items()
            if items
        ]

        if not active_sectors:
            logger.info("没有板块有数据，跳过汇总")
            return digests

        # 按内容数量排序，热度高的先处理
        active_sectors.sort(key=lambda x: len(x[1]), reverse=True)

        logger.info(f"需汇总的板块：{len(active_sectors)} 个")
        for sector, items in active_sectors:
            logger.info(f"  汇总板块：{sector}（{len(items)} 条内容）")
            digest = self.digest_sector(sector, items)
            digests.append(digest)

        return digests

    # ── 生成每日总览 ──

    def generate_overview(
        self,
        digests: List[SectorDigest],
        total_condensed: int,
        total_raw: int,
    ) -> DailyDigest:
        """基于所有板块汇总，生成最终的每日总览"""
        if not digests:
            return DailyDigest(overview="今日无相关财经内容")

        # 构建板块摘要
        sector_briefs = "\n".join(
            f"- 【{d.sector}】热度{d.discussion_heat} | {d.sector_overview}"
            for d in digests
        )

        hot_digests = [d for d in digests if d.discussion_heat == "高"]
        mid_digests = [d for d in digests if d.discussion_heat == "中"]

        today = datetime.now(CST).strftime("%Y年%m月%d日")
        user = f"""今日共抓取 {total_raw} 条内容，其中 {total_condensed} 条与财经相关，涉及 {len(digests)} 个板块。

各板块讨论情况：
{sector_briefs}

请基于以上信息，生成今日A股市场讨论的总览。输出JSON：
{{
  "overview": "今日市场讨论总体概述，200字内",
  "hot_topics": ["今日最受关注的3-5个话题"],
  "summary_by_sector": [
    {{"sector": "板块名", "one_liner": "一句话总结该板块今日讨论焦点（80字内）"}}
  ]
}}"""

        try:
            raw = self.client.complete(
                system=SYSTEM_DATE_TEMPLATE.format(date=today),
                user=user,
                model=self.client.synthesize_model,
                max_tokens=600,
            )
            return DailyDigest.from_json(raw)
        except Exception as e:
            logger.error(f"生成总览失败: {e}")
            return DailyDigest(
                overview=f"今日共分析 {total_condensed} 条财经相关内容，"
                         f"覆盖 {len(digests)} 个板块。"
                         f"热度最高板块：{digests[0].sector if digests else '无'}。",
                hot_topics=[d.sector for d in hot_digests[:5]],
                summary_by_sector=[
                    {"sector": d.sector, "one_liner": d.sector_overview}
                    for d in digests
                ],
            )


# ---- 向后兼容 ----
Synthesizer = Digester
