#!/usr/bin/env python3
"""金十数据实时监听 + iPhone 推送。

用法:
    python main.py              # 终端仪表盘模式
    python main.py --quiet      # 后台静默模式
    python main.py --test       # 测试模式：拉取一次，打印分析结果，发一条 Bark 测试
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

# ── 自动加载 .env 文件 ─────────────────────────────────────────────
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:  # 不覆盖已有环境变量
                    os.environ[key] = val

from fetcher import fetch_news
from detector import keyword_match, ai_verify, should_trigger
from notifier import send, send_test, format_stock_alert
from storage import init_db, is_new, mark_sent, cleanup_old, get_recent_notifications

# ── 配置加载 ──────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 日志 ──────────────────────────────────────────────────────────

def setup_logging(cfg: dict, quiet: bool = False) -> None:
    level = getattr(logging, cfg.get("log", {}).get("level", "INFO"))
    log_file = cfg.get("log", {}).get("file", "monitor.log")

    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if not quiet:
        # 非静默模式：错误以上输出到 stderr（仪表盘用 Rich 输出）
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        handlers.append(stderr_handler)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ── 仪表盘 ────────────────────────────────────────────────────────

class Dashboard:
    """Rich 终端仪表盘。"""

    def __init__(self):
        self.stats = {
            "fetched": 0,
            "keyword_hits": 0,
            "ai_confirmed": 0,
            "total_sent": 0,
            "last_poll": "",
            "start_time": datetime.now(),
            "errors": 0,
        }
        self.start_time = datetime.now()

    def update(self, fetched=0, keyword_hits=0, ai_confirmed=0, sent=0, error=False) -> None:
        self.stats["fetched"] = fetched
        self.stats["keyword_hits"] = keyword_hits
        self.stats["ai_confirmed"] = ai_confirmed
        self.stats["last_poll"] = datetime.now().strftime("%H:%M:%S")
        self.stats["total_sent"] += sent
        if error:
            self.stats["errors"] += 1

    def render(self) -> str:
        """生成仪表盘文本。"""
        s = self.stats
        elapsed = datetime.now() - self.start_time
        hours, rem = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(rem, 60)

        lines = [
            "╔══════════════════════════════════════════╗",
            f"║  金十监听中 | 已运行: {hours}h{minutes}m{seconds}s".ljust(46) + "║",
            "╠══════════════════════════════════════════╣",
            f"║  最近轮询: {s['last_poll']}  拉取 {s['fetched']} 条快讯".ljust(46) + "║",
            f"║  关键词命中: {s['keyword_hits']} 条  AI确认: {s['ai_confirmed']} 条".ljust(46) + "║",
            f"║  累计推送: {s['total_sent']} 次  错误: {s['errors']}".ljust(46) + "║",
            "╠══════════════════════════════════════════╣",
        ]

        # 最近推送记录
        recent = get_recent_notifications(limit=5)
        if recent:
            for r in recent:
                entry = f"  [{r['sent_at'][-8:-3]}] ⚠️ {r['by']}看好{r['stock']}"
                lines.append(f"║{entry}".ljust(46) + "║")
        else:
            lines.append("║  (暂无推送记录)".ljust(46) + "║")

        lines.append("╚══════════════════════════════════════════╝")
        return "\n".join(lines)


# ── 运行模式 ──────────────────────────────────────────────────────

def run_loop(cfg: dict, quiet: bool = False) -> None:
    """主循环：轮询 → 检测 → 推送。"""
    bark_cfg = cfg["bark"]
    det_cfg = cfg["detection"]
    ai_cfg = cfg["ai"]

    interval = det_cfg.get("poll_interval_seconds", 90)
    target_people = det_cfg.get("target_people", ["黄仁勋", "特朗普"])
    bullish_keywords = det_cfg.get("bullish_keywords", [])
    ai_enabled = ai_cfg.get("enabled", True)
    ai_model = ai_cfg.get("model", "deepseek-chat")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if ai_enabled and not api_key:
        logging.warning("AI 精判已启用但未设置 DEEPSEEK_API_KEY 环境变量，将仅用关键词模式")
        ai_enabled = False

    dash = None if quiet else Dashboard()
    logger = logging.getLogger("main")

    logger.info("金十监听启动")

    while True:
        try:
            # 1. 拉取
            news_list = fetch_news()
            fetched = len(news_list)
            keyword_hits = 0
            ai_confirmed = 0
            sent_count = 0

            # 2. 检测
            for news in news_list:
                if not is_new(news["content"]):
                    continue

                matched, stocks = keyword_match(
                    news["content"], target_people, bullish_keywords
                )
                if not matched:
                    continue
                keyword_hits += 1

                # AI 精判
                trigger = False
                verdict = None
                if ai_enabled:
                    verdict = ai_verify(news["content"], news["time"], api_key, ai_model)
                    trigger = should_trigger(verdict)
                else:
                    # 无 AI 模式：关键词命中即推送
                    trigger = True
                    verdict = {"speaker": "检测到", "stock_name": stocks[0] if stocks else "",
                               "summary": news["content"][:100], "confidence": 1.0}

                if trigger:
                    ai_confirmed += 1
                    person = verdict.get("speaker", "检测到")
                    stock = verdict.get("stock_name", stocks[0] if stocks else "某股")
                    summary = verdict.get("summary", news["content"][:120])

                    title, body = format_stock_alert(person, stock, summary)
                    ok = send(
                        device_key=bark_cfg["device_key"],
                        title=title,
                        body=body,
                        base_url=bark_cfg.get("base_url", "https://api.day.app"),
                    )
                    if ok:
                        mark_sent(news["id"], news["content"], stock, person)
                        sent_count += 1

            # 3. 更新仪表盘
            if dash:
                dash.update(
                    fetched=fetched,
                    keyword_hits=keyword_hits,
                    ai_confirmed=ai_confirmed,
                    sent=sent_count,
                )
                _clear_screen()
                print(dash.render())

            # 4. 定期清理过期记录
            if sent_count > 0:
                cleanup_old()

        except KeyboardInterrupt:
            logger.info("用户中断，退出")
            print("\n👋 已退出")
            break
        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)
            if dash:
                dash.update(error=True)
            time.sleep(10)

        time.sleep(interval)


def run_test(cfg: dict) -> None:
    """测试模式：拉一次数据、展示分析结果、发测试推送。"""
    bark_cfg = cfg["bark"]
    det_cfg = cfg["detection"]
    ai_cfg = cfg["ai"]

    target_people = det_cfg.get("target_people", ["黄仁勋", "特朗普"])
    bullish_keywords = det_cfg.get("bullish_keywords", [])
    ai_model = ai_cfg.get("model", "deepseek-chat")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    ai_provider = ai_cfg.get("provider", "deepseek")

    print("=" * 60)
    print("  金十监听 — 测试模式")
    print("=" * 60)

    # 1. Bark 测试
    print("\n📱 发送 Bark 测试推送...")
    if bark_cfg["device_key"] == "YOUR_BARK_DEVICE_KEY":
        print("   ⚠️ 未配置 Bark device_key，请在 config.yaml 中填入后重试")
    else:
        ok = send_test(bark_cfg["device_key"], bark_cfg.get("base_url", "https://api.day.app"))
        print(f"   {'✅ 测试推送已发送' if ok else '❌ 推送失败，请检查 device_key'}")

    # 2. 拉取快讯
    print("\n📡 拉取金十快讯...")
    news_list = fetch_news()
    print(f"   拉取到 {len(news_list)} 条快讯")

    if not news_list:
        print("   ⚠️ 没有拉取到数据，请检查网络或 AKShare 版本")
        return

    # 3. 展示最新几条
    print("\n📋 最近 5 条快讯：")
    for i, news in enumerate(news_list[:5]):
        print(f"   [{news['time']}] {news['content'][:120]}{'...' if len(news['content']) > 120 else ''}")

    # 4. 关键词检测
    print(f"\n🔍 关键词检测（目标人物: {target_people}）：")
    hit_count = 0
    for news in news_list:
        matched, stocks = keyword_match(news["content"], target_people, bullish_keywords)
        if matched:
            hit_count += 1
            print(f"   💡 命中 [{news['time']}]: {news['content'][:100]}...")
            print(f"      股票候选: {stocks}")

            # AI 精判
            if ai_cfg.get("enabled", True) and api_key:
                print(f"      🤖 AI 精判中...")
                verdict = ai_verify(news["content"], news["time"], api_key, ai_model)
                if verdict:
                    print(f"      结果: bullish={verdict.get('is_bullish_recommendation')}, "
                          f"speaker={verdict.get('speaker')}, "
                          f"stock={verdict.get('stock_name')}, "
                          f"confidence={verdict.get('confidence')}")
                    if should_trigger(verdict):
                        print(f"      ✅ 满足推送条件！")
                    else:
                        print(f"      ❌ 不满足推送条件（speaker非本人或置信度不足）")
                else:
                    print(f"      ❌ AI 调用失败")

    if hit_count == 0:
        print("   本轮未命中任何关键词 → 这很正常，黄仁勋/特朗普不是每条快讯都出现")

    print("\n" + "=" * 60)
    print("  测试完成。确认以上输出正常后，运行 python main.py 启动监听")
    print("=" * 60)


def _clear_screen():
    """清屏（用于仪表盘刷新）。"""
    # 这里不用 os.system('clear') 以避免跨平台问题
    # 改为打印换行来实现"伪清屏"
    print("\033[2J\033[H", end="")


# ── 入口 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="金十数据实时监听 — 黄仁勋/特朗普股票推荐推送"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="后台静默模式，无终端输出"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="测试模式：拉取一次数据，分析并展示结果"
    )
    args = parser.parse_args()

    cfg = load_config()
    init_db()

    if args.test:
        setup_logging(cfg, quiet=False)
        run_test(cfg)
    else:
        setup_logging(cfg, quiet=args.quiet)
        if args.quiet:
            print("🔇 金十监听已启动（静默模式），按 Ctrl+C 退出")
        run_loop(cfg, quiet=args.quiet)


if __name__ == "__main__":
    main()
