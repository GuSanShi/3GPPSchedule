# 3GPP 日程查看器

从 3GPP FTP 服务器下载最新会议日程 DOCX 文件,用 DeepSeek(Gemini 亦可)解析非结构化表格文本,生成 **CSS Grid 甘特图风格的静态 HTML 页面**。

## 主要功能

- 从 3GPP FTP 自动下载最新日程 DOCX(支持 ZIP 内文档自动解压)
- **多来源日程整合**:自动发现并下载 Chair_notes 之外副议长(Hiroki、Sorour 等)目录的日程
- **会议优先级识别**:常规会议按 `RAN1#124 < RAN1#124bis < RAN1#125` 排序比较,非常规会议(AH/e 等)按上传时间判断
- `python-docx` 提取表格结构并处理合并单元格(TextBox 颜色匹配房间)
- DeepSeek API 将非结构化文本转换为结构化会议数据(结果缓存)
- **多来源交叉引用**:同一时间段的多个日程表在一次 LLM 调用中整合,推导出最详细的会议信息(如 AI 编号)
- **会议时区自动检测**:从 Chair notes DOCX 提取举办地信息,自动设置 IANA 时区
- 按天 tab 切换、自动选中今天日期的单页 HTML 甘特图(分组配色、自动刷新、NOW 红线)
- GitHub Actions 自动构建与 GitHub Pages 部署(每天 07:00 / 14:00 / 21:00 阿姆斯特丹时间固定检测,有变更才重建)

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- DeepSeek API Key(任意 OpenAI 兼容端点亦可,见下文)

## 安装

```bash
git clone https://github.com/<你的用户名>/3GPPSchedule.git
cd 3GPPSchedule
uv sync
```

## 环境配置

在项目根目录创建 `.env` 文件:

```bash
cp .env.example .env
```

```dotenv
DEEPSEEK_API_KEY=your-api-key-here
SCHEDULE_CONTACT_NAME=Your Name
SCHEDULE_CONTACT_EMAIL=your.email@example.com
```

- `DEEPSEEK_API_KEY`:DeepSeek API Key(默认使用;未设置时回退 `GEMINI_API_KEY`)
- `SCHEDULE_CONTACT_NAME`:生成的 HTML 中显示的联系人姓名
- `SCHEDULE_CONTACT_EMAIL`:生成的 HTML 中显示的联系人邮箱

也可改用其他 OpenAI 兼容端点:`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 环境变量(见 `deepseek_llm.py`)。

## 使用方法

### 完整流水线(下载 → 解析 → 生成 HTML)

```bash
uv run python main.py
```

从 3GPP FTP 下载最新日程文件,解析后生成 `docs/index.html`。

### 使用本地 DOCX 文件

```bash
uv run python main.py --local "Chair_notes/RAN1#124 online and offline schedules - v00.docx"
```

### 跳过下载

```bash
uv run python main.py --no-download
```

### 指定输出路径

```bash
uv run python main.py --output output/schedule.html
```

默认输出路径为 `docs/index.html`。

## CLI 选项

| 选项 | 说明 |
|---|---|
| (无) | FTP 下载 → 解析 → 生成 HTML 完整流水线 |
| `--local <path>` | 用指定本地 DOCX 生成 HTML |
| `--no-download` | 不下载,使用最新本地文件 |
| `--output <path>` | HTML 输出路径(默认 `docs/index.html`) |
| `--rebuild-slots` | 清空 `docs/slot_state/` 后全量冷重建 |

## 更新机制

- GitHub Actions 每天 **07:00 / 14:00 / 21:00(阿姆斯特丹时间,UTC+2)** 触发一次检测,对应 UTC 05:00 / 12:00 / 19:00
- `check_update.py` 轻量拉取 FTP 目录列表,与 `docs/.schedule_state.json` 缓存对比(文件名 + 上传时间)
- **有变更才重建部署**;无变更直接跳过,节省 Actions 分钟数
- 手动触发:仓库 `Actions` 页面 → `Build and Deploy Schedule` → `Run workflow`,可选:
  - `check-build-deploy`:变更检测,有变化才构建
  - `build-deploy`:跳过检测,保留缓存重建
  - `force-deploy`:清空缓存后全量重建
  - `deploy-only`:不构建,直接部署当前 `docs/`

## 项目结构

```
main.py                # CLI 入口,整体流水线编排
downloader.py          # 3GPP FTP 日程 DOCX 下载(多目录发现、ZIP 自动解压)
parser.py              # python-docx 表格结构提取(TextBox 颜色匹配、会议地点提取)
merger.py              # 多来源日程数据按 (day, time_block) 聚合
session_parser.py      # DeepSeek API 将单元格文本解析为结构化会议数据(时区检测、房间匹配、分组归一化)
models.py              # 数据模型(Session、DaySchedule、Schedule、ScheduleSource 等)
generator.py           # CSS Grid 甘特图 HTML 生成(分组配色、自动刷新、房间角色后缀)
slot_state.py          # 增量合并的持久化状态(按时间块缓存 LLM 结果)
check_update.py        # GitHub Actions 变更检测(轻量 FTP 对比)
deepseek_llm.py        # OpenAI 兼容 LLM 封装(DeepSeek 等)
agenda_descriptions.py # 议程描述提取(从 TDoc xlsx)
```

## 增量解析说明

- 每个 (day, time_block) 的 LLM 解析结果缓存在 `docs/slot_state/`,按来源内容哈希判断
- 来源未变化 → 直接复用缓存(0 次 LLM 调用)
- 部分变化 → 增量提示词只更新变化部分
- 会议切换(meeting_id 变化)→ 自动冷重建
- 需要强制重建:运行 `uv run python main.py --rebuild-slots`,或在 GitHub 网页上删除 `docs/slot_state/` 中对应日期的 JSON 文件
