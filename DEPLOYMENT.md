# Deployment Information

## Public URL
`<ĐIỀN_URL_RENDER_CỦA_BẠN>` (ví dụ: `https://ai-agent-production-xxxx.onrender.com`)

## Platform
Render (Blueprint từ `06-lab-complete/render.yaml` — Web Service Docker + Render Redis)

## Test Commands

### 1. Health Check (expected: 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "<PUBLIC_URL>/health"
```

### 2. Readiness Check (expected: 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "<PUBLIC_URL>/ready"
```

### 3. API Test without Key (expected: 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "<PUBLIC_URL>/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
```

### 4. API Test with Key (expected: 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "<PUBLIC_URL>/ask" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question": "Hello"}'
```

## Environment Variables Set (trên Render Dashboard)
- `ENVIRONMENT=production`
- `AGENT_API_KEY` (tự sinh qua `generateValue: true`)
- `REDIS_URL` (tự động nối từ Render Redis `ai-agent-redis`)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `LOG_LEVEL=INFO`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
