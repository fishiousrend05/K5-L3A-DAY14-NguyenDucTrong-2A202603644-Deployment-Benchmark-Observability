# Day 14 Lab — Mission Answers

- **Student Name:** Nguyễn Đức Trọng
- **Student ID:** 2A202603644
- **Class:** K5-L3A
- **Date:** 2026-11-25

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn (dòng 16–17):** Gán trực tiếp `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub, toàn bộ secret bị lộ ngay lập tức. Bản `production/app.py` đã khắc phục bằng cách đọc toàn bộ cấu hình từ biến môi trường qua `config.py`.
2. **Không quản lý cấu hình theo môi trường (dòng 20–21):** Khai báo cứng `DEBUG = True`, `MAX_TOKENS = 500` trong code thay vì dùng environment variables theo nguyên tắc 12-Factor App.
3. **Dùng `print()` và ghi log lộ secret (dòng 31–35):** Gọi `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa làm rò rỉ API key ra stdout, vừa không thể lọc/phân tích log tập trung. Bản `production/app.py` (dòng 29–32, 95–107) chuyển sang structured JSON logging bằng module `logging` và tuyệt đối không log secret.
4. **Thiếu health check và readiness endpoint:** Bản `develop` chỉ có `/` và `/ask`, khiến nền tảng cloud hoặc load balancer không biết container còn sống hay đã sẵn sàng nhận traffic. Bản `production/app.py` đã bổ sung `GET /health` (dòng 124) và `GET /ready` (dòng 142).
5. **Bind `localhost`, cố định port, bật `reload=True` và không có graceful shutdown (dòng 43–49):** Dùng `host="localhost"` khiến container không nhận được kết nối từ bên ngoài; cố định `port=8000` bỏ qua biến `PORT` do nền tảng cloud cấp; bật `reload=True` gây tốn tài nguyên và thiếu cơ chế xử lý `SIGTERM` / `lifespan` (bản `production/app.py` khắc phục tại dòng 39–63 và dòng 164–180).

### Exercise 1.2: Kết quả chạy bản `develop`

```text
POST http://localhost:8000/ask?question=Hello
-> HTTP/1.1 200 OK
{"answer": "[Mock LLM] ..."}
```

