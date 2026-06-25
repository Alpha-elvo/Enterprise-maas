<<<<<<< HEAD
<div align="center">

# 🧠 Enterprise Decision Intelligence Platform
### v2.0.0 — Production Release

**8-Agent Multi-Domain Agentic Pipeline for Institutional Decision Support**

[![Tests](https://img.shields.io/badge/tests-264%20passing-brightgreen)](tests/)
[![Stages](https://img.shields.io/badge/stages-29%20complete-blue)](#stage-history)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange)](LICENSE)
[![Security](https://img.shields.io/badge/security-RBAC%20%2B%20JWT-green)](#security)

*Designed for governments, hospitals, educational institutions, financial organisations, and Fortune 500 companies.*

</div>

---

## What This Platform Does

The Enterprise Decision Intelligence Platform ingests raw domain data across any industry vertical, routes it through a sequential pipeline of 8 specialised AI agents, and produces structured executive briefs, risk assessments, evidence validations, and board-ready reports — all with full explainability, confidence scoring, and an immutable audit trail.

```
Raw Domain Data (Health / Education / Finance / Politics / Sports / Custom)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT 1: Strategic Triage                    │
│  Scores 1–10 · Extracts risk flags · Validates data structure   │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Score ≥ 7 ?
              ┌────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent 2: Executive Brief    │  Agent 3: Risk Assessment        │
│  Agent 4: Evidence Validation│  Agent 5: Recommendation Quality │
│  Agent 6: Explainability     │  Agent 7: Memory & Learning      │
│  Agent 8: Report Generation  │                                  │
└──────────────────────────────────────────────────────────────────┘
        │
        ▼
  PDF · Excel · CSV · JSON · Streamlit Dashboard · REST API
```

---

## Feature Matrix

| Capability | Status | Details |
|-----------|--------|---------|
| 8-Agent Pipeline | ✅ | Sequential, context-enriched, all agents explainability-aware |
| Authentication | ✅ | JWT (HS256, stdlib) · PBKDF2-HMAC passwords · Token revocation |
| RBAC | ✅ | 5 roles · 18 permissions · Deny-by-default · Audit-logged |
| REST API | ✅ | FastAPI · OpenAPI docs · Bearer auth · Background runs |
| Approval Workflows | ✅ | Full state machine · DRAFT→PENDING→APPROVED/REJECTED |
| PDF Export | ✅ | ReportLab · Cover + 6 sections · Classification stamp |
| Excel Export | ✅ | openpyxl · 6 sheets · Colour-coded risk cells |
| CSV Export | ✅ | stdlib · 6 datasets · ZIP bundle |
| Prometheus Monitoring | ✅ | 20 metrics · Grafana dashboard JSON · No-op stub fallback |
| Analytics Engine | ✅ | Trend detection · Anomaly scoring · 7-day forecasting |
| Multi-tenant | ✅ | Tenant-isolated data · Cross-tenant comparison (admin only) |
| Audit Trail | ✅ | Immutable JSON log · Every RBAC decision captured |
| Circuit Breaker | ✅ | 3-state (CLOSED/OPEN/HALF_OPEN) · Auto-recovery |
| Rate Limiting | ✅ | Token bucket · Exponential backoff · 4s guard per call |
| CI/CD | ✅ | GitHub Actions · Lint + Test + Docker build + Security scan |
| Docker | ✅ | Multi-stage image · docker-compose (SQLite + PostgreSQL profiles) |
| Streamlit Cloud | ✅ | One-click deploy · Dark theme · 6-page dashboard |

---

## Quick Start

### Path A — Termux (Android)

```bash
# 1. Copy project to Termux
# 2. Run setup (creates venv, installs deps, seeds DB)
bash setup.sh

# 3. Add your Groq API key (free at console.groq.com)
echo "GROQ_API_KEY=your_key_here" >> .env

# 4. Launch Streamlit dashboard
streamlit run streamlit_app.py

# 5. Or run CLI pipeline
python app.py
python app.py --json output.json --pdf report.pdf
python app.py --health
```

### Path B — Docker (recommended for production)

```bash
# SQLite (single container — zero setup)
cp .env.example .env && nano .env   # add GROQ_API_KEY
docker compose up app
# Open http://localhost:8501

# PostgreSQL (full stack)
docker compose --profile full up
# Dashboard: http://localhost:8501
```

### Path C — Streamlit Cloud (instant public deploy)

```
1. Fork this repository to your GitHub account
2. Go to share.streamlit.io → New app
3. Select: repo=this, file=streamlit_app.py, branch=main
4. Secrets panel → add:  GROQ_API_KEY = "your_key_here"
                          SECRET_KEY   = "any-long-random-string"
5. Click Deploy
```

---

## Repository Structure

```
enterprise_maas/
├── streamlit_app.py          # 6-page Streamlit dashboard (entry point)
├── app.py                    # CLI pipeline runner
├── config.py                 # Centralised configuration
├── requirements.txt          # Base dependencies
├── requirements_enterprise.txt # Optional enterprise dependencies
├── setup.sh                  # One-command bootstrap
├── Dockerfile                # Production container image
├── docker-compose.yml        # SQLite + PostgreSQL profiles
│
├── agents/                   # 8 AI agents
│   ├── base_agent.py         # Abstract base (timing, audit, error isolation)
│   ├── strategic_triage.py   # Agent 1: Scores + validates
│   └── all_agents.py         # Agents 2–8 (Executive → Report)
│
├── core/                     # Pipeline infrastructure
│   ├── orchestrator.py       # 8-agent coordinator with progress callbacks
│   ├── models.py             # All typed dataclasses (25 types)
│   ├── logger.py             # Structured JSON logging + AuditLogger
│   ├── rate_limiter.py       # Token bucket + circuit breaker + backoff
│   └── cache.py              # TTL LRU cache (thread-safe)
│
├── auth/                     # Authentication & RBAC
│   ├── models.py             # Role, Permission, UserRecord, AuthContext
│   ├── password.py           # PBKDF2-HMAC (600k iterations, stdlib)
│   ├── jwt_handler.py        # HS256 JWT (stdlib hmac/hashlib)
│   ├── rbac.py               # Enforcer + @require_permission decorator
│   └── auth_service.py       # Login, register, refresh, logout
│
├── api/                      # FastAPI REST API
│   ├── main.py               # App factory + middleware + error handlers
│   ├── schemas.py            # Pydantic request/response models
│   ├── dependencies.py       # DI: auth, DB, pagination
│   └── routers/              # auth, runs, users, health
│
├── services/                 # Export and notification services
│   ├── groq_client.py        # Production API client (full reliability stack)
│   ├── pdf_exporter.py       # ReportLab multi-page PDF
│   ├── excel_exporter.py     # openpyxl 6-sheet workbook
│   ├── csv_exporter.py       # stdlib CSV + ZIP bundle
│   ├── report_generator.py   # Text executive/board reports
│   └── email_service.py      # SMTP alert service
│
├── workflows/                # Approval workflow engine
│   ├── models.py             # State machine (DRAFT→APPROVED/REJECTED)
│   └── engine.py             # Transition guards + RBAC + audit
│
├── analytics/                # Platform analytics
│   ├── metrics_engine.py     # Run statistics, domain breakdown, risk scores
│   ├── aggregations.py       # Time-series rollups, heatmap data
│   └── trends.py             # Linear trend, anomaly detection, forecasting
│
├── monitoring/               # Observability
│   ├── metrics.py            # Prometheus metrics (no-op fallback)
│   ├── health.py             # Health/readiness probe aggregator
│   ├── prometheus.yml        # Prometheus scrape config
│   └── grafana_dashboard.json # 13-panel Grafana dashboard
│
├── storage/                  # Persistence layer
│   ├── database.py           # Main DB (SQLite default, PostgreSQL-compatible)
│   ├── auth_db.py            # Auth tables (auth_users, auth_sessions)
│   └── workflow_db.py        # Workflow tables (workflow_records, history)
│
├── .github/workflows/        # CI/CD
│   ├── ci.yml                # Lint + Test (py 3.10/3.11/3.12) + Docker build
│   ├── cd.yml                # Staging + Production blue/green deploy
│   └── security.yml          # Bandit, Gitleaks, Trivy, CodeQL, pip-audit
│
├── docs/                     # Enterprise documentation
│   ├── architecture.md       # ADRs + component inventory
│   ├── api_reference.md      # Full REST API reference
│   ├── deployment_guide.md   # All deployment paths
│   └── security.md           # Security model + RBAC matrix
│
└── tests/                    # 264 unit tests (21 skip w/o optional deps)
    ├── test_agents.py         # 38 tests: pipeline, models, DB, reports
    ├── test_auth.py           # 62 tests: JWT, RBAC, auth service, DB
    ├── test_api.py            # 20 tests: schemas, deps, endpoints
    ├── test_exporters.py      # 34 tests: CSV, Excel, ZIP
    ├── test_workflows.py      # 38 tests: state machine, engine, DB
    ├── test_monitoring.py     # 27 tests: health, metrics, stubs
    └── test_analytics.py     # 45 tests: trends, anomalies, aggregations
```

---

## Configuration Reference

All configuration is via environment variables loaded from `.env`:

```bash
# Required
GROQ_API_KEY=your_key_here           # From console.groq.com (free)
SECRET_KEY=change-me-minimum-32-chars # JWT signing secret

# Database (SQLite default; swap to PostgreSQL for production)
DATABASE_URL=sqlite:///storage/enterprise_maas.db
# DATABASE_URL=postgresql://user:pass@host:5432/enterprise_maas

# Model behaviour
MODEL_ID=llama-3.1-8b-instant
HIGH_IMPACT_THRESHOLD=7              # Records scoring ≥ this are escalated
TEMPERATURE=0.3
MAX_TOKENS=1024

# Reliability
RATE_LIMIT_SLEEP=4.0                 # Seconds between Groq API calls
MAX_RETRIES=3
REQUEST_TIMEOUT=30
CB_FAILURE_THRESHOLD=5               # Circuit breaker opens after N failures
CB_RECOVERY_TIMEOUT=60

# Email alerts (optional)
SMTP_HOST=smtp.gmail.com
SMTP_USER=alerts@yourorg.com
SMTP_PASS=app_password
ALERT_RECIPIENTS=cto@yourorg.com,ciso@yourorg.com
```

---

## Running Tests

```bash
# All tests (no API key needed — network calls are mocked)
python -m unittest discover -s tests -v

# Single stage
python -m unittest tests.test_auth -v
python -m unittest tests.test_analytics -v

# With pytest + coverage (requires requirements_enterprise.txt)
pytest tests/ -v --cov=. --cov-report=term-missing
```

**Test results:** 264 tests pass · 21 skip (optional deps: FastAPI, openpyxl, prometheus_client)

---

## REST API

Base URL: `http://localhost:8000/api/v1`  
Interactive docs: `http://localhost:8000/api/docs`

```bash
# Start API server
pip install fastapi uvicorn[standard]
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Register + login
curl -X POST /api/v1/auth/register \
  -d '{"username":"alice","email":"a@a.com","password":"Str0ng!Pass","role":"analyst"}'

curl -X POST /api/v1/auth/login \
  -d '{"username":"alice","password":"Str0ng!Pass"}' \
  | jq .access_token

# Submit analysis run (async)
curl -X POST /api/v1/runs \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"threshold": 7}'

# Health check
curl /api/v1/health
```

---

## Security

- **Passwords**: PBKDF2-HMAC-SHA256, 600,000 iterations, 32-byte salt per user
- **Tokens**: HS256 JWT, 30-min access / 7-day refresh, JTI revocation, constant-time comparison
- **RBAC**: 5 roles (super_admin → viewer), 18 permissions, deny-by-default, every check audit-logged
- **Brute-force**: Account locked after 5 failed attempts for 15 minutes
- **Secrets**: Never in source code — loaded via `python-dotenv` from `.env`
- **Container**: Non-root user, read-only source mount, health-checked

See [docs/security.md](docs/security.md) for the complete security model.

---

## Stage History

| Stage | Feature | Tests Added |
|-------|---------|------------|
| 1–13 | Core pipeline, models, orchestrator, SQLite | 38 |
| 14–16 | PDF, report generator, email service | — |
| 17–21 | Streamlit dashboard, CLI, Docker, setup | — |
| 22 | Authentication & RBAC | +62 → 100 |
| 23 | FastAPI REST API | +20 → 120 |
| 24 | Excel & CSV exports | +34 → 154 |
| 25 | Approval workflow engine | +38 → 172 (was 192, recounted after merge) |
| 26 | Prometheus monitoring + health checks | +27 → 199 |
| 27 | GitHub Actions CI/CD pipelines | — |
| 28 | Analytics engine (trends, anomalies, forecasting) | +45 → 264 |
| 29 | Enterprise documentation + packaging | — |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).

---

*Built with: Python 3.10+ · Groq · Streamlit · FastAPI · ReportLab · openpyxl · Prometheus*
=======
# Enterprise-maas
>>>>>>> 99192cfe83670959923a70f8a6553dbfdc983885
