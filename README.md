# PaperReader

PaperReader 是一个面向博士生和研究者的本地优先论文阅读助手。  
它围绕 `session` 组织一次完整的论文学习过程：上传一篇或多篇论文，生成初始深度分析，支持继续追问，在回答过程中回读本地原文并按需补查外部资料，最后把分析、问答和补充材料整理成一份可归档的 Markdown 报告。

## 项目定位

读论文时，真正困难的部分通常不是“生成一个摘要”，而是下面这些事情同时做好：

- 把论文读深，理解问题定义、方法细节、实验设计、局限与相关工作
- 在追问时不脱离原文，不靠模糊记忆回答
- 当本地材料不够时，继续补查可靠的学术资料
- 把补查到的资料纳入当前学习上下文，而不是散落在聊天记录里
- 学习结束后形成可复用、可归档、可回看的完整文档

PaperReader 的目标，就是把这条链路做成一个稳定的本地工作流。

## 核心能力

- 以 `session` 为核心组织一次论文学习过程
- 上传一篇或多篇论文到同一个 session
- 生成单篇分析和跨论文综合分析
- 在同一个工作区里继续提问
- 回答时优先检索本地已有分析、记忆文档和本地化参考资料
- 在必要时补查外部学术资料，并把命中资料本地化保存
- 维护每个 session 的 `memory.md`
- 生成包含分析、问答、补充资料与记忆摘要的 Markdown 归档报告

## 一次典型使用流程

1. 创建一个 session，并填写 `session_name`
2. 上传一篇或多篇论文
3. 系统解析论文并生成初始深度分析
4. 你在工作区里继续追问概念、方法、实验、局限或相关工作
5. 系统优先检索本地材料，不够时再补查外部学术来源
6. 命中的有效资料会被保存到当前 session
7. 学习完成后，点击生成归档报告
8. 系统输出一份 Markdown 文档，汇总本次学习过程

## 文献查阅与真实性原则

这部分不是附属功能，而是整个项目最重要的约束之一。

### 1. 先本地，后外部

回答问题时，系统默认先使用当前 session 内已经存在的材料：

- 上传论文的解析结果
- 已生成的分析产物
- 历史问答记录
- `memory.md`
- 已本地化保存的 references

这样做的目的，是让回答始终围绕你真正读过的材料展开，而不是每次追问都重新发散搜索。

### 2. 高风险问题优先回读原文

如果问题涉及方法细节、实验设置、边界条件、对比基线、局限性等高风险信息，系统应优先回读上传论文的本地解析结果，而不是只复述先前总结。

### 3. 外部检索坚持学术源优先

当本地材料仍不足以支撑回答时，V1 的外部检索顺序是：

1. `Semantic Scholar`
2. `OpenAlex`
3. 补充性网页检索

这套顺序参考了 `DailyReport` 中“稳定来源优先、开放网页补充”的思路，也更符合论文阅读场景中的可靠性要求。

### 4. 新资料必须本地化

外部检索命中的有效资料不会只停留在当次回答里，而会被保存到当前 session，后续回答和最终归档都可以继续使用。

### 5. 网页检索只做补充

网页检索可以帮助找到博客、项目页、作者说明、补充实现资料，但它不应天然高于原始论文和学术索引。因此在 V1 中，网页检索始终是补充通道，不是主证据来源。

## 系统概览

PaperReader V1 采用 `React + FastAPI` 的本地优先结构，前后端职责分离。

### 前端工作区

前端提供两个核心页面：

- `Session 列表页`
- `Session 工作区页`

其中 `Session 工作区页` 集中展示：

- 当前 session 的论文与参考资料
- 初始分析与跨论文综合分析
- 追问对话区
- 当前回答使用了哪些本地资料、补查了哪些外部资料
- 归档报告生成入口

### 后端分层

后端按能力分层，而不是把逻辑堆在单个服务文件里。主要模块包括：

- `api/`：FastAPI 路由
- `orchestrator/`：分阶段编排器
- `llm/`：OpenAI / Claude 与 CLIProxy / 原始 API 双轨接入
- `parsers/`：论文与文本解析
- `retrieval/`：本地检索与外部检索
- `verification/`：回答前后的本地回读与验证
- `reports/`：归档 Markdown 生成
- `storage/`：session 目录与产物持久化
- `models/`：领域模型
- `logging/`：session 级日志

### 执行流程

V1 不是“一个 prompt 跑到底”，而是固定阶段式流程：

