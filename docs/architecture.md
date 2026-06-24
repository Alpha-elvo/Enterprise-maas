# Architecture Decision Records
## Enterprise Decision Intelligence Platform v2.0

---

## Overview

The platform is a production-grade multi-agent decision intelligence system
built on a layered architecture with strict separation of concerns, additive
extensibility, and zero-downtime deployability.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                           │
│   Streamlit Dashboard  │  FastAPI REST API  │  Prometheus /metrics  │
└───────────────┬─────────────────┬──────────────────────────────────-┘
                │                 │
┌───────────────▼─────────────────▼───────────────────────────────────┐
│                     ORCHESTRATION LAYER                             │
│         core/orchestrator.py — 8-Agent Pipeline Coordinator        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                         AGENT LAYER                                 │
│  Agent 1        Agent 2        Agent 3        Agent 4               │
│  Strategic      Executive      Risk           Evidence              │
│  Triage         Engine         Assessment     Validation            │
│                                                                     │
│  Agent 5        Agent 6        Agent 7        Agent 8               │
│  Recommendation Explainability Memory &       Report                │
│  Quality        Agent          Learning       Generation            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                       SERVICES LAYER                                │
│  GroqClient  │  PDFExporter  │  ExcelExporter  │  CSVExporter       │
│  ReportGen   │  EmailService │  WorkflowEngine │  AuthService       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                      INFRASTRUCTURE LAYER                           │
│  SQLite/PostgreSQL  │  TTL Cache/Redis  │  Circuit Breaker          │
│  JWT Auth           │  RBAC Engine      │  Prometheus Metrics       │
│  Audit Logger       │  Workflow DB      │  Analytics Engine         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ADR-001: SQLite Default with PostgreSQL Upgrade Path

**Status:** Accepted  
**Context:** Platform must run on a single Android device in Termux (dev)
and on enterprise Kubernetes (production) without code changes.  
**Decision:** Use raw `sqlite3` stdlib with schema identical to PostgreSQL.
Set `DATABASE_URL` env var to `postgresql://` to switch backends.  
**Consequences:** Zero cold-start dependencies. Production upgrade requires
only `psycopg2-binary` install and `DATABASE_URL` change.

---

## ADR-002: Stdlib-First JWT Implementation

**Status:** Accepted  
**Context:** Avoid dependency on PyJWT which is unavailable in restricted
environments.  
**Decision:** Implement HS256 JWT using `hmac`, `hashlib`, `base64` from
stdlib. Interface is identical to PyJWT so drop-in replacement is trivial.  
**Consequences:** No additional install required. Constant-time comparison
via `hmac.compare_digest` preserves security properties.

---

## ADR-003: 8-Agent Sequential Pipeline over Parallel Execution

**Status:** Accepted  
**Context:** Each downstream agent needs the output of upstream agents for
context enrichment (e.g., Agent 6 synthesises Agents 1–5 outputs).  
**Decision:** Sequential execution with explicit context injection between
agents. Parallelism deferred to a future async implementation.  
**Consequences:** Predictable execution trace, full audit trail, simpler
error isolation. Total wall-clock time scales linearly with record count.

---

## ADR-004: Deny-by-Default RBAC with Explicit Allow-Lists

**Status:** Accepted  
**Context:** Enterprise deployments require zero-trust access control.  
**Decision:** `ROLE_PERMISSIONS` matrix assigns explicit permission sets per
role. Any permission not listed is implicitly denied. New roles/permissions
added without touching consumer code (Open/Closed Principle).  
**Consequences:** Secure by default. Requires deliberate grant for every
permission. Audit trail captures every RBAC decision.

---

## ADR-005: Workflow State Machine with Immutable History

**Status:** Accepted  
**Context:** Hospitals and government agencies require full approval audit
trails for regulatory compliance.  
**Decision:** Every state transition produces an immutable `WorkflowHistoryEntry`
persisted atomically with the status update. History is append-only.  
**Consequences:** Full audit lineage from DRAFT to terminal state.
Cannot be modified after write (regulatory requirement met).

---

## ADR-006: Additive Module Extension Strategy

**Status:** Accepted  
**Context:** 29-stage incremental development requires each stage to not
break previous stages.  
**Decision:** New functionality always in new files/classes. Existing files
patched only for bug fixes via targeted string replacement. No file is ever
overwritten from scratch once production-tested.  
**Consequences:** 264/264 tests maintained throughout all 29 stages.
Zero regressions across the entire development arc.

---

## Component Inventory

| Component                  | File(s)                          | Tests |
|----------------------------|----------------------------------|-------|
| Domain Models              | `core/models.py`                 | 8     |
| TTL Cache                  | `core/cache.py`                  | 7     |
| Circuit Breaker            | `core/rate_limiter.py`           | 5     |
| JSON Recovery Parser       | `services/groq_client.py`        | 7     |
| 8-Agent Pipeline           | `agents/*.py`, `core/orchestrator.py` | 11 |
| SQLite Persistence         | `storage/database.py`            | 4     |
| JWT Handler                | `auth/jwt_handler.py`            | 14    |
| RBAC Engine                | `auth/rbac.py`, `auth/models.py` | 18    |
| Auth Service               | `auth/auth_service.py`           | 8     |
| Auth Database              | `storage/auth_db.py`             | 8     |
| FastAPI REST API           | `api/`                           | 20    |
| CSV Exporter               | `services/csv_exporter.py`       | 18    |
| Excel Exporter             | `services/excel_exporter.py`     | 8+    |
| Approval Workflow Engine   | `workflows/`                     | 38    |
| Prometheus Monitoring      | `monitoring/`                    | 27    |
| Analytics Engine           | `analytics/`                     | 45    |
| **Total**                  |                                  | **264** |
