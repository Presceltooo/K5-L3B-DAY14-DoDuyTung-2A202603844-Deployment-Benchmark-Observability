# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong source code (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên Git, key và mật khẩu bị lộ ngay lập tức.
2. **In secret ra log (dòng 34):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key vào stdout/log aggregator.
3. **Dùng `print()` thay vì structured logging (dòng 33, 38, 48):** Khó lọc theo level, không có timestamp chuẩn hay định dạng JSON để công cụ giám sát (Loki, Datadog) parse.
4. **Hardcode cấu hình & bật `reload=True` (dòng 21–22, 51–53):** `DEBUG = True`, `host="localhost"` (container không nhận được traffic từ bên ngoài), `port=8000` (không đọc `PORT` do Railway/Render cấp), `reload=True` gây tốn CPU và không ổn định trên production.
5. **Thiếu health check (`/health`, `/ready`) và graceful shutdown:** Nếu app treo hoặc đang tắt container, load balancer/platform không biết để ngừng gửi request hoặc restart.

### Exercise 1.2: Kết quả chạy bản `develop`

```bash
curl -sS -X POST "http://localhost:8000/ask?question=Hello"
```

```json
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 1.3: So sánh `develop/app.py` và `production/app.py`

| Tiêu chí | `develop/app.py` | `production/app.py` | Vì sao quan trọng? |
|---|---|---|---|
| **Cấu hình & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `port=8000` (dòng 17–18, 52) | Đọc từ biến môi trường qua `config.settings` (`settings.host`, `settings.port` ở dòng 195–197) | Tách biệt code và config theo 12-Factor App, không lộ secret trên Git và đổi được cấu hình theo từng môi trường mà không sửa code. |
| **Logging** | Dùng `print("[DEBUG] ...")` và in cả API key (dòng 33–38) | `logging.basicConfig` định dạng JSON + `json.dumps` (dòng 28–32, 49–55, 111–122), không log secret | Log JSON giúp hệ thống thu thập log parse, tìm kiếm, tạo metric/alert tự động và đảm bảo an toàn bảo mật. |
| **Health & Readiness** | Không có endpoint kiểm tra | Có `GET /health` (liveness, dòng 135–149) và `GET /ready` (readiness, trả 503 nếu chưa sẵn sàng, dòng 152–161) | Platform/load balancer biết chính xác khi nào container sống và khi nào sẵn sàng nhận traffic. |
| **Lifecycle / Shutdown** | Không xử lý `SIGTERM` | Dùng `lifespan` (dòng 39–68) và đăng ký `signal.SIGTERM` (dòng 180–189) | Cho phép request đang xử lý hoàn thành trước khi process thoát, tránh rớt request khi deploy/scale down. |
| **Network binding & Debug** | `host="localhost"`, `reload=True` (dòng 51–53) | `host=settings.host` (`0.0.0.0`), `reload=settings.debug` (dòng 196–198) | Trong Docker/cloud, app phải bind `0.0.0.0` và nhận `PORT` động mới nhận được kết nối từ bên ngoài. |

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image:** `FROM python:3.11` — bản đầy đủ của Python trên Debian (~1 GB), chứa nhiều công cụ build không cần thiết khi chạy production.
2. **Working directory:** `WORKDIR /app` — mọi lệnh tiếp theo (`COPY`, `RUN`, `CMD`) chạy trong thư mục `/app` bên trong container.
3. **Thứ tự `COPY requirements.txt` trước `COPY . .`:** Tận dụng **Docker layer cache**. Khi chỉ sửa code (`app.py`) mà không đổi `requirements.txt`, Docker tái sử dụng lại layer `pip install` đã cache, giúp build nhanh hơn rất nhiều.
4. **Điểm chưa tối ưu cho production:** Dùng base image nặng (`python:3.11` thay vì `-slim`), không dùng multi-stage build, chạy bằng user `root`, và chưa có `HEALTHCHECK`.

### Exercise 2.2 & 2.3: So sánh kích thước image (`docker images`)

Build từ gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

| Image | Tag | Kích thước đo được | Ghi chú |
|---|---|---:|---|
| `my-agent` | `develop` | **1.67 GB** (~1670 MB) | Single-stage, `FROM python:3.11` |
| `my-agent` | `advanced` | **240 MB** | Multi-stage (`builder` + `runtime` dùng `python:3.11-slim`), non-root `appuser` |
| **Chênh lệch** | | **Giảm 85.6%** | Tiết kiệm ~1.43 GB mỗi image |

**Multi-stage giảm dung lượng ở đâu?** Stage `builder` cài `gcc`, `libpq-dev` và biên dịch packages vào `/root/.local`; stage `runtime` khởi tạo lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder` phần site-packages đã cài, bỏ lại toàn bộ compiler (`gcc`) và cache apt/pip.

### Exercise 2.4: Kiến trúc Docker Compose stack (`02-docker/production/docker-compose.yml`)

```text
Client ──▶ Nginx (:80/:443) ──▶ Agent (:8000, network: internal) ──▶ Redis (:6379)
                                        │
                                        └──▶ Qdrant (:6333)
```

- **nginx:** Reverse proxy / load balancer nhận traffic từ ngoài (`80:80`), forward vào service `agent` trong mạng nội bộ `internal`.
- **agent:** Chạy FastAPI (target `runtime`), kết nối `REDIS_URL=redis://redis:6379/0` và `QDRANT_URL=http://qdrant:6333`, chỉ khởi động sau khi `redis` và `qdrant` báo `healthy`.
- **redis:** Cache session & rate limiting (`redis:7-alpine`, volume `redis_data`).
- **qdrant:** Vector database cho RAG (`qdrant/qdrant:v1.9.0`, volume `qdrant_data`).

---

## Part 3: Cloud Deployment

