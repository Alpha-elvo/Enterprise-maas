# Deployment Guide
## Enterprise Decision Intelligence Platform v2.0

---

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.10 | 3.11 |
| RAM | 512 MB | 2 GB |
| Disk | 500 MB | 5 GB |
| Internet | Yes (Groq API) | Yes |
| Groq API key | Free at console.groq.com | — |

---

## Option 1 — Termux (Android)

Tested on Samsung Galaxy A07 running Android 12.

```bash
# Install Termux from F-Droid (not Play Store — outdated there)
# Inside Termux:

pkg update && pkg install python git
pip install --break-system-packages -r requirements.txt

cp .env.example .env
nano .env          # add GROQ_API_KEY=your_key_here

bash setup.sh
streamlit run streamlit_app.py
# Visit http://localhost:8501 in your browser
```

For the REST API:
```bash
pip install --break-system-packages fastapi uvicorn
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

---

## Option 2 — Local (Ubuntu 22.04 / macOS 13+)

```bash
git clone https://github.com/yourorg/enterprise-decision-intelligence.git
cd enterprise-decision-intelligence

# Automated setup (creates venv, installs deps, seeds DB)
bash setup.sh

# Configure
cp .env.example .env
$EDITOR .env         # add GROQ_API_KEY and SECRET_KEY

# Dashboard
streamlit run streamlit_app.py

# CLI pipeline
python app.py
python app.py --pdf report.pdf --json results.json

# REST API (requires enterprise deps)
pip install -r requirements_enterprise.txt
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Option 3 — Docker (Single Container, SQLite)

The simplest production path. Zero external dependencies.

```bash
# Build (or pull from your registry)
docker build -t decision-intelligence:2.0.0 .

# Run
docker run -d \
  --name decision-intelligence \
  -p 8501:8501 \
  -e GROQ_API_KEY=your_key \
  -e SECRET_KEY=your-32-char-minimum-secret-key \
  -v $(pwd)/storage:/app/storage \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/reports:/app/reports \
  --restart unless-stopped \
  decision-intelligence:2.0.0

# Health check
curl http://localhost:8501/_stcore/health

# View logs
docker logs decision-intelligence -f
```

---

## Option 4 — Docker Compose (Full Stack with PostgreSQL)

```yaml
# .env for compose
GROQ_API_KEY=your_key
SECRET_KEY=your-32-char-minimum-secret-key
DATABASE_URL=postgresql://maas_user:maas_pass_change_me@postgres:5432/enterprise_maas
```

```bash
# Start full stack (app + PostgreSQL)
docker compose --profile full up -d

# Dashboard:        http://localhost:8502
# SQLite variant:   http://localhost:8501

# View all services
docker compose ps

# Tail logs
docker compose logs -f app

# Stop everything
docker compose down
```

---

## Option 5 — Streamlit Cloud (Recommended for Demos & PoC)

```
1. Push this repository to GitHub (public or private)

2. Visit share.streamlit.io → Sign in → New app

3. Set:
   Repository: your-org/enterprise-decision-intelligence
   Branch:     main
   Main file:  streamlit_app.py

4. Click "Advanced settings" → Secrets:
   GROQ_API_KEY = "gsk_..."
   SECRET_KEY   = "any-long-random-string-minimum-32-chars"

5. Click "Deploy" — live in ~90 seconds

Notes:
  - Free tier supports 1 GB RAM and 1 vCPU
  - SQLite file is ephemeral (resets on sleep/restart)
  - For persistent storage on Streamlit Cloud, switch DATABASE_URL
    to a hosted PostgreSQL (Neon, Supabase, or Railway — all have free tiers)
```

### Persistent PostgreSQL on Streamlit Cloud (Free)

```
1. Create a free Neon database: neon.tech → New project
2. Copy the connection string (starts with postgresql://)
3. Add to Streamlit Secrets:
   DATABASE_URL = "postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require"
4. Redeploy
```

---

## Option 6 — Kubernetes (Enterprise)

