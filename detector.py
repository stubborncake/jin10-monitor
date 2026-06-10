"""检测模块 —— 两级判断快讯是否命中。

第一级：关键词匹配（本地，免费）
    检测三项：目标人名 + 看多关键词 + 可能的股票名
第二级：AI 精判（DeepSeek API，性价比高）
    判断推荐者是否为本人，提取股票名，评估置信度
"""

import json
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ── 第一级：关键词匹配 ────────────────────────────────────────────

def _match_any(text: str, keywords: list[str]) -> bool:
    """检查文本是否包含任意关键词（不区分大小写）。"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def extract_potential_stocks(text: str) -> list[str]:
    """从快讯文本中提取可能的股票名称/代码。

    支持识别：
    - 美股代码：AAPL, NVDA, TSLA 等（大写字母 2-5 位）
    - A 股代码：600xxx, 000xxx, 300xxx, 688xxx
    - 港股代码：0xxxx.HK
    - 中文股票名：XX股份、XX科技、XX集团、XX银行、XX证券等
    - 知名公司中文名：英伟达、苹果、特斯拉、微软等
    """
    found = []

    # 美股 ticker 模式：连续 2-5 个大写字母（前面可能带 $）
    ticker_pattern = r'\$?[A-Z]{2,5}'
    for m in re.finditer(ticker_pattern, text):
        ticker = m.group().lstrip('$')
        if ticker not in _NON_TICKER_WORDS:
            found.append(ticker)

    # A 股 6 位代码
    a_stock = re.findall(
        r'\b(60[0123]\d{3}|000\d{3}|001\d{3}|002\d{3}|300\d{3}|301\d{3}|688\d{3})\b',
        text
    )
    found.extend(a_stock)

    # 港股 5 位代码 + .HK
    hk_stock = re.findall(r'\b(0\d{4})\.HK\b', text, re.IGNORECASE)
    found.extend([f"{c}.HK" for c in hk_stock])

    # 中文股票名称
    cn_stock_pattern = (
        r'(?:[一-鿿]{2,6}(?:股份|科技|集团|银行|证券|控股|'
        r'医药|汽车|电子|半导体|能源|钢铁|地产|保险|基金|通信|'
        r'传媒|食品|饮料|家电|电气|化工|建材|航空|铁路|港口))'
    )
    cn_names = re.findall(cn_stock_pattern, text)
    found.extend(cn_names)

    # 知名公司中文名
    for name in _FAMOUS_COMPANIES:
        if name in text and name not in found:
            found.append(name)

    # 去重保持顺序
    seen = set()
    unique = []
    for s in found:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique


_NON_TICKER_WORDS = {
    "API", "CEO", "CFO", "CTO", "AI", "IPO", "ETF", "GDP", "CPI", "PMI",
    "USA", "USD", "CNY", "HKD", "EUR", "JPY", "A股", "港股", "美股",
    "OK", "ID", "IT", "OPEC", "IMF", "WTO", "WHO", "FBI", "CIA",
    "RSI", "MACD", "SMA", "EMA", "NYSE", "NASDAQ", "SEC",
    "WWDC", "CES", "MWC", "ASML", "TSMC",
    "GPU", "CPU", "PC", "VR", "AR", "MR", "XR",
    "HBM", "DRAM", "NAND", "SSD", "DDR", "LPDDR",
    "CAGR", "FY", "Q1", "Q2", "Q3", "Q4", "H1", "H2",
    "YOY", "QOQ", "MTD", "YTD", "EPS", "PE", "PB", "ROE",
}

_FAMOUS_COMPANIES = [
    "英伟达", "苹果", "特斯拉", "微软", "谷歌", "亚马逊", "Meta",
    "台积电", "英特尔", "AMD", "高通", "博通", "美光",
    "阿里巴巴", "腾讯", "百度", "京东", "网易", "拼多多", "美团",
    "字节跳动", "华为", "小米", "比亚迪", "宁德时代", "茅台",
    "贵州茅台", "五粮液", "中国平安", "招商银行", "工商银行",
    "甲骨文", "SAP", "Salesforce", "Adobe", "Palantir", "Snowflake",
    "摩根大通", "高盛", "摩根士丹利", "花旗", "富国银行",
    "波音", "洛克希德马丁", "雷神", "通用动力",
    "强生", "辉瑞", "默克", "艾伯维", "诺华",
    "宝洁", "可口可乐", "百事", "沃尔玛", "好市多",
    "埃克森美孚", "雪佛龙", "壳牌", "BP",
    "迪士尼", "Netflix", "Uber", "Airbnb", "Zoom",
]


def keyword_match(
    content: str,
    target_people: list[str],
    bullish_keywords: list[str],
) -> tuple[bool, list[str]]:
    """第一级关键词匹配。"""
    if not _match_any(content, target_people):
        return False, []
    if not _match_any(content, bullish_keywords):
        return False, []
    stocks = extract_potential_stocks(content)
    if not stocks:
        return False, []
    logger.info(f"关键词命中 → 股票候选: {stocks}")
    return True, stocks


# ── 第二级：AI 精判（DeepSeek）────────────────────────────────────

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# 输出 JSON Schema（嵌入 prompt 中让 DeepSeek 严格遵循）
OUTPUT_SCHEMA_DESC = """
你必须严格输出以下 JSON 格式，不要输出其他内容：
{
  "is_bullish_recommendation": true或false,
  "speaker": "黄仁勋"或"特朗普"或"other",
  "target_person_in_news": "黄仁勋"或"特朗普"或"both"或"other",
  "stock_name": "股票中文名如高通、英伟达"或null,
  "stock_code": "股票代码如QCOM.O、TSLA、000001、09988.HK"或null,
  "confidence": 0.0到1.0之间的数字,
  "summary": "一句话中文摘要"
}
"""

SYSTEM_PROMPT = f"""你是一个金融快讯语义分析器。分析输入的财经快讯，判断是否触发推送条件。