Bản `develop` chạy được trên máy cá nhân nhưng không an toàn và chưa sẵn sàng cho production do lộ secret, chỉ nghe trên `localhost` và thiếu cơ chế kiểm tra sức khỏe cũng như tắt an toàn.

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Why Important? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True` trực tiếp trong code | Đọc từ environment variables qua `config.py` (12-Factor) | Ngăn lộ secret trên Git và cho phép thay đổi cấu hình theo từng môi trường (dev/staging/prod) mà không sửa code |
| **Network & Port** | `host="localhost"`, cố định `port=8000`, `reload=True` | `host="0.0.0.0"`, đọc từ biến `PORT`, tắt `reload` ở production | Container cần bind `0.0.0.0` và dùng cổng động do nền tảng cloud (Render/Railway) cấp mới nhận được request từ bên ngoài |
| **Health Checks** | Không có `/health` hay `/ready` | Có `GET /health` (liveness) và `GET /ready` (readiness, trả 503 khi chưa sẵn sàng) | Giúp orchestrator biết khi nào cần restart container bị treo và giúp load balancer chỉ định tuyến traffic tới instance sẵn sàng |
| **Logging** | Dùng `print()`, in thẳng API key ra console | Structured JSON logging qua `logging`, không ghi thông tin nhạy cảm | Dễ parse và truy vấn trên các hệ thống thu thập log (Loki, Datadog, Cloud Logging) và đảm bảo bảo mật |
| **Shutdown** | Dừng đột ngột khi process bị ngắt | Quản lý vòng đời bằng `lifespan` và xử lý tín hiệu `SIGTERM` | Hoàn thành các request đang xử lý (in-flight requests) và đóng kết nối sạch sẽ trước khi thoát, tránh lỗi 502 cho người dùng |

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (ở bản develop) — image Python đầy đủ chứa sẵn nhiều gói tiện ích hệ điều hành Debian nên dung lượng lớn. Bản production chuyển sang `python:3.11-slim` để loại bỏ các gói không cần thiết.
2. **Working directory:** `/app` (`WORKDIR /app`) — thiết lập thư mục làm việc mặc định bên trong container, tách biệt mã nguồn ứng dụng khỏi thư mục gốc của hệ điều hành.
3. **Tại sao `COPY requirements.txt .` phải đứng trước `COPY . .`:** Để tận dụng cơ chế **layer caching** của Docker. Danh sách thư viện (`requirements.txt`) ít thay đổi hơn mã nguồn `.py`; khi chỉ sửa code ứng dụng, Docker tái sử dụng lớp cache `pip install` thay vì tải và cài lại toàn bộ dependencies từ đầu.
4. **Sự khác nhau giữa `CMD` và `ENTRYPOINT`:** `ENTRYPOINT` cố định chương trình thực thi chính luôn chạy khi container khởi động, còn `CMD` chỉ định lệnh hoặc bộ tham số mặc định có thể dễ dàng ghi đè khi truyền thêm đối số vào `docker run`.

### Exercise 2.2 & 2.3: Multi-stage build và so sánh kích thước image

- **Cơ chế tối ưu của multi-stage build (`02-docker/production/Dockerfile`):**
  - **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài đặt công cụ biên dịch (`gcc`, `libpq-dev`) và cài đặt các gói Python vào `/root/.local`.
  - **Stage 2 (`runtime`):** Tạo lớp sạch mới từ `python:3.11-slim`, tạo user non-root `appuser`, chỉ `COPY --from=builder` thư mục `/root/.local` và mã nguồn cần chạy sang, bỏ lại hoàn toàn `gcc`, header thư viện và cache build ở Stage 1.
- **Kết quả đo thực tế bằng `docker images`:**
  - `agent-dev:latest` (single-stage, `python:3.11`): **1.67 GB** (~1,670 MB)
  - `agent-prod:latest` (multi-stage, `python:3.11-slim`): **240 MB**
  - **Chênh lệch:** Giảm **~1,430 MB** (**85.6%** dung lượng)

### Exercise 2.4: Kiến trúc Docker Compose (`02-docker/production/`)

```text
┌────────┐      HTTP :80      ┌───────────────┐     HTTP :8000     ┌──────────────────┐
│ Client │ ─────────────────▶ │ Nginx (Proxy) │ ─────────────────▶ │ FastAPI Agent    │
└────────┘                    └───────────────┘                    └──────────────────┘
```

- **Các service khởi chạy:** `nginx` (reverse proxy mở cổng `80` ra bên ngoài) và `agent` (FastAPI chạy nội bộ trên cổng `8000`). Hai container giao tiếp với nhau qua mạng nội bộ của Docker Compose thông qua tên service (`http://agent:8000`).
- **Kết quả kiểm thử qua Nginx:** Gọi `GET http://localhost/health` và `POST http://localhost/ask` qua cổng `80` của Nginx đều định tuyến thành công tới `agent` và trả về `HTTP 200 OK`.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Triển khai Agent Part 6 lên Render

- **Nền tảng chính:** Render (Web Service Docker + Render Key Value / Redis)
- **Public URL:** https://day14-ai-agent-qscp.onrender.com
- **Kết quả kiểm thử 4 endpoint bắt buộc:**
  - `GET /health` → `200`
  - `GET /ready` → `200`
  - `POST /ask` (không có `X-API-Key`) → `401`
  - `POST /ask` (có `X-API-Key` hợp lệ) → `200`
- **Screenshots:**
  - [Dashboard & Environment Variables](screenshots/dashboard.png)
  - [Service Running & Logs](screenshots/running.png)
  - [Endpoint Test Results](screenshots/test.png)

### So sánh `railway.toml` và `render.yaml`

- **Cấu trúc và mức độ khai báo:** `railway.toml` viết theo định dạng TOML, tập trung khai báo cách build (`builder = "DOCKERFILE"`, `dockerfilePath`) và chính sách chạy (`healthcheckPath = "/health"`, `restartPolicyType`) cho từng service riêng lẻ; biến môi trường và liên kết Redis thường cấu hình qua Railway Dashboard hoặc CLI (`${{Redis.REDIS_URL}}`). Trong khi đó, `render.yaml` là file Blueprint YAML mang tính Infrastructure-as-Code đầy đủ hơn, khai báo danh sách dịch vụ (`services:`), loại dịch vụ (`type: web`), `healthCheckPath: /health` và định nghĩa rõ từng biến môi trường trong `envVars` (`generateValue: true` để tự động sinh secret, `sync: false` để nhập secret trực tiếp trên dashboard mà không lưu vào Git).
- **Lý do khác biệt:** Railway ưu tiên trải nghiệm triển khai nhanh theo từng service kết nối trực quan trên project canvas, còn Render Blueprint hướng tới mô tả toàn bộ cấu hình hạ tầng và biến môi trường nhất quán trong mã nguồn Git.

