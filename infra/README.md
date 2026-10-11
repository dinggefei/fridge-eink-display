# 本地基础设施

本项目使用 PostgreSQL 16 保存用户、家庭空间、库存和设备绑定关系。

安装并启动 Docker Desktop 后，在项目根目录执行：

```bash
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml ps
```

数据库仅监听本机 `127.0.0.1:5432`。开发用户名、密码和数据库名都是 `rfm`，
只适用于本机开发，正式部署必须替换。

首次启动数据库后执行迁移：

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期当前版本为 `0003_recognition_tasks (head)`。

正式服务器部署使用 `production/` 目录，具体步骤见
[`production/README.md`](production/README.md)。本地开发与正式环境使用独立
的 Compose 配置和数据卷，避免误操作本地数据库。