## 触发条件（必须同时满足）
1. 快讯中明确在看多/推荐/利好某只股票（is_bullish_recommendation=true）
2. 推荐动作的**发言者（speaker）**必须是黄仁勋或特朗普**本人**
3. 能识别出具体被推荐的股票名称和代码

## stock_name 和 stock_code 字段
- stock_name：股票中文名，如"高通"、"英伟达"、"特斯拉"
- stock_code：从原文提取的股票代码，优先取带交易所后缀的格式
  - 美股：QCOM.O、TSLA.O、AAPL.O、NVDA.O（注意原文如 QCOM.O 就原样保留）
  - A股：600519、000001
  - 港股：09988.HK、00700.HK
  - 若原文未出现代码则为 null

## 关键：speaker 归因
- "黄仁勋表示英伟达股价还能翻倍" → speaker="黄仁勋" ✅
- "特朗普发帖称某某股票被严重低估" → speaker="特朗普" ✅
- "分析师称黄仁勋看好的公司值得关注" → speaker="other" ❌（不是本人）
- "市场热议特朗普概念股大涨" → speaker="other" ❌（不是本人，也没有推荐）

## 置信度 confidence
- 0.9+: 原文非常明确，本人直接表态推荐
- 0.7-0.89: 可以推断但略有模糊
- 0.5-0.69: 不太确定
- <0.5: 基本不是

{OUTPUT_SCHEMA_DESC}"""


def ai_verify(
    content: str,
    time_str: str,
    api_key: str,
    model: str = "deepseek-chat",
) -> Optional[dict]:
    """使用 DeepSeek API 进行精确判断。

    Args:
        content: 快讯原文。
        time_str: 快讯时间。
        api_key: DeepSeek API Key。
        model: 模型名称，默认 deepseek-chat。

    Returns:
        判断结果 dict，若 API 调用失败则返回 None。
    """
    user_msg = f"快讯时间：{time_str}\n\n快讯内容：{content}" if time_str else content

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 512,
        "temperature": 0.0,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            DEEPSEEK_API_URL,
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        raw = data["choices"][0]["message"]["content"]
        result = json.loads(raw)

        logger.info(
            f"AI 判断: bullish={result.get('is_bullish_recommendation')}, "
            f"speaker={result.get('speaker')}, "
            f"stock={result.get('stock_name')}, "
            f"conf={result.get('confidence')}"
        )
        return result

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"DeepSeek 返回格式异常: {e} | raw: {raw[:200] if 'raw' in dir() else 'N/A'}")
        return None
    except Exception as e:
        logger.error(f"DeepSeek API 调用失败: {e}")
        return None


def should_trigger(result: dict, min_confidence: float = 0.7) -> bool:
    """根据 AI 判断结果，决定是否触发推送。"""
    if not result:
        return False
    return (
        result.get("is_bullish_recommendation", False)
        and result.get("speaker") in ("黄仁勋", "特朗普")
        and result.get("confidence", 0) >= min_confidence
    )
