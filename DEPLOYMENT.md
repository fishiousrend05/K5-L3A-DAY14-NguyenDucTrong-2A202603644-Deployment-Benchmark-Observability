# Deployment — Day 14: Production AI Agent

## 1. Thông tin triển khai

- **Nền tảng:** Render (Web Service + Render Key Value / Redis)
- **Public URL:** https://day14-ai-agent-qscp.onrender.com
- **Thư mục nguồn:** `06-lab-complete/`
- **Runtime:** Docker (multi-stage `python:3.11-slim`, non-root user, image size ~238 MB)
- **Health check path:** `/health`
- **File cấu hình hạ tầng:** `06-lab-complete/render.yaml` (kèm `06-lab-complete/railway.toml`)

## 2. Biến môi trường đã cấu hình trên Render Dashboard

| Biến môi trường | Mô tả | Cách cấu hình |
| --- | --- | --- |
| `AGENT_API_KEY` | API key xác thực header `X-API-Key` | Đặt trực tiếp trên Render Environment (secret, không lưu trong repo) |
| `REDIS_URL` | Internal Key Value URL kết nối dịch vụ Redis cùng region | Đặt trực tiếp trên Render Environment |
| `ENVIRONMENT` | Môi trường chạy | `production` |
| `RATE_LIMIT_PER_MINUTE` | Giới hạn request/phút theo API key | `10` |
| `DAILY_BUDGET_USD` | Ngân sách tối đa mỗi ngày (USD) | `1.0` |
| `PORT` | Cổng lắng nghe HTTP | Do Render tự động cấp phát |

## 3. Kiểm thử endpoints sau khi deploy

```bash
BASE="[https://day14-ai-agent-qscp.onrender.com](https://day14-ai-agent-qscp.onrender.com)"

# 1. Liveness probe -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "\$BASE/health"

# 2. Readiness probe (kiểm tra kết nối Redis) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "\$BASE/ready"

# 3. Gọi /ask không có API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "\$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có X-API-Key hợp lệ -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "\$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: \$AGENT_API_KEY" \
  -d '{"question":"Hello"}'