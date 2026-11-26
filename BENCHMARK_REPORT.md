# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file JSON trong `reports/`, CSV trong `benchmark-results/` và log/API của stack Docker Observability.

**Họ tên:** Đỗ Duy Tùng (MSSV: 2A202603844)  
**Ngày chạy:** 2026-11-26  
**Môi trường:** Linux (Python 3.14.10 venv / Docker Engine 29.9.3 / Docker Compose v5.7.1)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency cơ bản của mock LLM + retrieval là ~150–220 ms; ngưỡng 500 ms đảm bảo 95% người dùng nhận phản hồi nhanh, không bị nghẽn hàng đợi. |
| Error rate `/ask` | < 2.0 % | Mock LLM có tỉ lệ lỗi upstream mặc định ~1% (`MOCK_ERROR_RATE=0.01`); ngưỡng 2% cho phép sai số nhỏ mà vẫn phát hiện sớm lỗi hệ thống. |
| Accuracy trên golden dataset | ≥ 100 % | Bộ golden dataset có 23 câu hỏi cốt lõi; dùng quality gate 100% (v2_fixed) để chặn mọi regression trước khi merge/deploy. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.99 | 193.2 | 222.8 | 1716.2 | 1.67% | PASS |
| 10 | 36.14 | 192.6 | 225.5 | 1703.5 | 1.33% | PASS |
| 50 | 100.86 | 214.5 | 395.5 | 1718.2 | 1.33% | PASS |
| 100 | 63.83 | 427.4 | 3474.3 | 3748.7 | 0.67% | FAIL |

**Nhận xét:** RPS không tăng tuyến tính mãi theo concurrency. Từ c=1 → 50, RPS tăng gần tuyến tính (3.99 → 36.14 → 100.86 req/s) nhờ xử lý bất đồng bộ; nhưng tới c=100, event loop / 1 worker Uvicorn bị bão hòa (queueing), khiến RPS tụt xuống 63.83 req/s và p95 vọt lên 3474.3 ms (vi phạm SLO ≤ 500 ms).

### 2.2 Tail latency (`concurrency=20`, `requests=300`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 197.9 | 243.7 | 287.0 |
| 0.03 (mặc định) | 229.5 | 261.8 | 1695.2 |
| 0.1 | 360.7 | 1697.3 | 1718.7 |

**Nhận xét:** **p99** (và ở mức 10% là **p95**) nhạy nhất với các request chậm bất thường. Ở `MOCK_SLOW_RATE=0.03`, `avg` chỉ tăng nhẹ từ 197.9 lên 229.5 ms nhưng `p99` nhảy vọt từ 287.0 ms lên **1695.2 ms**. Vì vậy không nên đặt SLO theo `average`, vì giá trị trung bình che giấu trải nghiệm tệ của nhóm người dùng ở đuôi phân phối (tail latency).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.4 | 108.7 | 113.0 |
| Tổng cost (USD) | $0.000409 | $0.000756 | $0.000785 |
| Cost / câu đúng (USD) | $0.00040875 | $0.00003599 | $0.00003413 |
| Quality gate | FAIL | PASS (min 80%) | PASS (min 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa (`develop/utils/mock_llm.py`):**

| ID | Keyword bị thiếu | Cách sửa |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["jwt", "xác thực"]` mô tả JWT là token có chữ ký số và thời gian hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["hpa", "kubernetes", "autoscal"]` mô tả HPA scale theo CPU, memory hoặc custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- Agent v2 thêm bước retrieval nên tốn nhiều token hơn (~113 vs 57.4 tokens/câu) và chậm hơn một chút (p50 ~199.6 ms vs 160.5 ms), nhưng accuracy tăng vọt từ 4.35% lên 100%, làm **cost / câu đúng** giảm hơn **10 lần** ($0.00040875 xuống $0.00003413).
- **Cách dùng exit code của `run_eval.py` trong CI:** Chạy `python eval/run_eval.py --min-accuracy 1.0 --baseline reports/eval_v2.json` trong GitHub Actions; nếu accuracy thấp hơn ngưỡng hoặc có bất kỳ câu nào bị regression, script trả **exit code 1** và CI tự động chặn merge PR.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] `screenshots/grafana-dashboard.png` — Dashboard Grafana khi đang có tải (4 Golden Signals)
- [x] `screenshots/jaeger-slow-trace.png` — Một trace chậm trong Jaeger (`b1687111f40364ab46e2fbd95248da85`)
- [x] `screenshots/jaeger-error-trace.png` — Một trace lỗi trong Jaeger (`a7a2cc7a01d528e06aa3f8f303633936`, HTTP 503 + exception `LLMError`)
- [x] `screenshots/prometheus-alert-firing.png` — Trang Alerts của Prometheus đang **firing** (`AgentInstanceDown`)

