# Security Model
## Enterprise Decision Intelligence Platform v2.0

---

## Overview

The platform implements defence-in-depth across every layer:
authentication, authorisation, transport, secrets management, dependency
scanning, and container hardening. This document describes each control
and its implementation.

---

## Authentication

### Password Hashing

**Algorithm:** PBKDF2-HMAC-SHA256  
**Iterations:** 600,000 (NIST SP 800-132 recommendation for 2024)  
**Salt:** 32 bytes, OS-level CSPRNG (`os.urandom`)  
**Key length:** 32 bytes  
**Storage format:** `pbkdf2_sha256$600000$<salt_hex>$<hash_hex>`

No plaintext password ever leaves the `auth/password.py` module.
Timing-safe comparison via `hmac.compare_digest` throughout.

Rehash on login: if an existing hash was created with fewer iterations
(from a previous platform version), it is silently upgraded on successful
login without requiring a password change.

### JSON Web Tokens

**Algorithm:** HS256 (HMAC-SHA256)  
**Implementation:** Pure Python stdlib (`hmac`, `hashlib`, `base64`) —
no third-party JWT library required.

**Token lifetimes:**

| Token type | Expiry | Purpose |
|-----------|--------|---------|
| Access token | 30 minutes | API request authentication |
| Refresh token | 7 days | Access token rotation |

**Security properties:**
- JTI (JWT ID) per token — every token can be individually revoked
- `type` claim prevents access/refresh token substitution attacks
- Token revocation table (`auth_sessions`) checked on every request
- Constant-time signature comparison prevents timing attacks
- Refresh token rotation: old refresh token revoked on every `/auth/refresh` call
- `logout_all()` revokes all sessions on password change

**Claims payload (access token):**
```json
{
  "sub":       "<user_id>",
  "username":  "<username>",
  "jti":       "<uuid4>",
  "role":      "<role>",
  "tenant_id": "<tenant>",
  "type":      "access",
  "iat":       <unix_timestamp>,
  "exp":       <unix_timestamp>
}
```

### Brute-Force Protection

- Failed login attempts are recorded per (username, tenant_id)
- After **5 failures within 15 minutes**: account locked for 15 minutes
- Lockout stored in `auth_users.locked_until` (UTC ISO timestamp)
- Non-existent usernames trigger the same timing path as invalid passwords
  (constant-time PBKDF2 verify) to prevent username enumeration

---

## Authorisation (RBAC)

### Role Hierarchy

```
super_admin  >  tenant_admin  >  analyst  =  approver  >  viewer
```

### Permission Matrix

18 granular permissions, deny-by-default. A role receives **only** what is
explicitly listed in `auth/models.py:ROLE_PERMISSIONS`.

| Permission | super_admin | tenant_admin | analyst | approver | viewer |
|-----------|:-----------:|:------------:|:-------:|:--------:|:------:|
| runs:create | ✅ | ✅ | ✅ | — | — |
| runs:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| runs:delete | ✅ | ✅ | — | — | — |
| reports:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| reports:export | ✅ | ✅ | ✅ | ✅ | — |
| users:create | ✅ | ✅ | — | — | — |
| users:read | ✅ | ✅ | ✅ | ✅ | — |
| users:update | ✅ | ✅ | — | — | — |
| users:delete | ✅ | ✅ | — | — | — |
| workflows:create | ✅ | ✅ | ✅ | — | — |
| workflows:read | ✅ | ✅ | ✅ | ✅ | — |
| workflows:approve | ✅ | ✅ | — | ✅ | — |
| workflows:reject | ✅ | ✅ | — | ✅ | — |
| settings:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| settings:update | ✅ | ✅ | — | — | — |
| audit:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| tenants:create/update/delete | ✅ | — | — | — | — |
| tenants:read | ✅ | ✅ | — | — | — |

### Enforcement Layers

1. **`@require_permission` decorator** — applied to every API route handler
2. **`RBACEnforcer.require()`** — called inside service methods for double-check
3. **`AuthContext.require()`** — available to any code receiving an AuthContext
4. **Every RBAC decision** is logged to the audit trail with actor, permission,
   resource, and outcome

### Multi-Tenancy Isolation

- All database queries include `WHERE tenant_id = ?`
- Cross-tenant access requires `tenants:read` permission (super_admin only)
- Tenant ID is embedded in the JWT — cannot be changed mid-session
- Users can only see and modify resources within their own tenant

---

## Password Policy

Enforced at registration and password-change time (`auth/password.py`):

| Requirement | Rule |
|-------------|------|
| Minimum length | 10 characters |
| Uppercase | At least 1 |
| Lowercase | At least 1 |
| Digit | At least 1 |
| Special character | At least 1 from `!@#$%^&*()-_=+[]{}|;:,.<>?` |
| Maximum length | 128 characters |

