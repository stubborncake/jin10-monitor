"""金十数据快讯拉取模块。

直接调用金十数据 HTTP API 获取实时快讯。
"""

import hashlib
import logging
import re
import time
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# 金十快讯 API
FLASH_API_URL = "https://flash-api.jin10.com/get_flash_list"

# 必须的请求头（金十 App 标识）
API_HEADERS = {
    "x-app-id": "SO1EJGmNgCtmpcPF",
    "x-version": "1.0.0",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://www.jin10.com",
    "Referer": "https://www.jin10.com/",
}

# 频道标识（-8200 = 全部快讯）
DEFAULT_CHANNEL = "-8200"

# HTML 标签清理正则
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def fetch_news(
    max_retries: int = 3,
    retry_delay: float = 5.0,
    channel: str = DEFAULT_CHANNEL,
) -> list[dict]:
    """拉取金十数据最近一批快讯。

    Args:
        max_retries: 最大重试次数。
        retry_delay: 重试间隔（秒）。
        channel: 频道 ID，默认 -8200（全部）。

    Returns:
        快讯列表，每条为 dict: {"id": str, "content": str, "time": str}
        若多次重试均失败则返回空列表。
    """
    # 用当前 UTC 时间作为 max_time，获取最近快讯
    max_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "channel": channel,
        "max_time": max_time,
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.get(
                FLASH_API_URL,
                params=params,
                headers=API_HEADERS,
                timeout=15.0,
            )
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("status") != 200:
                logger.warning(f"API 返回异常状态: {payload.get('status')}")
                return []

            raw_data = payload.get("data") or []
            news_list = []
            for item in raw_data:
                data = item.get("data") or {}
                content = data.get("content", "")
                if not content:
                    continue

                # 清理 HTML 标签
                content = _clean_html(content)

                news_time = item.get("time", "")
                news_id = item.get("id", _make_id(content, news_time))

                news_list.append({
                    "id": news_id,
                    "content": content,
                    "time": news_time,
                })

            logger.info(f"拉取到 {len(news_list)} 条快讯")
            return news_list

        except Exception as e:
            logger.warning(f"第 {attempt}/{max_retries} 次拉取失败: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    logger.error("所有重试均失败，放弃本轮拉取")
    return []


def _clean_html(text: str) -> str:
    """去除 HTML 标签并清理空白。"""
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


def _make_id(content: str, time_str: str) -> str:
    """以内容哈希 + 时间生成唯一 ID，作为 API 未返回 id 时的后备。"""
    seed = f"{time_str}|{content[:80]}"
    return hashlib.md5(seed.encode()).hexdigest()[:16]
