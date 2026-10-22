"""
第一阶段：批量相关性分类（判断内容是否与财经/股市/时政相关）
"""
import json
import logging
import re
from typing import List

from src.analyzer.deepseek_client import DeepSeekClient
from src.crawler.feed_fetcher import RawContent

logger = logging.getLogger("zhihu_analyst")

CLASSIFY_SYSTEM = """你是A股投资信息筛选助手。

你的任务是判断每条内容是否与财经和投资有关系，包括但不限于以下任一主题【相关】：
- 股票市场、A股、港股、美股（含涨跌、行情、个股、板块）
- 上市公司（业绩、公告、并购、分红）
- 行业政策与监管（影响上市公司的政策）
- 宏观经济（GDP、CPI、PMI、就业、贸易）
- 货币政策（降息、降准、央行操作）
- 财政政策（减税、补贴、专项债）
- 时政新闻（重大会议、领导人讲话、国际关系中影响经济的部分）
- 大宗商品（石油、铜、黄金、煤炭等）
- 房地产市场政策

【不相关】的内容包括：娱乐八卦、生活方式、文学历史（无经济联系）、纯学术、体育（无博彩）、抖机灵开玩笑等。

严格输出JSON数组，不含任何解释或代码块标记。"""


def _parse_bool_array(raw: str, expected_len: int) -> List[bool]:
    """解析模型返回的 JSON bool 数组，容错处理。失败时保守返回全 True。"""
    try:
        cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()
        arr = json.loads(cleaned)
        if isinstance(arr, list) and len(arr) == expected_len:
            return [bool(v) for v in arr]
        if isinstance(arr, list):
            while len(arr) < expected_len:
                arr.append(True)
            return [bool(v) for v in arr[:expected_len]]
    except Exception as e:
        logger.warning(f"解析分类结果失败: {e}，原始响应: {raw[:200]}，全部标为相关")
    return [True] * expected_len


class Classifier:
    def __init__(self, client: DeepSeekClient, cfg: dict):
        self.client = client
        self.batch_size = cfg.get("classify_batch_size", 25)

    def classify_batch(self, contents: List[RawContent]) -> List[bool]:
        """批量分类，返回与 contents 等长的 bool 列表。True 表示相关。"""
        if not contents:
            return []

        results = []
        total_batches = (len(contents) + self.batch_size - 1) // self.batch_size

        for batch_idx in range(0, len(contents), self.batch_size):
            batch = contents[batch_idx: batch_idx + self.batch_size]
            batch_num = batch_idx // self.batch_size + 1
            logger.info(f"分类第 {batch_num}/{total_batches} 批（{len(batch)} 条）")

            items_text = "\n".join(
                f"[{i}] 标题:{c.title[:60] if c.title else '(无标题)'} "
                f"| 正文预览:{c.body[:120]}"
                for i, c in enumerate(batch)
            )

            user_prompt = (
                f"以下 {len(batch)} 条内容，逐一判断是否与财经/股市/时政相关。\n\n"
                f"{items_text}\n\n"
                f"输出格式：仅输出一个JSON数组，长度 {len(batch)}，元素为 true 或 false，"
                f"与输入顺序严格对应。"
            )

            try:
                raw = self.client.complete(
                    system=CLASSIFY_SYSTEM,
                    user=user_prompt,
                    model=self.client.classify_model,
                    max_tokens=len(batch) * 8 + 32,
                )
                batch_results = _parse_bool_array(raw, len(batch))
            except Exception as e:
                logger.error(f"分类批次 {batch_num} 失败: {e}，全部标为相关")
                batch_results = [True] * len(batch)

            relevant_count = sum(batch_results)
            logger.info(f"  批次 {batch_num}：相关 {relevant_count}/{len(batch)} 条")
            results.extend(batch_results)

        return results
