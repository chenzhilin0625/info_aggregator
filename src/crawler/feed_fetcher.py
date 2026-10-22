"""
知乎关注流抓取：分页、今日边界判断、内容解析
"""
import time
import random
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pytz
from bs4 import BeautifulSoup

from src.crawler.zhihu_client import ZhihuClient
from src.storage.db import Database

logger = logging.getLogger("zhihu_analyst")
CST = pytz.timezone("Asia/Shanghai")


@dataclass
class RawContent:
    """统一的知乎内容数据类"""
    content_id: str
    content_type: str
    title: str
    body: str
    author: str
    created_time: int
    url: str
    raw_body_html: str = ""

    @property
    def time_display(self) -> str:
        dt = datetime.fromtimestamp(self.created_time, tz=CST)
        return dt.strftime("%Y-%m-%d %H:%M")

    @property
    def body_truncated(self) -> str:
        return self.body[:800] if len(self.body) > 800 else self.body


def _strip_html(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", "", html)


def _get_today_start_ts(day_start_hour: int = 0, reference_date: str = None) -> int:
    if reference_date:
        try:
            dt = datetime.strptime(reference_date, "%Y-%m-%d")
            today_start = CST.localize(dt.replace(hour=day_start_hour, minute=0, second=0, microsecond=0))
            return int(today_start.timestamp())
        except ValueError:
            pass
    now = datetime.now(CST)
    today_start = now.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    return int(today_start.timestamp())


class FeedFetcher:
    def __init__(self, client: ZhihuClient, db: Database, cfg: dict,
                 followees: set[str] = None, reference_date: str = None):
        self.client = client
        self.db = db
        self.followees = followees or set()
        self.max_pages = cfg.get("max_pages", 50)
        self.stale_threshold = cfg.get("stale_threshold", 5)
        self.delay_min = cfg.get("request_delay_min", 1.0)
        self.delay_max = cfg.get("request_delay_max", 2.5)
        self.today_start_ts = _get_today_start_ts(reference_date=reference_date)
        logger.info(
            f"今日起始时间戳：{self.today_start_ts} "
            f"({datetime.fromtimestamp(self.today_start_ts, CST).strftime('%Y-%m-%d %H:%M')})"
        )

    def fetch_from_followees(self) -> List[RawContent]:
        """
        遍历关注用户，拉取回答（需单独获取正文）和想法（有正文）。
        文章正文无法通过独立 API 获取（返回 403），文章走 topstory 抓取。
        """
        results: List[RawContent] = []
        url_tokens = list(self.followees)
        logger.info(f"开始遍历 {len(url_tokens)} 位关注用户的回答和想法...")

        for i, token in enumerate(url_tokens):
            if not token:
                continue
            try:
                # 回答：列表 API 不含 content，需单独获取正文
                answers = self.client.fetch_member_answers(token, limit=5)
                for a in answers:
                    ct = a.get("created_time", 0)
                    a_id = a.get("id", "")
                    if ct >= self.today_start_ts and a_id and not self.db.is_seen(f"answer_{a_id}"):
                        answer_content = self.client.fetch_answer_content(a_id)
                        if answer_content:
                            a["_content"] = answer_content
                        content = self._parse_answer_raw(a)
                        if content:
                            results.append(content)

                # 想法：API 有正文，直接解析
                pins = self.client.fetch_member_pins(token, limit=5)
                for p in pins:
                    ct = p.get("created") or p.get("updated") or 0
                    p_id = p.get("id", "")
                    if ct >= self.today_start_ts and p_id and not self.db.is_seen(f"pin_{p_id}"):
                        content = self._parse_pin_raw(p)
                        if content:
                            results.append(content)
            except Exception as e:
                logger.debug(f"获取用户 {token} 内容失败: {e}")

            if (i + 1) % 10 == 0:
                logger.info(f"  已检查 {i+1}/{len(url_tokens)} 人，收集 {len(results)} 条今日内容")
            time.sleep(random.uniform(0.3, 0.8))

        logger.info(f"关注用户遍历完成：共收集 {len(results)} 条今日内容")
        return results

    def _parse_answer_raw(self, a: dict) -> Optional[RawContent]:
        a_id = a.get("id", "")
        if not a_id:
            return None
        question = a.get("question", {}) or {}
        # 列表 API 不含 content，优先使用单独获取的 _content，其次 content
        html_body = a.get("_content") or a.get("content", "")
        if not html_body:
            return None
        return RawContent(
            content_id=f"answer_{a_id}",
            content_type="answer",
            title=question.get("title", ""),
            body=_strip_html(html_body),
            raw_body_html=html_body,
            author=a.get("author", {}).get("name", "匿名用户"),
            created_time=a.get("created_time", 0),
            url=f"https://www.zhihu.com/question/{question.get('id', '')}/answer/{a_id}",
        )

    def _parse_article_raw(self, art: dict) -> Optional[RawContent]:
        art_id = art.get("id", "")
        if not art_id:
            return None
        html_body = art.get("content", "")
        ct = art.get("created") or art.get("updated") or 0
        return RawContent(
            content_id=f"article_{art_id}",
            content_type="article",
            title=art.get("title", ""),
            body=_strip_html(html_body),
            raw_body_html=html_body,
            author=art.get("author", {}).get("name", "匿名用户"),
            created_time=int(ct),
            url=f"https://zhuanlan.zhihu.com/p/{art_id}",
        )

    def _parse_pin_raw(self, pin: dict) -> Optional[RawContent]:
        p_id = pin.get("id", "")
        if not p_id:
            return None
        content_items = pin.get("content", [])
        text_parts = []
        for ci in content_items:
            if isinstance(ci, dict) and ci.get("type") == "text":
                text_parts.append(ci.get("content", "") or ci.get("own_text", ""))
        body = _strip_html(" ".join(text_parts))
        ct = pin.get("created") or pin.get("updated") or 0
        pin_url = pin.get("url", "") or f"https://www.zhihu.com/pin/{p_id}"
        if not pin_url.startswith("http"):
            pin_url = f"https://www.zhihu.com{pin_url}"
        return RawContent(
            content_id=f"pin_{p_id}",
            content_type="pin",
            title=pin.get("excerpt_title", "") or "",
            body=body,
            raw_body_html=" ".join(text_parts),
            author=pin.get("author", {}).get("name", "匿名用户"),
            created_time=int(ct),
            url=pin_url,
        )

    def fetch_today(self) -> List[RawContent]:
        results: List[RawContent] = []
        next_url: Optional[str] = None
        stale_count = 0
        total_seen = 0
        total_skipped_dup = 0

        for page_num in range(1, self.max_pages + 1):
            logger.info(f"抓取第 {page_num} 页")
            data = self.client.get_feed_page(next_url=next_url, limit=20)
            items = data.get("data", [])

            if not items:
                logger.info("返回空列表，停止抓取")
                break

            total_seen += len(items)
            page_old_count = 0

            for item in items:
                content = self._parse_item(item)
                if content is None:
                    continue

                if content.created_time < self.today_start_ts:
                    page_old_count += 1
                    stale_count += 1
                else:
                    stale_count = 0
                    if self.db.is_seen(content.content_id):
                        total_skipped_dup += 1
                    else:
                        results.append(content)

            logger.debug(
                f"  第 {page_num} 页：{len(items)} 条，"
                f"今日 {len(items) - page_old_count} 条，"
                f"连续旧内容 {stale_count} 条"
            )

            if stale_count >= self.stale_threshold:
                logger.info(f"连续 {stale_count} 条旧内容，停止翻页")
                break

            paging = data.get("paging", {})
            if paging.get("is_end"):
                logger.info("API 返回 is_end=true，停止翻页")
                break

            next_url = paging.get("next", "")
            if not next_url:
                logger.info("无下一页 URL，停止翻页")
                break

            delay = random.uniform(self.delay_min, self.delay_max)
            time.sleep(delay)

        logger.info(
            f"抓取完成：共处理 {total_seen} 条，"
            f"跳过重复 {total_skipped_dup} 条，"
            f"今日新内容 {len(results)} 条"
        )
        return results

    def _parse_item(self, item: dict) -> Optional[RawContent]:
        item_type = item.get("type", "")
        target = item.get("target", {})

        if item_type in ("feed_advert", "commercial_story"):
            return None
        if not target:
            return None

        # 过滤非关注用户的内容
        if self.followees:
            author = target.get("author", {})
            author_token = author.get("url_token", "")
            if author_token and author_token not in self.followees:
                return None

        # Feed 层的时间戳是内容出现在关注流的时间（最准确）
        feed_time = item.get("created_time", 0)

        try:
            real_type = target.get("type", item_type)
            if item_type == "feed":
                if real_type == "answer":
                    return self._parse_answer(target, feed_time)
                elif real_type == "article":
                    return self._parse_article(target, feed_time)
                elif real_type == "pin":
                    return self._parse_pin(target, feed_time)
                elif real_type in ("question", "topic", "column", "collection"):
                    pass
                else:
                    logger.debug(f"跳过不支持的 feed 子类型: {real_type}")
                return None

            if item_type == "answer":
                return self._parse_answer(target, feed_time)
            elif item_type == "article":
                return self._parse_article(target, feed_time)
            elif item_type == "pin":
                return self._parse_pin(target, feed_time)
            else:
                return None
        except Exception as e:
            logger.warning(f"解析 {item_type} 失败: {e}")
            return None

    def _parse_answer(self, target: dict, feed_time: int = 0) -> Optional[RawContent]:
        question = target.get("question", {}) or {}
        q_id = question.get("id", "")
        a_id = target.get("id", "")
        if not a_id:
            return None

        html_body = target.get("content", "")
        ct = feed_time or target.get("created_time") or target.get("updated_time") or 0
        return RawContent(
            content_id=f"answer_{a_id}",
            content_type="answer",
            title=question.get("title", ""),
            body=_strip_html(html_body),
            raw_body_html=html_body,
            author=target.get("author", {}).get("name", "匿名用户"),
            created_time=int(ct),
            url=f"https://www.zhihu.com/question/{q_id}/answer/{a_id}",
        )

    def _parse_article(self, target: dict, feed_time: int = 0) -> Optional[RawContent]:
        a_id = target.get("id", "")
        if not a_id:
            return None

        html_body = target.get("content", "")
        ct = feed_time or target.get("created_time") or target.get("updated_time") or 0
        return RawContent(
            content_id=f"article_{a_id}",
            content_type="article",
            title=target.get("title", ""),
            body=_strip_html(html_body),
            raw_body_html=html_body,
            author=target.get("author", {}).get("name", "匿名用户"),
            created_time=int(ct),
            url=f"https://zhuanlan.zhihu.com/p/{a_id}",
        )

    def _parse_pin(self, target: dict, feed_time: int = 0) -> Optional[RawContent]:
        p_id = target.get("id", "")
        if not p_id:
            return None

        content_items = target.get("content", [])
        text_parts = []
        for ci in content_items:
            if ci.get("type") == "text":
                text_parts.append(ci.get("content", ""))

        body = _strip_html(" ".join(text_parts))
        ct = feed_time or target.get("created_time") or target.get("updated_time") or 0

        return RawContent(
            content_id=f"pin_{p_id}",
            content_type="pin",
            title="",
            body=body,
            raw_body_html=" ".join(text_parts),
            author=target.get("author", {}).get("name", "匿名用户"),
            created_time=int(ct),
            url=f"https://www.zhihu.com/pin/{p_id}",
        )