Policy violations return HTTP 422 with a list of specific reasons.

---

## Secrets Management

**Never in source code.** All secrets load via `python-dotenv` from `.env`:

```
GROQ_API_KEY  — Groq inference API key
SECRET_KEY    — JWT signing secret (minimum 32 characters)
SMTP_PASS     — Email service credential
DATABASE_URL  — Database connection string (may contain password)
```

### Production Recommendations

```bash
# Generate a cryptographically secure SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Use a secrets manager in production:
# AWS:   aws ssm get-parameter --name /platform/groq-api-key --with-decryption
# GCP:   gcloud secrets versions access latest --secret="groq-api-key"
# Azure: az keyvault secret show --vault-name MyVault --name groq-api-key
# K8s:   kubectl create secret generic platform-secrets --from-env-file=.env
```

The `.gitignore` excludes `.env` from version control. Never commit secrets.

---

## API Security

### Transport

- All production deployments must use HTTPS (TLS 1.2+)
- Enforce via reverse proxy (nginx, Caddy, AWS ALB)
- HSTS header recommended: `Strict-Transport-Security: max-age=31536000`

### Request Validation

- All request bodies validated by Pydantic before processing
- String inputs sanitised (whitespace stripping, length limits)
- No raw SQL string interpolation anywhere — all queries use parameterised statements

### CORS

Default: `allow_origins=["*"]` (suitable for internal tools)  
Production: restrict to your domain in `api/main.py`:
```python
allow_origins=["https://your-dashboard.example.com"]
```

---

## Container Security

- **Non-root user**: Container runs as `appuser` (UID 1000)
- **No new privileges**: `securityContext.allowPrivilegeEscalation: false`
- **Read-only filesystem**: Source code mounted read-only; only `storage/`,
  `logs/`, `reports/` are writable volumes
- **Minimal base image**: `python:3.11-slim` — no unnecessary packages
- **Health check**: Docker HEALTHCHECK validates Streamlit health endpoint

---

## Security Scanning (CI/CD)

The `.github/workflows/security.yml` pipeline runs on every push to `main`
and weekly:

| Tool | Purpose |
|------|---------|
| **Bandit** | Python SAST — detects common security anti-patterns |
| **pip-audit** | PyPA vulnerability database check against all dependencies |
| **Safety** | CVE database scan of requirements files |
| **Gitleaks** | Secret scanning across full git history |
| **Trivy** | Container image vulnerability scanner (CRITICAL + HIGH) |
| **CodeQL** | GitHub's semantic SAST for Python (security-extended queries) |

---

## Audit Trail

Every significant action is recorded to `storage/audit_log.json`:

```json
{
  "timestamp":  "2026-01-15T08:00:00Z",
  "event_type": "USER_LOGIN",
  "severity":   "INFO",
  "run_id":     "",
  "record_id":  "",
  "agent_name": "auth_service",
  "data":       { "username": "alice", "ip": "10.0.0.1" }
}
```

Events captured:
- `USER_REGISTERED`, `USER_LOGIN`, `USER_LOGOUT`, `USER_LOGOUT_ALL`
- `PASSWORD_CHANGED`, `PASSWORD_ADMIN_RESET`
- `ACCOUNT_LOCKED`, `TOKEN_REFRESHED`
- `RBAC_CHECK` (every permission decision with granted/denied outcome)
- `API_CALL_SUCCESS`, `API_CALL_FAILURE`
- `CIRCUIT_OPEN`
- `ORCHESTRATOR_START`, `ORCHESTRATOR_COMPLETE`
- `AGENT_SUCCESS:*`, `AGENT_FAILURE:*`
- `WORKFLOW_CREATED`, `WORKFLOW_SUBMIT`, `WORKFLOW_APPROVE`, `WORKFLOW_REJECT`

The audit log is **append-only** and protected by the application layer.
In production, ship it to an immutable SIEM (Splunk, Datadog, ELK).

---

## Incident Response

### Suspected Credential Compromise

```bash
# Revoke all sessions for a user immediately
python -c "
from storage.auth_db import AuthDatabase
from auth.auth_service import AuthService
from auth.jwt_handler import JWTHandler
from config import config
db  = AuthDatabase()
jwt = JWTHandler(config.SECRET_KEY)
svc = AuthService(db=db, jwt=jwt)
# Get user ID from audit logs, then:
count = svc.logout_all('user-id-here')
print(f'Revoked {count} sessions')
"
```

### Suspected API Key Compromise

```
1. Rotate GROQ_API_KEY at console.groq.com
2. Update .env (or your secrets manager)
3. Restart the application
4. Review audit_log.json for anomalous API calls
```

---

## Responsible Disclosure

If you discover a security vulnerability in this platform, please contact
the security team via your organisation's private channel before public
disclosure. Do not file public GitHub issues for security vulnerabilities.
