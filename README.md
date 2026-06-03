# 金十监听 · Jin10 Monitor

实时监听金十数据快讯，当 **黄仁勋** 或 **特朗普** 公开推荐/看多某只股票时，通过 **Bark** 向 iPhone 发送推送通知。

## 工作原理

```
金十快讯 API ──→ 关键词粗筛 ──→ AI 精判 ──→ Bark 推送到 iPhone
  (每90秒)       (人名+股票+看多)   (确认是本人表态)
```

- **第一级**：关键词本地匹配 —— 零成本，毫秒级
- **第二级**：AI 精判（默认 DeepSeek）—— 区分"黄仁勋本人说"和"分析师提黄仁勋"，避免误报

## 快速开始

### 1. 环境要求

- Python 3.10+
- iPhone（安装 [Bark](https://apps.apple.com/app/id1403753865)）
- [DeepSeek API Key](https://platform.deepseek.com/)（可选，关闭 AI 后纯关键词模式也够用）

### 2. 安装

```bash
git clone https://github.com/YOUR_USERNAME/jin10-monitor.git
cd jin10-monitor
pip install -r requirements.txt
```

### 3. 配置

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

编辑 `config.yaml`，填入 Bark device_key（打开 Bark App 即可看到）：

```yaml
bark:
  device_key: "你的Bark设备Key"
```

编辑 `.env`，填入 API Key（可选）：

```
DEEPSEEK_API_KEY=sk-your-key-here
```

### 4. 运行

```bash
python main.py --test    # 测试一切是否正常（推荐首次运行）
python main.py           # 仪表盘模式，终端实时显示状态
python main.py --quiet   # 静默模式，纯后台运行
```

### 仪表盘预览

```
╔══════════════════════════════════════════╗
║  金十监听中 | 已运行: 2h15m23s           ║
╠══════════════════════════════════════════╣
║  最近轮询: 14:32:05  拉取 12 条快讯      ║
║  关键词命中: 2 条  AI确认: 1 条          ║
║  累计推送: 3 次                          ║
╠══════════════════════════════════════════╣
║  [14:15] ⚠️ 特朗普看好DJT                ║
║  [13:02] ⚠️ 黄仁勋看好NVDA               ║
╚══════════════════════════════════════════╝
```

## 配置说明

### `config.yaml`

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `bark.device_key` | Bark 设备 Key | 必填 |
| `bark.base_url` | Bark 服务地址 | `https://api.day.app` |
| `detection.poll_interval_seconds` | 轮询间隔（秒） | `90` |
| `detection.target_people` | 监听的人物列表 | `["黄仁勋", "特朗普", "Jensen Huang", "Trump"]` |
| `detection.bullish_keywords` | 看多信号词 | 见配置文件 |
| `ai.enabled` | 是否启用 AI 精判 | `true` |
| `ai.provider` | AI 服务商 | `deepseek` |
| `ai.model` | 模型名称 | `deepseek-chat` |
| `ai.min_confidence` | 置信度阈值 | `0.7` |

### 添加更多人物或关键词

编辑 `config.yaml` 中 `detection.target_people` 和 `detection.bullish_keywords`，支持任意人物和任意看多信号词。

## 项目结构

```
jin10-monitor/
├── main.py               # 入口，主循环 + 终端仪表盘
├── fetcher.py            # 金十快讯 HTTP API 封装
├── detector.py           # 关键词 + AI 两级检测
├── notifier.py           # Bark iPhone 推送
├── storage.py            # SQLite 去重
├── config.yaml.example   # 配置文件模板
├── .env.example          # 环境变量模板
├── .gitignore
└── requirements.txt
```

## 常见问题

**Q: 不想用 AI，纯关键词模式够用吗？**

够用。把 `config.yaml` 里 `ai.enabled` 设为 `false`。关键词模式能捕获大多数场景，AI 主要负责过滤"别人提及黄仁勋但他本人没表态"这类误报。

**Q: DeepSeek 费用？**

每条快讯仅几十字，一次判断消耗约 200 token。按 DeepSeek 定价，日常使用几乎免费。

**Q: Windows 能用吗？**

完全支持。Python 跨平台，后台运行用 `pythonw main.py --quiet`。

## 免责声明

本项目仅供学习研究使用，不构成投资建议。使用金十数据 API 请遵守其服务条款。