1. `Parse`：解析上传论文与补充资料
2. `Plan`：生成学习大纲与分析子任务
3. `Analyze`：产出初始分析
4. `Answer`：处理用户追问
5. `Verify`：必要时回读本地材料并补检索外部资料
6. `Archive`：整理分析、问答、参考资料与记忆，生成归档报告

## 快速开始

### 1. 环境准备

- Windows 本地开发环境
- Conda 环境：`research_tools`
- Node.js 18 或更高版本

### 2. 安装依赖

先安装后端依赖：

```bash
conda activate research_tools
pip install -e .[dev]
```

再安装前端依赖：

```bash
cd frontend
npm install
```

### 3. 配置环境变量

复制模板：

```bash
copy .env.example .env
```

常用配置项如下：

```env
# LLM
LLM_PROVIDER=openai
LLM_MODE=api-key
LLM_MODEL=
OPENAI_API_KEY=
CLAUDE_API_KEY=
LLM_PROXY_URL=http://localhost:8317

# Retrieval
SEMANTIC_SCHOLAR_API_KEY=
OPENALEX_EMAIL=
TAVILY_API_KEY=

# App
SESSION_DATA_ROOT=data/sessions
MAX_PARSE_CHARS=120000
```

说明：

- `LLM_PROVIDER` 支持 `openai` 与 `claude`
- `LLM_MODE` 支持直连 API key，也支持对齐 `DailyReport` 的双轨接入方式
- `LLM_PROXY_URL` 用于 CLIProxy / setup-token 风格接入
- `SEMANTIC_SCHOLAR_API_KEY` 用于提升 Semantic Scholar 访问能力
- `OPENALEX_EMAIL` 用于 OpenAlex 的联系标识
- `TAVILY_API_KEY` 是补充性网页检索所需，可选

### 4. 启动项目

为了避免开发入口过多，默认只保留一个推荐启动命令。

```bat
start.bat
```

它会同时启动：

- FastAPI 后端
- React 前端开发服务器

默认地址：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`

如果你在排查问题，也可以手动启动：

后端：

```bash
conda activate research_tools
uvicorn backend.app.main:app --reload
```

前端：

```bash
cd frontend
npm run dev
```

### 5. 运行测试

后端测试：

```bash
conda activate research_tools
pytest tests -v
```

如果只想快速执行测试，也可以运行：

```bat
run_tests.bat
```

## 仓库结构

```text
backend/
  app/
    api/             FastAPI 路由
    llm/             OpenAI / Claude / CLIProxy 封装
    logging/         session 日志
    models/          领域模型与 API 模型
    orchestrator/    分阶段编排器
    parsers/         文档解析
    reports/         归档报告生成
    retrieval/       本地检索与外部检索
    storage/         session 持久化
    verification/    真实性验证

frontend/
  src/               React 工作区前端

docs/
  implementation-plan.md
  reference/         调研资料与历史参考文档

AGENT.md             项目长期约束与开发规则
product_spec.md      产品定义
system_architecture.md 系统设计说明
```

## 本地数据组织

每个 session 都会在本地创建独立目录，目录结构如下：

```text
data/sessions/<session_slug>__<timestamp>/
  uploads/      原始上传论文
  parsed/       解析结果
  references/   额外检索并本地化保存的资料
  analysis/     初始分析与综合分析
  qa/           问答记录
  memory/       session 记忆文档
  archive/      最终归档报告
  logs/         当前 session 日志
```

这也是长期记忆、可追溯性和归档能力的基础。

## 当前实现状态

V1 当前已经具备基础闭环：

- session 创建
- 论文上传
- 初始分析
- 问答
- 外部资料补查
- 归档报告生成

当前仍值得继续增强的部分包括：

- 更强的 PDF 结构解析能力
- 更细粒度的证据引用与页码定位
- 更强的多篇论文综合能力
- 更完善的前端交互与可视化
- 更强的长期记忆策略

## 阅读顺序建议

如果你是后续开发者，建议按这个顺序进入项目：

1. `AGENT.md`
2. `README.md`
3. `docs/implementation-plan.md`
4. `product_spec.md`
5. `system_architecture.md`

## 补充说明

- `AGENT.md` 是本项目的长期约束文件，开发时必须遵守
- `docs/reference/` 下保留调研资料和历史启动材料，方便回看，但不作为日常入口
- 如果你想继续增强文献获取策略，优先考虑“本地优先、学术源优先、网页补充、命中即本地化”这条主线，不要把系统做成泛搜索聊天器