### Exercise 3.3: Mô tả CI/CD Pipeline trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `cloudbuild.yaml` được kích hoạt tự động khi push lên nhánh `main` và thực hiện 4 bước tuần tự:
1. **`test`:** Khởi chạy container `python:3.11-slim` để cài dependencies và chạy `pytest tests/ -v`; nếu test lỗi thì dừng pipeline ngay lập tức.
2. **`build`:** Build Docker image gắn đồng thời hai tag `$COMMIT_SHA` và `latest`, sử dụng `--cache-from` từ image `latest` để tăng tốc độ build.
3. **`push`:** Đẩy các tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Triển khai revision mới lên Cloud Run (vùng `asia-southeast1`) tương ứng đặc tả trong `service.yaml`: cấu hình autoscaling `minScale: 1` (tránh cold start) đến `maxScale: 10`, `containerConcurrency: 80`, giới hạn `1 CPU / 512Mi RAM`, gắn `livenessProbe` (`/health`), `startupProbe` (`/ready`) và nạp các secret (`OPENAI_API_KEY`, `AGENT_API_KEY`) an toàn từ GCP Secret Manager.

---

## Part 4: API Security

### Exercise 4.1–4.3: Kết quả kiểm thử Authentication (401 / 200) và Rate Limiting (429)

Kiểm thử thực tế trên `04-api-gateway/production` (hỗ trợ JWT với tài khoản `student` giới hạn `10 req/min`, `$1/day` và `teacher` giới hạn `100 req/min`) cùng lớp bảo mật trên `06-lab-complete` (API Key `X-API-Key` + Sliding Window Rate Limit lưu Redis):

```text
# 1. Request thiếu / sai xác thực -> HTTP 401 Unauthorized (kèm security headers)
HTTP/1.1 401 Unauthorized
server: uvicorn
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
{"detail":"Invalid or missing API key / token"}

# 2. Request có xác thực hợp lệ (đã ẩn key/token) -> HTTP 200 OK
curl -i -X POST "$BASE/ask" -H "Content-Type: application/json" -H "X-API-Key: <REDACTED>" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"...","cost_usd":0.000018}

# 3. Gửi liên tục vượt RATE_LIMIT_PER_MINUTE -> HTTP 429 Too Many Requests
Request 1..5 -> HTTP/1.1 200 OK
Request 6    -> HTTP/1.1 429 Too Many Requests
Retry-After: 60
{"detail":"Rate limit exceeded"}
(Restart agent: state lưu trên Redis Sorted Set nên vẫn giữ nguyên trạng thái chặn 429)
```

### Exercise 4.4: Cách triển khai Cost Guard

- **Cơ chế hoạt động:**
  1. **Định giá token:** Quy đổi số `input_tokens` và `output_tokens` sang USD theo bảng giá model (`PRICE_INPUT_PER_1K = 0.00015`, `PRICE_OUTPUT_PER_1K = 0.0006`).
  2. **Kiểm tra trước khi gọi LLM (`check_budget`):** Đọc tổng chi phí tích lũy hiện tại trong ngày từ Redis (`cost:daily:YYYY-MM-DD`). Nếu tổng chi phí đã đạt hoặc vượt `DAILY_BUDGET_USD`, chặn ngay request bằng mã lỗi **`HTTP 402 Payment Required`** trước khi gọi LLM để không phát sinh thêm chi phí.
  3. **Ghi nhận sau khi gọi LLM (`record_cost`):** Cộng dồn chi phí của request vừa xử lý vào Redis bằng lệnh nguyên tử `INCRBYFLOAT` kèm `EXPIRE` để tự động reset theo chu kỳ ngày và đồng bộ chính xác giữa nhiều worker/instance.
