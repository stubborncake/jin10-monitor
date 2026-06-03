"""Bark 推送通知模块。

通过 Bark HTTP API 向 iPhone 发送推送通知。
Bark 官网：https://bark.day.app
"""

import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# Bark 支持的参数
# isArchive: 1 = 自动保存到历史记录
# level: active / timeSensitive / passive
# sound: 自定义铃声名
# url: 点击通知跳转的 URL
DEFAULT_LEVEL = "timeSensitive"
DEFAULT_SOUND = "bell"


def send(
    device_key: str,
    title: str,
    body: str,
    base_url: str = "https://api.day.app",
    group: str = "金十监听",
    url: str = "",
    sound: str = DEFAULT_SOUND,
    level: str = DEFAULT_LEVEL,
) -> bool:
    """发送一条 Bark 推送。

    Args:
        device_key: Bark App 提供的设备 Key。
        title: 推送标题。
        body: 推送正文。
        base_url: Bark 服务地址。
        group: 推送分组（便于管理）。
        url: 点击推送后跳转的 URL（如金十原文链接）。
        sound: 推送铃声。
        level: 推送级别（timeSensitive 可在专注模式下送达）。

    Returns:
        True 表示发送成功。
    """
    # Bark v2 API: POST /push
    endpoint = f"{base_url}/push"
    payload = {
        "device_key": device_key,
        "title": title,
        "body": body,
        "group": group,
        "sound": sound,
        "level": level,
        "isArchive": 1,
    }
    if url:
        payload["url"] = url

    try:
        resp = httpx.post(endpoint, json=payload, timeout=10.0)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 200:
            logger.info(f"Bark 推送成功: {title}")
            return True
        else:
            logger.error(f"Bark 推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"Bark 推送异常: {e}")
        return False


def send_test(device_key: str, base_url: str = "https://api.day.app") -> bool:
    """发送一条测试推送，验证 Bark 配置是否正确。"""
    return send(
        device_key=device_key,
        title="✅ 金十监听已启动",
        body="如果你收到这条推送，说明 Bark 配置正确！\n程序正在监听黄仁勋/特朗普的股票推荐...",
        base_url=base_url,
        group="金十监听",
    )


def format_stock_alert(
    person: str,
    stock: str,
    summary: str,
) -> tuple[str, str]:
    """格式化股票推荐推送的标题和正文。

    Args:
        person: 推荐者（黄仁勋/特朗普）。
        stock: 被推荐的股票。
        summary: Claude 生成的一句话摘要。

    Returns:
        (title, body) 元组。
    """
    title = f"⚠️ {person}看好{stock}"
    body = summary if summary else f"{person}在最新快讯中提及{stock}，快去看看！"
    return title, body
