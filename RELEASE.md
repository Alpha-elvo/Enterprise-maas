# Release v2.0.0

## Enterprise Decision Intelligence Platform

**Released:** 2026-06-24  
**Type:** Major Production Release  
**Codename:** Apex

---

## Summary

Version 2.0.0 is the first full production release of the Enterprise Decision
Intelligence Platform. Built across 29 incremental stages with zero regressions,
the platform delivers a complete 8-agent agentic pipeline for multi-domain
institutional decision support, backed by enterprise authentication, approval
workflows, REST API, analytics, monitoring, and a professional Streamlit dashboard.

**264 unit tests. 0 failures. 25 modules. 13,101 lines of production Python.**

---

## What's Included

### Core Pipeline (Stages 1–21)
- **8-Agent sequential pipeline**: Strategic Triage → Executive Engine → Risk Assessment → Evidence Validation → Recommendation Quality → Explainability → Memory & Learning → Report Generation
- **5-domain default input matrix**: Health, Education, Entertainment, Sports, Politics
- **Custom domain support**: any structured text payload via JSON
- **Explainability block** on every agent output: confidence score, reasoning, supporting evidence, risks of inaction, expected outcomes
- **4-strategy JSON recovery parser**: handles markdown fences, partial JSON, and LLM commentary without crashing
- **Circuit breaker** (3-state: CLOSED / OPEN / HALF-OPEN) + **token bucket rate limiter** + **exponential backoff** on all Groq API calls
- **TTL LRU cache**: thread-safe, configurable TTL and max size, hit-rate tracking
- **Structured audit logger**: every agent call, RBAC decision, and workflow transition permanently recorded
- **PDF export**: ReportLab multi-page report with cover page, classification stamp, executive summary, domain analysis, risk matrix, recommendations, and audit metadata
- **6-page Streamlit dashboard**: KPI cards, domain score bar chart, urgency donut, risk heatmap, escalation queue, agent status table, audit timeline, system health, settings
- **CLI runner**: `python app.py` with `--pdf`, `--json`, `--health`, `--threshold` flags

### Authentication & RBAC (Stage 22)
- PBKDF2-HMAC-SHA256 password hashing (600,000 iterations, 32-byte salt, stdlib only)
- HS256 JWT implementation in pure stdlib (`hmac` + `hashlib` + `base64`) — no PyJWT dependency
- 30-minute access tokens, 7-day refresh tokens, JTI revocation table
- Refresh token rotation: old token revoked on every `/auth/refresh`
- Brute-force protection: account locked after 5 failures within 15 minutes
- 5 roles (super_admin, tenant_admin, analyst, approver, viewer)
- 18 permissions, deny-by-default matrix
- `@require_permission` decorator and `RBACEnforcer.require()` service-layer gate
- Every RBAC decision logged to audit trail with actor, resource, and outcome

### FastAPI REST API (Stage 23)
- Full OpenAPI 3.0 schema at `/api/docs` and `/api/redoc`
- Bearer token authentication on all protected routes
- Endpoints: auth (register, login, refresh, logout, password, me), runs (CRUD + async submit), users (CRUD), health (liveness + readiness)
- Request ID middleware, response-time headers, structured access logging
- Global exception handlers mapping domain errors to correct HTTP status codes
- Pagination on all list endpoints (`?page=N&per_page=M`)

### Export Services (Stage 24)
- **Excel** (openpyxl): 6-sheet workbook — Summary, Domain Scores, Risk Matrix, Escalations, Recommendations, Audit Trail — with colour-coded urgency cells and frozen header rows
- **CSV** (stdlib): 6 separate datasets, ZIP bundle via `export_all_as_zip()`
- Both exporters gracefully handle empty runs, unicode payloads, and zero escalations

### Approval Workflow Engine (Stage 25)
- Formal state machine: DRAFT → PENDING_REVIEW → APPROVED / REJECTED, with REVISION_REQUESTED cycle and WITHDRAW path
- `VALID_TRANSITIONS` lookup table enforces all guards
- Immutable `WorkflowHistoryEntry` per transition — regulatory-grade audit trail
- RBAC-gated transitions (analysts submit; approvers approve/reject)
- Notification hook (pluggable; default logs)

### Monitoring (Stage 26)
- 20+ Prometheus metrics: counters (runs, agent calls, tokens, auth events), gauges (active sessions, circuit breaker state, cache size), histograms (run duration, agent latency, API response time, impact score distribution)
- No-op stub fallback — platform starts without `prometheus_client` installed
- Grafana dashboard JSON (13 panels) ready to import
- Health aggregator: per-component liveness probe (database, auth DB, circuit breaker, cache, Groq API config, filesystem, workflow DB)
- Readiness probe returns 200 or 503, suitable for Kubernetes readinessProbe

### CI/CD (Stage 27)
- `ci.yml`: ruff lint, black format check, mypy type check; unit tests on Python 3.10, 3.11, 3.12; Docker build + HEALTHCHECK
- `cd.yml`: build + push to GHCR; staged deploy to staging with smoke test; blue/green production deploy on semver tags; Grafana deploy annotation; Slack notification
- `security.yml`: Bandit SAST, pip-audit, Safety CVE check, Gitleaks secret scan, Trivy container scan, CodeQL analysis — runs weekly and on every push to main

