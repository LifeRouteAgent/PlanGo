# Deployment

This project is deployed with Docker Compose from the repository root.

## 1. Prepare environment variables

Copy the example file and fill in real secrets:

```powershell
Copy-Item .env.example .env
```

The Docker deployment reads the root `.env` file automatically.

Required values:

| Purpose | Variable | Location |
|---|---|---|
| MySQL root password | `MYSQL_ROOT_PASSWORD` | `.env` |
| MinIO secret for Milvus | `MINIO_SECRET_KEY` | `.env` |
| DeepSeek API key | `DEEPSEEK_API_KEY` | `.env` |
| AMap Web/API key | `AMAP_API_KEY` | `.env` |
| AMap JS security code | `AMAP_SECURITY_JS_CODE` | `.env` |

## 2. LLM API configuration

The large model provider is configured in these files:

| Item | File |
|---|---|
| Docker runtime values | `.env` |
| Docker backend config shape | `backend/config.docker.json` |
| Local backend config example | `backend/config.example.toml` |
| Backend config loader | `backend/app/config.py` |

Current LLM variables:

```env
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_REASONING_EFFORT=high
DEEPSEEK_THINKING_ENABLED=false
```

`backend/app/config.py` reads config in this order:

1. `LIFEROUTE_CONFIG_PATH`
2. `backend/config.local.toml`
3. `backend/config.example.toml`

Docker sets `LIFEROUTE_CONFIG_PATH=/app/config.docker.json`, so containerized backend settings come from `backend/config.docker.json` plus environment variables from `.env`.

## 3. AMap configuration

Backend route planning uses:

```env
AMAP_API_KEY=
AMAP_ROUTE_ENABLED=true
```

Frontend map rendering uses:

```env
AMAP_API_KEY=
AMAP_SECURITY_JS_CODE=
```

The frontend Docker container writes these values to:

```text
/usr/share/nginx/html/app-config.json
```

The browser then reads:

```text
/app-config.json
```

Local Vite development can also use `frontend/.env.local` with:

```env
VITE_AMAP_JS_KEY=
VITE_AMAP_SECURITY_CODE=
```

## 4. Start services

```powershell
docker compose up -d --build
```

Services:

| Service | URL |
|---|---|
| Frontend | `http://127.0.0.1:5173` |
| Backend health | `http://127.0.0.1:8000/health` |
| Backend docs | `http://127.0.0.1:8000/docs` |
| MySQL | `127.0.0.1:3306` |
| Redis | `127.0.0.1:6379` |
| Milvus | `127.0.0.1:19530` |
| MinIO console | `http://127.0.0.1:9001` |

The frontend container serves built static assets through Nginx and proxies these paths to the backend:

```text
/api/*
/trip/*
/export/*
/health
```

## 5. Runtime data

Docker volumes:

| Volume | Purpose |
|---|---|
| `liferoute_mysql_data` | MySQL data |
| `liferoute_redis_data` | Redis data |
| `liferoute_etcd_data` | Milvus etcd data |
| `liferoute_minio_data` | Milvus object storage |
| `liferoute_milvus_data` | Milvus standalone data |
| `liferoute_backend_runtime` | Backend runtime files |

The backend container runs:

```text
python scripts/init_runtime_schema.py
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

So runtime MySQL tables are initialized during backend startup.

## 6. Useful commands

```powershell
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose down
```

To reset local deployment data:

```powershell
docker compose down -v
```
