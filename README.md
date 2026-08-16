# 智能数据分析助手

上传 CSV / XLSX，用自然语言提问，自动完成数据画像、分析、可视化与 Markdown 报告。对外提供 FastAPI 接口。

处理流程：规划 → 分析 → 出图 → 写报告 → 复核。复核对照 findings 和图表看报告有没有无依据的数字；未通过会回到写报告、出图或分析再跑，次数由 CRITIC_MAX_ROUNDS 限制。

## 功能概览

- 基于 **LangGraph** 多阶段编排：规划 / 分析 / 出图 / 报告 / 复核，共享任务状态
- **OpenAI 兼容 SDK** 调模型；分析侧 ReAct 风格 Tool Calling + 自研 Pandas/画图工具
- 支持 CSV、XLSX；报告绑定数据证据，复核未通过会按阶段打回
- 单次分析与会话追问（同一份数据多轮提问）
- 可选 Celery + Redis 异步队列与任务状态持久化
- 可选 MinIO/S3 对象存储；本地盘亦可运行
- Prometheus 指标、就绪探针；工具层评测脚本。Celery 模式下任务次数/耗时看 Worker 端口（默认 9091），API 的 `/metrics` 是 API 进程本身

## 架构（Celery 模式）

```text
Client → FastAPI(api) → Redis(Broker + JobState)
                ↓
         Celery Worker → LangGraph Orchestrator → 本地盘 / MinIO
```

## 项目结构

```text
Data_Analysis_Agent/
├── src/
│   ├── agents/               # 提示词与 AgentRunner（OpenAI + Tools）
│   ├── api/                  # 接口路由、鉴权、文档
│   ├── core/                 # LangGraph 编排、任务存储、缓存、指标
│   ├── infrastructure/       # 对象存储抽象（local / s3）
│   ├── worker/               # Celery app 与任务
│   ├── tools/                # 自研 Tool 协议 + 读表/聚合/画图/写报告
│   ├── utils/
│   ├── data/                 # 样例数据
│   ├── config.py
│   └── state.py
├── scripts/                  # cleanup_expired / run_eval
├── evals/                    # 离线评测用例
├── tests/
├── docker-compose.yml
├── Dockerfile
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

## 快速开始

### 方式 A：本地最简

```bash
pip install -r requirements.txt
# 配置 .env：LLM_API_KEY、API_KEYS；TASK_BACKEND=memory、STORAGE_BACKEND=local
python main.py
```

### 方式 B：Docker Compose

```bash
# 先配置 .env 的 LLM_API_KEY
docker compose up -d --build
```

- 文档：http://127.0.0.1:8000/docs
- MinIO 控制台：http://127.0.0.1:9001 （默认 minioadmin / minioadmin）

单独起 Worker（本机已有 Redis 时）：

```bash
celery -A src.worker.celery_app.celery_app worker -Q analysis -c 2 -l INFO
# Windows 可加：--pool=solo
```

就绪后日志会出现 `worker_metrics_listening http://127.0.0.1:9091/`。浏览器打开该地址可看 `analyst_jobs_total` 等；端口由 `.env` 的 `WORKER_METRICS_PORT` 配置，`0` 关闭。计数只含当前 Worker 进程启动之后跑完的任务（命中结果缓存的不会加）。

### 清理与评测

```bash
python -m scripts.cleanup_expired
python -m scripts.run_eval
pytest tests/test_tools.py -q
```

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活 |
| GET | `/readyz` | 就绪 |
| GET | `/metrics` | API 进程指标；`TASK_BACKEND=memory` 时任务计数在此。Celery 模式请看 Worker 的 9091 |
| POST | `/api/v1/analyze` | 单次分析（上传文件 + 问题） |
| POST | `/api/v1/sessions` | 创建会话（上传文件，可选第一问） |
| POST | `/api/v1/sessions/{id}/ask` | 同一份数据上继续追问 |
| GET | `/api/v1/sessions/{id}` | 查看会话历史 |
| GET | `/api/v1/jobs/{job_id}` | 查询任务进度（含复核结果） |
| GET | `/api/v1/jobs/{job_id}/report` | 下载报告 |
| GET | `/api/v1/jobs/{job_id}/charts/{name}` | 下载图表 |

鉴权：Swagger 右上角 Authorize，填入 `.env` 中 `API_KEYS` 的值。

### 多轮追问示例

1. `POST /api/v1/sessions`：上传 `src/data/sample_sales.csv`，可填第一问
2. 记下 `session_id`；有 `job_id` 则轮询至 `succeeded`
3. `POST /api/v1/sessions/{session_id}/ask`，body：`{"question":"那只看 East 区域呢？"}`
4. 用新的 `job_id` 下载报告；用 `GET /sessions/{id}` 查看历史

分析结果默认写在 `outputs/reports/` 与 `outputs/charts/`。每单报告为 `report_{job_id}.md`，复核重写会覆盖同一文件。