### Analytics Engine (Stage 28)
- **Trend detection**: OLS linear regression, R² confidence, RISING / FLAT / FALLING classification
- **Anomaly detection**: dual Z-score + IQR method, severity levels (MODERATE / HIGH / EXTREME)
- **Forecasting**: linear extrapolation with optional EMA smoothing, 7-day horizon
- **Composite risk signal**: `escalation_risk_score()` — weighted combination of current mean, trend direction, and anomaly count
- **Time-series rollups**: daily run volume, weekly score trends, token consumption timeline, domain urgency heatmap, agent performance summary (p50/p95 latency)
- **Cross-tenant comparison**: KPI side-by-side for super-admin dashboards

---

## Test Results

| Test File | Tests | Passed | Skipped | Failed |
|-----------|------:|-------:|--------:|-------:|
| `test_agents.py` | 38 | 38 | 0 | 0 |
| `test_auth.py` | 62 | 62 | 0 | 0 |
| `test_api.py` | 20 | 3 | 17 | 0 |
| `test_exporters.py` | 34 | 34 | 0 | 0 |
| `test_workflows.py` | 38 | 38 | 0 | 0 |
| `test_monitoring.py` | 27 | 23 | 4 | 0 |
| `test_analytics.py` | 45 | 45 | 0 | 0 |
| **Total** | **264** | **243** | **21** | **0** |

The 21 skipped tests require optional dependencies (FastAPI test client,
openpyxl, prometheus_client) and skip cleanly via `@unittest.skipUnless`.
All 243 non-optional tests pass on Python 3.10, 3.11, and 3.12.

---

## File Inventory

```
79 total files  |  56 Python files  |  13,101 lines of Python
 6 YAML/config  |   7 Markdown docs  |   1,715 lines of documentation
```

| Package | Files | Responsibility |
|---------|------:|----------------|
| `agents/` | 4 | 8 AI agents (base + 3 implementation files) |
| `analytics/` | 4 | Metrics engine, aggregations, trend analysis |
| `api/` | 7 | FastAPI app, schemas, dependencies, 2 routers |
| `auth/` | 6 | JWT, PBKDF2, RBAC, auth service, models |
| `core/` | 6 | Orchestrator, typed models, cache, rate limiter, logger |
| `monitoring/` | 5 | Prometheus metrics, health probes, Grafana dashboard |
| `services/` | 7 | Groq client, PDF/Excel/CSV exporters, email, reports |
| `storage/` | 7 | Main DB, auth DB, workflow DB, seed files |
| `workflows/` | 3 | State machine engine and models |
| `tests/` | 8 | 7 test suites + `__init__.py` |
| `.github/workflows/` | 3 | ci.yml, cd.yml, security.yml |
| `docs/` | 4 | architecture, api_reference, deployment_guide, security |
| Root | 13 | streamlit_app, app, config, Dockerfile, compose, setup, README, LICENSE, requirements×2, .env.example, .gitignore, .streamlit/config.toml |

---

## Deployment

| Path | Command | Time |
|------|---------|------|
| Docker (SQLite) | `docker compose up app` | ~2 min |
| Docker (PostgreSQL) | `docker compose --profile full up` | ~3 min |
| Streamlit Cloud | Set `streamlit_app.py` + 2 secrets | ~90 sec |
| Local / Termux | `bash setup.sh && streamlit run streamlit_app.py` | ~5 min |
| Kubernetes | `kubectl apply -f k8s/` | ~30 min |

See [docs/deployment_guide.md](docs/deployment_guide.md) for all paths.

---

## Open Issues

**None.** This release ships with zero known open issues.

The one pre-release finding — a syntax error on line 850 of `streamlit_app.py`
caused by escaped quotes inside an f-string — was identified during final
release verification and fixed before tagging.

---

## Dependencies

**Base** (required — `requirements.txt`):
`streamlit` · `requests` · `python-dotenv` · `plotly` · `pandas` · `reportlab` · `tenacity` · `jsonschema`

**Enterprise** (optional — `requirements_enterprise.txt`):
`pydantic` · `fastapi` · `uvicorn` · `openpyxl` · `prometheus-client` · `psycopg2-binary` · `pytest`

The platform runs fully on the base requirements alone, with graceful
feature degradation for each missing optional dependency.

---

## Upgrade Notes

This is the initial production release. No migration path from a previous
version is required.

For future upgrades:
- SQLite schema uses `CREATE TABLE IF NOT EXISTS` — forward-compatible
- Auth tables (`auth_`) and workflow tables (`workflow_`) are namespaced — no collisions
- `ROLE_PERMISSIONS` matrix in `auth/models.py` is the single point of change for new permissions — no other files need modification

---

## Checksums

Verify the release archive before deployment:

```bash
sha256sum enterprise_maas_v2.0.0.zip
```

Compare against the value published on the GitHub Releases page.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright 2026 Enterprise Decision Intelligence Platform Contributors.

---

*Enterprise Decision Intelligence Platform v2.0.0*
*Python 3.10+ · Groq LLaMA 3.1 · Streamlit · FastAPI · ReportLab · openpyxl · Prometheus*
