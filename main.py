"""
A股每日分析系统 - 主入口（DeepSeek 版）
按作者逐篇分析 + 每日行业总结

Usage:
  python main.py                  # 正常运行
  python main.py --dry-run        # 仅抓取，不调用 AI 也不发邮件
  python main.py --validate-only  # 仅验证 Cookie 和 SMTP 配置
  python main.py --skip-fetch     # 跳过抓取，使用测试数据
  python main.py --date 2026-05-29  # 指定日期抓取（默认今天）
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz
import yaml

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.logger import setup_logger
from src.storage.db import Database
from src.crawler.zhihu_client import ZhihuClient
from src.crawler.feed_fetcher import FeedFetcher, RawContent
from src.analyzer.deepseek_client import DeepSeekClient
from src.analyzer.classifier import Classifier
from src.analyzer.extractor import ContentSummarizer
from src.reporter.html_renderer import HtmlRenderer
from src.reporter.markdown_renderer import render_markdown
from src.reporter.email_sender import EmailSender

CST = pytz.timezone("Asia/Shanghai")


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_config(cfg: dict) -> list[str]:
    errors = []
    if not cfg.get("zhihu", {}).get("cookie_z_c0"):
        errors.append("zhihu.cookie_z_c0")
    if not cfg.get("deepseek", {}).get("api_key"):
        errors.append("deepseek.api_key")
    if cfg.get("email", {}).get("enabled"):
        ec = cfg["email"]
        if not ec.get("username"): errors.append("email.username")
        if not ec.get("password"): errors.append("email.password")
        if not any(ec.get("recipients", [])): errors.append("email.recipients")
    return errors


def today_str(tz=CST, reference_date: str = None) -> str:
    if reference_date:
        try:
            datetime.strptime(reference_date, "%Y-%m-%d")
            return reference_date
        except ValueError:
            pass
    return datetime.now(tz).strftime("%Y-%m-%d")


def cleanup_old_files(directory: str, keep_days: int):
    cutoff = time.time() - keep_days * 86400
    path = Path(directory)
    if not path.exists():
        return
    count = sum(1 for f in path.iterdir() if f.is_file() and f.stat().st_mtime < cutoff)
    for f in path.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
    if count:
        logging.getLogger("zhihu_analyst").info(f"Cleaned {count} old files in {directory}")


def save_report(html: str, md: str, report_dir: str, date_str: str) -> tuple[str, str]:
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hp = out_dir / f"report_{date_str}.html"
    mp = out_dir / f"report_{date_str}.md"
    hp.write_text(html, encoding="utf-8")
    mp.write_text(md, encoding="utf-8")
    return str(hp), str(mp)


def main():
    parser = argparse.ArgumentParser(description="A股每日分析")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    cfg = load_config(args.config)
    oc = cfg.get("output", {})
    log_dir = oc.get("log_dir", "output/logs")
    report_dir = oc.get("report_dir", "output/reports")
    keep_days = oc.get("keep_days", 30)

    logger = setup_logger(log_dir)
    logger.info("=" * 60)
    logger.info(f"A股每日分析启动 ({today_str(reference_date=args.date)}) [DeepSeek]")
    logger.info("=" * 60)

    errs = validate_config(cfg)
    if errs:
        for e in errs:
            logger.error(f"  Config missing: {e}")
        sys.exit(1)

    start_time = time.time()
    date_str = today_str(reference_date=args.date)

    db_path = cfg.get("database", {}).get("path", "output/seen_content.db")
    db = Database(db_path)
    db.cleanup_old(cfg.get("database", {}).get("retention_days", 7))
    cleanup_old_files(log_dir, keep_days)
    cleanup_old_files(report_dir, keep_days)

    zhihu_cfg = cfg["zhihu"]
    zhihu = ZhihuClient(zhihu_cfg["cookie_z_c0"])

    logger.info("Verifying Zhihu Cookie...")
    if not zhihu.validate_cookie():
        logger.error("Cookie invalid or expired!")
        if cfg.get("email", {}).get("enabled") and not args.validate_only:
            try:
                EmailSender(cfg["email"]).send_cookie_expired_alert()
            except Exception as e:
                logger.warning(f"Failed to send alert: {e}")
        if args.validate_only:
            sys.exit(1)
        db.record_run(date_str, 0, 0, {}, success=False, error_msg="Cookie expired")
        sys.exit(1)

    if args.validate_only:
        logger.info("Cookie OK")
        if cfg.get("email", {}).get("enabled"):
            if not EmailSender(cfg["email"]).test_connection():
                sys.exit(1)
        logger.info("All configs OK")
        return

    # ── Fetch ──
    raw_contents: list[RawContent] = []
    if not args.skip_fetch:
        followees = zhihu.fetch_followees()
        fetcher = FeedFetcher(zhihu, db, zhihu_cfg, followees=followees, reference_date=args.date)
        # 两条路径同时抓取，相互补充
        topstory_results = fetcher.fetch_today()       # 文章+回答+想法（含完整正文）
        followee_results = fetcher.fetch_from_followees()  # 回答+想法（补充 topstory 可能遗漏的）
        # 合并去重
        seen_ids = set()
        raw_contents = []
        for c in topstory_results + followee_results:
            if c.content_id not in seen_ids:
                seen_ids.add(c.content_id)
                raw_contents.append(c)
        logger.info(f"合并结果：topstory {len(topstory_results)} + followee {len(followee_results)} → {len(raw_contents)} 条")
    else:
        logger.warning("--skip-fetch: using test data")
        import time as _time
        raw_contents = [
            RawContent(content_id="test_001", content_type="article",
                title="半导体行业展望", body="AI算力需求驱动存储芯片上涨。国产替代加速。",
                author="TestA", created_time=int(_time.time()),
                url="https://zhuanlan.zhihu.com/p/test001"),
            RawContent(content_id="test_002", content_type="answer",
                title="央行降准预期", body="央行释放宽松信号，银行板块受益但息差压力仍存。",
                author="TestB", created_time=int(_time.time()),
                url="https://www.zhihu.com/question/test/answer/test002"),
        ]

    if args.dry_run:
        logger.info("--dry-run: skipping AI analysis")
        print(f"\n{'='*50}")
        print(f"Fetch results ({len(raw_contents)} items):")
        for i, c in enumerate(raw_contents[:10], 1):
            print(f"  {i}. [{c.content_type}] {c.author}: {c.title[:50] or c.body[:50]}")
        if len(raw_contents) > 10:
            print(f"  ... plus {len(raw_contents)-10} more")
        return

    # ── Init AI ──
    ds_cfg = cfg["deepseek"]
    client = DeepSeekClient(ds_cfg["api_key"], ds_cfg)
    classifier = Classifier(client, ds_cfg)
    summarizer = ContentSummarizer(client)

    # ── Phase 1: Classify ──
    is_relevant_list = classifier.classify_batch(raw_contents) if raw_contents else []
    relevant_contents = [c for c, r in zip(raw_contents, is_relevant_list) if r]
    logger.info(f"Classify: {len(relevant_contents)}/{len(raw_contents)} relevant")

    # ── Phase 2: Summarize ──
    summary = ""
    if relevant_contents:
        summary = summarizer.summarize(relevant_contents)
        logger.info(f"Summary: {len(summary)} chars")
    else:
        summary = "今日无相关财经内容。"
        logger.info("No relevant content to summarize")

    # ── Generate Reports ──
    elapsed = time.time() - start_time
    html_renderer = HtmlRenderer("templates")
    html_content = html_renderer.render(
        report_date=date_str,
        total_items=len(raw_contents),
        relevant_items=len(relevant_contents),
        summary=summary,
        relevant_contents=relevant_contents,
        cost_tracker=client.cost_tracker,
        elapsed_seconds=elapsed,
    )
    md_content = render_markdown(
        report_date=date_str,
        total_items=len(raw_contents),
        relevant_items=len(relevant_contents),
        summary=summary,
        relevant_contents=relevant_contents,
        cost_tracker=client.cost_tracker,
        elapsed_seconds=elapsed,
    )
    hp, mp = save_report(html_content, md_content, report_dir, date_str)
    logger.info(f"Reports saved: {hp}, {mp}")

    if cfg.get("email", {}).get("enabled"):
        try:
            EmailSender(cfg["email"]).send_report(date_str, html_content, md_content)
            logger.info("Email sent")
        except Exception as e:
            logger.error(f"Email failed: {e}")

    if raw_contents:
        is_rel_map = {c.content_id: r for c, r in zip(raw_contents, is_relevant_list)}
        db.mark_seen_batch([
            (c.content_id, c.content_type, is_rel_map.get(c.content_id, False))
            for c in raw_contents
        ])

    db.record_run(date_str, len(raw_contents), len(relevant_contents),
                  client.cost_tracker, success=True)
    db.close()

    total_t = time.time() - start_time
    logger.info(f"Done in {total_t:.1f}s | {client.summary_cost()}")
    logger.info(f"Report: {hp}")


if __name__ == "__main__":
    main()