### 4.2 Thí nghiệm "phá hệ thống" & Alerting

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel / Metric phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (khi > 5% liên tục 1m) | ~60s (`for: 1m`) | Error Rate panel (`http_requests_total{status=~"5.."}`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (khi p95 > 1s liên tục 2m) | ~120s (`for: 2m`) | Latency p95/p99 panel (`http_request_duration_seconds_bucket`) |
| C | Load cao (`-u 100`) | `LLMCostBurnRateHigh` (quan sát thực tế: **$2.66–$4.05/giờ** > $2/giờ) | ~2m (`for: 2m`, fired lúc `10:14:42Z`) | LLM Cost Burn Rate (`llm_cost_usd_total`) |
| D | `docker pause` 1 instance (`agent-2`) | `AgentInstanceDown` (`up{job="agent"} == 0`) | ~30s (`for: 30s`, pending `10:21:47Z` → firing sau 30s) | Up / Active Instances (`up{job="agent"}`) |
| E | `AGENT_VERSION=v1` | Không alert nào firing | N/A | Token/cost giảm nhẹ nhưng chất lượng tụt mạnh |

**Thí nghiệm E không làm alert nào firing. Cách phát hiện sự cố này trong production:**
Hệ thống hạ tầng (HTTP 200, latency, CPU) vẫn bình thường khi chất lượng trả lời giảm (như đổi nhầm `v1` hoặc đổi prompt tệ). Để phát hiện, cần chạy **Eval định kỳ / Canary eval** trên golden dataset, kết hợp **online quality monitoring** (LLM-as-a-judge sampling, theo dõi tỉ lệ thumbs-up/down của user hoặc sự sụt giảm bất thường của `avg_output_tokens`).

### 4.3 Debug bằng trace

Chọn 1 trace chậm thực tế từ log & Jaeger:

- `trace_id`: `b1687111f40364ab46e2fbd95248da85`
- Tổng thời gian: `1692.7 ms`
- Span chiếm nhiều thời gian nhất: `llm_call` (`1667.1 ms`, chiếm **98.5%** tổng thời gian request)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T10:21:22.157844+00:00", "level": "INFO", "service": "observable-agent", "instance": "29626c33972b", "event": "llm_call", "trace_id": "b1687111f40364ab46e2fbd95248da85", "span_id": "022660cf34dc5ebe", "request_id": "e67e721c66da", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1667.1}
{"ts": "2026-11-26T10:21:22.158553+00:00", "level": "INFO", "service": "observable-agent", "instance": "29626c33972b", "event": "http_request", "trace_id": "b1687111f40364ab46e2fbd95248da85", "span_id": "022660cf34dc5ebe", "request_id": "e67e721c66da", "method": "POST", "route": "/ask", "status": 200, "ms": 1692.7}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút, endpoint `POST /ask`)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---:|---:|---:|---:|---|
| 1 | 58.83 | 200 | 450 | 1700 | 68 / 7013 (0.97%) |
| 3 | 59.49 | 200 | 330 | 1700 | 55 / 7092 (0.78%) |

**Giải thích kết quả:**
- Khi scale từ 1 lên 3 instance, **p95 cải thiện rõ rệt từ 450 ms xuống 330 ms** (giảm 26.7%) vì tải được Nginx chia đều qua 3 container nên giảm thời gian chờ hàng đợi.
- **RPS gần như giữ nguyên (~59 req/s)** vì ở mức 100 user có `wait_time = between(0.5, 2)` giây, tổng lượng tải sinh ra từ Locust bị giới hạn bởi think-time của 100 user (~59 req/s đã đủ phục vụ hết). **p99 vẫn ở 1700 ms** vì nút thắt của tail latency nằm ở ~3% request bị chậm giả lập từ phía LLM (`MOCK_SLOW_RATE=0.03`), không thể giải quyết bằng cách thêm replica backend.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. Không bao giờ dùng latency trung bình (`avg`) làm SLO; phải dùng `p95`/`p99` để thấy được tail latency ảnh hưởng tới người dùng thật.
  2. Nâng cấp pipeline (như RAG ở v2) tuy tăng token/request nhưng giúp tăng accuracy vượt bậc và giảm mạnh **cost / câu đúng**.
  3. 3 trụ cột Metrics (Prometheus/Grafana) – Traces (Jaeger) – Logs (JSON có `trace_id`) liên kết chặt chẽ với nhau giúp khoanh vùng nguyên nhân chậm/lỗi chỉ trong vài giây.
- **Metric / Alert bổ sung cho production thật:**
  - Metric về **cache hit rate** (Redis), **TTFT (Time To First Token)** cho streaming, và **LLM provider rate-limit retries**.
  - Alert về **chất lượng suy giảm** (tỉ lệ fallback response tăng cao) và **Redis memory/connection saturation**.