- **Tại sao cần cả Rate Limiting và Cost Guard:** Rate limiting kiểm soát **tần suất gọi** (số request/phút) nhằm chống spam/quá tải hệ thống, còn Cost Guard kiểm soát **tổng chi phí tiền thật** (vì một số ít request có prompt/output rất dài vẫn có thể tiêu cạn ngân sách LLM dù chưa chạm ngưỡng rate limit).

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Ghi chú kiến trúc và kết quả kiểm thử Stateless Scaling

1. **Phân biệt Liveness (`/health`) và Readiness (`/ready`):**
   - `GET /health` (Liveness probe) kiểm tra tiến trình ứng dụng còn hoạt động hay bị treo; luôn trả về **`200 OK`** kể cả khi mất kết nối Redis để orchestrator không khởi động lại container một cách vô ích khi lỗi nằm ở dịch vụ bên ngoài.
   - `GET /ready` (Readiness probe) kiểm tra mức độ sẵn sàng xử lý traffic (kiểm tra `redis_healthy()` bằng `ping`); trả về **`503 Service Unavailable`** khi mất kết nối Redis để load balancer tạm ngừng chuyển traffic vào instance đó cho đến khi Redis phục hồi.
2. **Graceful Shutdown (`SIGTERM`):** Khi nhận tín hiệu `SIGTERM` (ví dụ lúc `docker stop` hoặc rolling deploy), ứng dụng ngừng nhận request mới, hoàn thành nốt các request đang xử lý, đóng kết nối Redis trong `lifespan` và thoát sạch với `exit code 0` (đo thực tế qua `docker stop` mất `0.5s`).
3. **Vì sao lưu state trong RAM bị hỏng khi chạy nhiều instance:** Mỗi container/worker có vùng nhớ RAM độc lập. Khi chạy 3 instance phía sau Nginx load balancer, request 1 được xử lý bởi `agent-1` nhưng request 2 lại vào `agent-2` sẽ không thấy được lịch sử hội thoại hoặc bộ đếm rate limit nằm trong RAM của `agent-1`. Do đó toàn bộ state phải đưa ra bộ nhớ dùng chung là Redis.
4. **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 104aa9a6-1daa-4247-8541-9c04028277b6

Request 1: [instance-b7b01e]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-d9aa87]
  Q: Why do we need containers?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 3: [instance-0dc490]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-b7b01e]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-d9aa87]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b7b01e', 'instance-d9aa87', 'instance-0dc490'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

- **Giải thích kết quả:** Nginx đã phân phối luân phiên 5 request qua cả 3 instance khác nhau (`instance-b7b01e`, `instance-d9aa87`, `instance-0dc490`), nhưng khi truy vấn lại `/chat/{session_id}/history`, toàn bộ 10 tin nhắn (5 user + 5 assistant) vẫn đầy đủ nhờ kiến trúc stateless lưu session tập trung trong Redis.

---

## Part 6: Final Project — Kết quả `check_production_ready.py`

Chạy đầy đủ trong `06-lab-complete/` (có Docker, image size `238 MB`, `docker stop` exit code `0` trong `0.5s`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Usage Log

- **Công cụ sử dụng:** Gemini
- **Mục đích sử dụng:**
  - Hướng dẫn hoàn thiện các chỗ `TODO` trong `06-lab-complete/` (`config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, multi-stage `Dockerfile`, `docker-compose.yml`, `railway.toml`, `render.yaml`).
  - Hỗ trợ xử lý lỗi chạy `check_production_ready.py` trên Windows/Docker để đạt đủ kiểm tra `SIGTERM` (`PASS 12/12`), gỡ lỗi kết nối Redis khi triển khai lên Render và tổng hợp cấu trúc báo cáo `DEPLOYMENT.md`, `MISSION_ANSWERS.md`.
- **Kiểm chứng của học viên:** Học viên trực tiếp chạy và xác minh toàn bộ mã nguồn, kết quả `PASS 12/12` (43/43 checks), đo kích thước Docker image (`1.67 GB` vs `240 MB`), kiểm thử stateless 3 instance với Redis, triển khai thực tế lên Render (`https://day14-ai-agent-qscp.onrender.com`) và đối chiếu 4 endpoint (`200 / 200 / 401 / 200`).