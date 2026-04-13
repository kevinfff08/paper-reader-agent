# PaperReader

PaperReader 是一个本地优先的论文精读助手。它围绕 `session` 组织完整学习闭环：上传论文、生成初始分析、持续追问、补充检索、回读原文验证、最后生成归档报告。

当前仓库的重点不是“做一个会聊天的论文摘要器”，而是把这条链路跑通：

`session -> upload -> parse -> analyze / answer / archive -> evidence -> memory -> archive`

## 项目当前能力

- 创建 session，并按 session 管理论文、问答、运行记录和归档
- 上传一篇或多篇论文，解析为本地可检索内容
- 发起 `analyze`、`answer`、`archive` 三类 run
- 通过 SSE 向前端持续推送运行事件和增量输出
- 在 session 内做文献发现：
  - `latest_top_venues`
  - `seminal`
  - `related`
  - `supporting_context`
- 将发现到的文献本地化为 session reference，供后续问答和归档复用
- 对高风险问题执行 evidence gate：没有命中上传论文证据时，不允许直接完成回答
- 维护分层记忆：
  - `working memory`
  - `evidence ledger`
  - `compact summaries`
  - `library cards`
- 生成最终 Markdown 归档报告

## 真实性与资料策略

PaperReader 当前遵循这条优先级：

1. 先使用 session 内已经存在的本地证据
2. 不够时回读上传论文的解析结果
3. 再看已有 analysis、QA、localized references
4. 仍不够时做外部文献发现和补充检索
5. 新命中的有价值资料要本地化回 session

这也是代码里把“外部文献发现”和“session 内本地证据检索”分开的原因：

- `services/discovery/` 负责找外部文献
- `services/retrieval/` 只负责检索当前 session 已有内容

## 后端如何组织

后端按“主链路 + 基础设施 + 辅助能力”组织，目的是让目录一眼可读。

### 主链路

```text
main.py -> api/ -> runtime/ -> storage/
```

- `main.py`
  应用装配入口。只负责创建依赖和挂载路由，不承载业务逻辑。
- `api/`
  HTTP 边界层，处理请求和响应，并保留兼容接口。
- `runtime/`
  主 loop 所在位置。`RunEngine` 统一承载 analyze / answer / archive。
- `storage/`
  本地持久化层。session、run、memory、archive 都落在这里。

### 基础设施

- `core/`
  配置、共享模型、全局约束。这里也放了测试模式下的 session root 安全保护。
- `llm/`
  OpenAI / Claude / CLIProxy 风格接入。
- `logging/`
  session 级日志和应用日志。

### 辅助能力

```text
services/
  discovery/      外部文献发现与本地化
  parsing/        论文解析
  reporting/      归档报告生成
  retrieval/      session 内本地证据检索
  verification/   回答验证标签与门禁辅助
```

### 当前后端目录

```text
backend/app/
  api/
  core/
  llm/
  logging/
  runtime/
  services/
  storage/
  main.py
```

如果只想快速理解后端，建议先读这 4 个文件：

- [main.py](D:\Kevin\PhD\Project\ResearchTools\PaperReader\backend\app\main.py)
- [run_engine.py](D:\Kevin\PhD\Project\ResearchTools\PaperReader\backend\app\runtime\run_engine.py)
- [sessions.py](D:\Kevin\PhD\Project\ResearchTools\PaperReader\backend\app\api\routes\sessions.py)
- [session_store.py](D:\Kevin\PhD\Project\ResearchTools\PaperReader\backend\app\storage\session_store.py)

## 前端当前结构

前端是一个单工作区界面，围绕 session 展开：

- 左侧：session 与当前资料
- 中间：分析结果、发现结果、归档状态
- 下方或右侧：问答与 active runtime 事件

当前主要文件：

```text
frontend/src/
  WorkspaceScreen.tsx
  WorkspaceScreen.test.tsx
  api.ts
  types.ts
  styles.css
  main.tsx
```

## 本地数据如何组织

每个 session 都有独立目录：

```text
data/sessions/<session_slug>__<timestamp>/
  uploads/
  parsed/
  references/
  searches/
  analysis/
  qa/
  runs/
    <run_id>.json
    <run_id>.events.jsonl
    index.json
  archive/
  logs/
  memory/
    memory.md
    memory.json
    evidence/
      ledger.jsonl
    compact/
      summaries.json

data/sessions/_library/
  cards.json
```

## 快速开始

### 1. 准备环境

- Python 环境：`conda activate research_tools`
- 前端依赖：进入 `frontend/` 后执行 `npm install`

### 2. 配置环境变量

参考 [.env.example](D:\Kevin\PhD\Project\ResearchTools\PaperReader\.env.example)。常用变量包括：

```env
LLM_PROVIDER=openai
LLM_MODE=api-key
LLM_MODEL=
OPENAI_API_KEY=
CLAUDE_API_KEY=
LLM_PROXY_URL=http://localhost:8317

SEMANTIC_SCHOLAR_API_KEY=
OPENALEX_EMAIL=
TAVILY_API_KEY=

SESSION_DATA_ROOT=data/sessions
MAX_PARSE_CHARS=120000
```

### 3. 启动项目

默认只推荐一个启动命令：

```bat
start.bat
```

它会同时启动：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`

### 4. 运行测试

默认只推荐一个测试入口：

```bat
run_tests.bat
```

前端测试如果要单独运行，再进入 `frontend/` 执行：

```bash
npm run test
```

## 测试数据隔离规则

这个仓库现在对测试数据做了硬保护，不只是约定：

- 所有测试默认开启 `PAPERREADER_TEST_MODE=1`
- 测试 session root 必须落在 `.tmp-tests/` 之类的隔离目录
- 如果测试模式下 `SESSION_DATA_ROOT` 指向正式 `data/sessions`，`SessionStore` 会直接报错
- 测试不能污染正式 session 数据

## 开发规范摘要

- 新实现替换旧实现时，要在同一次改动里清理旧代码
- 不保留失效的双轨实现、废弃 UI、过时测试
- 目录分工必须保持清晰：
  - `api/` 是接口层
  - `runtime/` 是主 loop
  - `storage/` 是持久化
  - `llm/` 和 `logging/` 是基础设施
  - `services/` 是辅助能力
- 影响结构、接口、运行流的改动，要同步更新：
  - [README.md](D:\Kevin\PhD\Project\ResearchTools\PaperReader\README.md)
  - [AGENT.md](D:\Kevin\PhD\Project\ResearchTools\PaperReader\AGENT.md)
  - [product_spec.md](D:\Kevin\PhD\Project\ResearchTools\PaperReader\product_spec.md)
  - [system_architecture.md](D:\Kevin\PhD\Project\ResearchTools\PaperReader\system_architecture.md)