### Exercise 3.2: Deploy lên Render (agent Part 6)

- **Public URL:** `<ĐIỀN_URL_RENDER_SAU_KHI_DEPLOY>` (chi tiết xem [DEPLOYMENT.md](DEPLOYMENT.md))
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`

- **`railway.toml`** là file cấu hình gắn với service hiện có trên Railway (khai báo `[build] builder = "DOCKERFILE"` và `[deploy] healthcheckPath = "/health"`), còn database như Redis hay biến môi trường thường được thêm/quản lý riêng trên Railway Dashboard hoặc CLI.
- **`render.yaml`** là file **Infrastructure as Code (Blueprint)** mô tả toàn bộ stack trong một file: khai báo cả `type: web` (`runtime: docker`, `rootDir: 06-lab-complete`, `healthCheckPath: /health`), lẫn service `type: redis`, đồng thời nối `REDIS_URL` tự động qua `fromService` và sinh secret an toàn bằng `generateValue: true` (hoặc `sync: false`).

### Exercise 3.3: Pipeline CI/CD trên Google Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `cloudbuild.yaml` chạy tự động qua 4 bước tuần tự (`waitFor`):
1. **`test`:** Dùng `python:3.11-slim` cài dependencies và chạy `pytest tests/`.
2. **`build`:** Build Docker image gắn tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from`).
3. **`push`:** Đẩy image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Chạy `gcloud run deploy` cập nhật service Cloud Run (`asia-southeast1`, `min-instances=1`, `max-instances=10`), inject secret từ Secret Manager (`--set-secrets`). File `service.yaml` định nghĩa cấu hình Knative Service tương ứng (concurrency 80, CPU/RAM limits, liveness `/health` và startup `/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **Không có `X-API-Key` → HTTP 401:**
```http
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

- **Có `X-API-Key: secret-key-123` → HTTP 200:**
```http
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT + Rate Limiting (`04-api-gateway/production/app.py`)

Đăng nhập lấy token tại `POST /auth/token` với `student` / `demo123` (token đã được che: `Bearer eyJhbGciOi...<masked>`). Tài khoản `student` giới hạn **10 request/phút**. Chạy vòng lặp 12 request liên tiếp:

```text
Req 1 -> HTTP 200
...
Req 10 -> HTTP 200
Req 11 -> HTTP 429
Req 12 -> HTTP 429
```

Output mẫu khi vượt giới hạn (`429 Too Many Requests`):
```http
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách làm Cost Guard

- **Rate limit** giới hạn *tần suất* request (requests/phút), nhưng không ngăn được việc user gửi câu hỏi rất dài hoặc gọi đều đặn làm tốn tiền LLM.
- **Cost guard** bảo vệ *ngân sách* (USD/ngày hoặc USD/tháng): trước khi gọi LLM (`check_budget()`), kiểm tra tổng chi phí đã dùng trong Redis; nếu `spent >= DAILY_BUDGET_USD` thì chặn ngay bằng **HTTP 402 Payment Required**. Sau khi LLM trả lời (`record_cost()`), tính chi phí theo số token input/output và cộng dồn nguyên tử vào Redis (`INCRBYFLOAT`).

---

## Part 5: Scaling & Reliability

### Liveness (`/health`) vs Readiness (`/ready`) và Graceful Shutdown

- **`GET /health` (Liveness):** Trả về **200** miễn là process Python còn sống (kể cả khi Redis chưa kết nối được), giúp platform biết container không bị treo deadlock.
- **`GET /ready` (Readiness):** Kiểm tra kết nối tới phụ thuộc (Redis `PING`). Nếu mất Redis → trả **503** để Load Balancer tạm ngừng route traffic vào instance đó cho tới khi Redis hồi phục.
- **Graceful shutdown:** Khi nhận `SIGTERM` (lúc `docker stop` hoặc rolling deploy), server ngừng nhận kết nối mới, chờ các request đang chạy hoàn thành (trả 200), đóng kết nối Redis trong `lifespan` rồi thoát với exit code `0`.

### Exercise 5.4 & 5.5: Chạy 3 instance với Redis (`test_stateless.py`)

Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` trong `05-scaling-reliability/production/` và chạy `python test_stateless.py`:

```text
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-e6cdd3', 'instance-960a35', 'instance-1d827f'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** Nếu lưu session/rate-limit/budget trong RAM của từng process, khi Nginx cân bằng tải round-robin sang 3 container khác nhau (`instance-e6cdd3`, `instance-960a35`, `instance-1d827f`), mỗi instance chỉ thấy dữ liệu cục bộ và mất sạch khi restart. Lưu state tập trung trong **Redis** giúp mọi instance đều stateless và dùng chung trạng thái nhất quán.

---

## Part 6: Final Project (`06-lab-complete/`)

Kết quả chạy `python check_production_ready.py` (chế độ đầy đủ với Docker):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)        (238 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown                          (docker stop: exit code 0, 0.6s)
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 42/42 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI log

- **Công cụ sử dụng:** Trợ lý AI lập trình trong IDE.
- **Nội dung đã hỏi / thực hiện:**
  - Thiết kế và triển khai các module trong `06-lab-complete/app/` (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`), `Dockerfile` multi-stage, `docker-compose.yml`, `.dockerignore`, `.env.example`, và `render.yaml`.
  - Hỗ trợ chạy các bài thực hành Part 1, 2, 4, 5 và đối chiếu kết quả thực tế.
- **Tự kiểm tra:** Đã chạy `python check_production_ready.py` đạt `PASS 12/12` (42/42 checks), tự build và đo kích thước image Docker (`1.67 GB` vs `240 MB`), chạy `curl -i` kiểm tra `401/200/429`, và chạy `test_stateless.py` trên 3 instance qua Nginx.
