# Review Agent v1.1

FastAPI + SQLite 实现的单用户复习 Agent：

- 基于知识点生成简答题（多模型可切换）
- 用户逐题作答
- 评分 + 纠错 + 关键要点（严格 JSON Schema）
- 记录掌握度（0-5 星）
- 按 1/2/4/7/15/30 天 + 掌握度因子自适应排期
- 每天 09:30（Asia/Shanghai）发送 1 封汇总提醒邮件

## 多模型能力

- 支持 Provider：`openai`、`deepseek`、`glm`、`mock`
- 出题和评分分离配置：`question_*` 与 `grading_*`
- 单次模型请求最多重试 3 次（指数退避）
- 同一任务类型连续 3 次失败触发 Gmail 告警（按任务类型计数）

## 快速启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

启动后可访问：

- `http://localhost:8000/review`：逐题复习页面
- `http://localhost:8000/admin/knowledge-points`：后台知识点页面（单条/批量录入 + 编辑 + 删除）

## Docker 部署（推荐服务器使用）

1. 准备环境文件

```bash
cp .env.docker.example .env
```

按你的实际情况修改 `.env`（至少要改邮箱与 SMTP 配置）。

2. 构建并启动

```bash
docker compose up -d --build
```

3. 查看运行状态

```bash
docker compose ps
docker compose logs -f review-agent
```

4. 访问应用

- `http://<服务器IP>:8000/review`
- `http://<服务器IP>:8000/admin/knowledge-points`

5. 常用运维命令

```bash
docker compose restart review-agent
docker compose down
docker compose up -d
```

说明：

- SQLite 数据文件存放在 Docker Volume `review-agent-data`，容器重建后数据仍保留。
- 当前服务包含 APScheduler 定时任务（每日 09:30 邮件提醒），请保持单实例运行，避免重复发送。

## 关键配置（环境变量）

- `DATABASE_URL` 默认 `sqlite:///./review_agent.db`
- `APP_ENV` 设为 `test` 可禁用调度器
- `APP_TIMEZONE` 默认 `Asia/Shanghai`
- `REVIEW_ENTRY_URL` 邮件中的复习入口（默认 `http://localhost:8000/review`）
- `OPENAI_API_KEY` / `OPENAI_BASE_URL`（可选，默认 `https://api.openai.com/v1`）
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`（可选，默认 `https://api.deepseek.com/v1`）
- `GLM_API_KEY` / `GLM_BASE_URL`（可选，默认 `https://open.bigmodel.cn/api/paas/v4`）
- `MODEL_FAILURE_ALERT_COOLDOWN_HOURS`（默认 `6`）
- `RECIPIENT_EMAIL`（提醒邮件收件人）
- `SMTP_FROM`（发件人）
- `SMTP_USER`（Gmail 登录账号）
- `SMTP_APP_PASSWORD`（Gmail 应用专用密码）
- `SEND_EMPTY_DIGEST`（`1` 表示无到期项也发送提醒）

你也可以在项目根目录放 `.env`，启动时会自动读取，例如：

```env
APP_ENV=dev
DATABASE_URL=sqlite:///./review_agent.db
APP_TIMEZONE=Asia/Shanghai
REVIEW_ENTRY_URL=http://localhost:8000/review

RECIPIENT_EMAIL=you@example.com
SMTP_FROM=your_gmail@gmail.com
SMTP_USER=your_gmail@gmail.com
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx
SEND_EMPTY_DIGEST=0
```

## 常用 API

- `POST /api/knowledge-points`
- `POST /api/knowledge-points/import`
- `GET /api/review/due`
- `POST /api/review/session/start`
- `POST /api/review/session/{id}/answer`
- `POST /api/reminder/run-daily`
- `GET /api/models/providers`
- `POST /api/settings/models`
- `POST /api/settings/model`（兼容旧接口，deprecated）
- `POST /api/settings/email`