Helm-compatible deployment sketch. Adapt values.yaml for your cluster.

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: decision-intelligence
  namespace: ai-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: decision-intelligence
  template:
    metadata:
      labels:
        app: decision-intelligence
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
      - name: app
        image: ghcr.io/yourorg/decision-intelligence:2.0.0
        ports:
        - containerPort: 8501
        - containerPort: 9090   # Prometheus metrics
        env:
        - name: GROQ_API_KEY
          valueFrom:
            secretKeyRef:
              name: platform-secrets
              key: groq-api-key
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: platform-secrets
              key: jwt-secret
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: platform-secrets
              key: database-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /_stcore/health
            port: 8501
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /api/v1/health/ready
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
```

```bash
# Create secrets
kubectl create secret generic platform-secrets \
  --from-literal=groq-api-key="gsk_..." \
  --from-literal=jwt-secret="$(openssl rand -base64 48)" \
  --from-literal=database-url="postgresql://..." \
  -n ai-platform

# Deploy
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

---

## Switching from SQLite to PostgreSQL

```bash
# 1. Install driver
pip install psycopg2-binary

# 2. Set DATABASE_URL in .env
DATABASE_URL=postgresql://user:password@host:5432/enterprise_maas

# 3. Run setup to initialise schema on PostgreSQL
python -c "
from storage.database import Database
from storage.auth_db import AuthDatabase
from storage.workflow_db import WorkflowDatabase
Database(); AuthDatabase(); WorkflowDatabase()
print('Schema initialised on PostgreSQL')
"
```

The schema is identical — all `CREATE TABLE IF NOT EXISTS` statements
are SQL-92 compatible and run unchanged on PostgreSQL.

---

## Environment Variables — Complete Reference

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `GROQ_API_KEY` | — | ✅ | Groq inference key (console.groq.com) |
| `SECRET_KEY` | placeholder | ✅ | JWT signing secret (min 32 chars) |
| `MODEL_ID` | `llama-3.1-8b-instant` | — | Groq model identifier |
| `DATABASE_URL` | `sqlite:///storage/…` | — | PostgreSQL connection string |
| `HIGH_IMPACT_THRESHOLD` | `7` | — | Escalation gate (1–10) |
| `RATE_LIMIT_SLEEP` | `4.0` | — | Seconds between Groq calls |
| `MAX_RETRIES` | `3` | — | API retry attempts |
| `REQUEST_TIMEOUT` | `30` | — | HTTP timeout in seconds |
| `CB_FAILURE_THRESHOLD` | `5` | — | Circuit breaker trip count |
| `CB_RECOVERY_TIMEOUT` | `60` | — | Circuit breaker cooldown (s) |
| `CACHE_TTL` | `3600` | — | Cache entry lifetime (s) |
| `TEMPERATURE` | `0.3` | — | LLM temperature (0.0–1.0) |
| `MAX_TOKENS` | `1024` | — | Max tokens per agent call |
| `SMTP_HOST` | — | — | Email alert SMTP server |
| `SMTP_PORT` | `587` | — | SMTP port |
| `SMTP_USER` | — | — | SMTP username |
| `SMTP_PASS` | — | — | SMTP app password |
| `ALERT_RECIPIENTS` | — | — | Comma-separated alert emails |
| `ENABLE_AUTH` | `false` | — | Enforce auth on Streamlit UI |
| `DEFAULT_TENANT` | `default` | — | Default tenant ID |

---

## Post-Deployment Verification

```bash
# 1. Health check
curl http://localhost:8501/_stcore/health        # Streamlit
curl http://localhost:8000/api/v1/health         # REST API

# 2. Readiness (checks all dependencies)
curl http://localhost:8000/api/v1/health/ready   # Returns 200 or 503

# 3. Register admin user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@org.com",
       "password":"Adm1n!Secure","role":"tenant_admin"}'

# 4. Run CLI health check
python app.py --health

# 5. Run a test pipeline
python app.py --threshold 7

# 6. Run test suite
python -m unittest discover -s tests -v
```

---

## Monitoring Setup

```bash
# Start Prometheus (scrapes platform metrics on :9090)
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# Start Grafana
docker run -d -p 3000:3000 grafana/grafana

# Import dashboard:
# Grafana UI → Dashboards → Import → Upload monitoring/grafana_dashboard.json
```

---

## Backup and Recovery

```bash
# SQLite backup (safe while running via WAL mode)
cp storage/enterprise_maas.db storage/enterprise_maas.db.bak

# Restore
cp storage/enterprise_maas.db.bak storage/enterprise_maas.db

# PostgreSQL backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Audit log backup (JSON, append-only)
cp storage/audit_log.json storage/audit_log.$(date +%Y%m%d).json
```
