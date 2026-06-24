# REST API Reference
## Enterprise Decision Intelligence Platform v2.0

**Base URL:** `https://your-domain.com/api/v1`  
**Interactive docs:** `/api/docs` (Swagger UI) · `/api/redoc` (ReDoc)  
**Authentication:** Bearer token (JWT) — obtain via `POST /auth/login`

---

## Authentication

All endpoints except `/health` and `/auth/login` require:
```
Authorization: Bearer <access_token>
```

### POST /auth/register
Create a new user account and receive a token pair.

**Request**
```json
{
  "username": "alice",
  "email": "alice@corp.com",
  "password": "Str0ng!Pass1",
  "role": "analyst",
  "tenant_id": "acme_corp"
}
```

**Response 201**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "alice",
    "email": "alice@corp.com",
    "role": "analyst",
    "tenant_id": "acme_corp",
    "is_active": true,
    "created_at": "2026-01-15T08:00:00Z"
  }
}
```

**Errors**
| Code | Reason |
|------|--------|
| 409 | Username already exists in this tenant |
| 422 | Password does not meet policy (10+ chars, upper, lower, digit, special) |
| 400 | Invalid role value |

---

### POST /auth/login
Authenticate and receive a JWT token pair.

**Request**
```json
{ "username": "alice", "password": "Str0ng!Pass1", "tenant_id": "acme_corp" }
```

**Response 200** — same shape as `/auth/register`

**Errors**
| Code | Reason |
|------|--------|
| 401 | Invalid credentials |
| 403 | Account locked (too many failed attempts) |

---

### POST /auth/refresh
Rotate refresh token and receive a new token pair. The old refresh token is immediately revoked.

**Request**
```json
{ "refresh_token": "eyJ..." }
```

**Response 200** — same shape as `/auth/login`

---

### POST /auth/logout
Revoke the current access token.

**Response 200**
```json
{ "message": "Successfully logged out." }
```

---

### POST /auth/password
Change the current user's password. Revokes **all** active sessions.

**Request**
```json
{ "current_password": "OldP@ss1", "new_password": "NewStr0ng!Pass" }
```

**Response 204** (No Content)

---

### GET /auth/me
Return the current user's profile and permission list.

**Response 200**
```json
{
  "user": { "user_id": "...", "username": "alice", "role": "analyst", ... },
  "permissions": [
    "runs:create", "runs:read", "reports:read", "reports:export",
    "workflows:create", "workflows:read", "audit:read", "settings:read"
  ]
}
```

---

## Analysis Runs

### POST /runs
Submit a new 8-agent pipeline run (executes asynchronously).

**Required permission:** `runs:create`

**Request**
```json
{
  "threshold": 7,
  "records": null
}
```

`records` is optional. Pass `null` to use the built-in 5-domain default matrix.  
Pass a custom array to analyse your own data:

```json
{
  "threshold": 6,
  "records": [
    {
      "record_id": "HOSP-001",
      "domain": "Health",
      "payload": "ICU occupancy at 98%. 3 critical patients awaiting transfer..."
    }
  ]
}
```

**Response 202**
```json
{
  "run_id": "550e8400-...",
  "status": "accepted",
  "message": "Run submitted. Poll /runs/{run_id} for status."
}
```

---

### GET /runs
List all runs for the current tenant, newest first.

**Required permission:** `runs:read`

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number (1-based) |
| `per_page` | integer | 20 | Results per page (max 100) |

**Response 200**
```json
{
  "runs": [
    {
      "run_id": "550e8400-...",
      "status": "completed",
      "tenant_id": "acme_corp",
      "started_at": "2026-01-15T08:00:00Z",
      "completed_at": "2026-01-15T08:04:32Z",
      "total_records": 5,
      "escalated": 3,
      "errors": 0,
      "total_tokens": 18420
    }
  ],
  "meta": { "page": 1, "per_page": 20, "total": 47, "total_pages": 3 }
}
```

---

### GET /runs/{run_id}
Retrieve full run details including per-record agent outputs.

**Required permission:** `runs:read`

**Response 200**
```json
{
  "run_id": "550e8400-...",
  "status": "completed",
  "summary": {
    "total_records_processed": 5,
    "escalated_records": 3,
    "below_threshold_records": 1,
    "errors_encountered": 0,
    "highest_impact_record": "HLTH-001",
    "total_tokens_used": 18420
  },
  "records": [ { "record_id": "HLTH-001", "domain": "Health", ... } ]
}
```

---

### DELETE /runs/{run_id}
Delete a run and all associated records.

**Required permission:** `runs:delete`

**Response 204** (No Content)

---

## User Management

### GET /users
List users in the current tenant.

**Required permission:** `users:read`

**Response 200**
```json
{
  "users": [
    {
      "user_id": "...", "username": "alice", "email": "alice@corp.com",
      "role": "analyst", "tenant_id": "acme_corp",
      "is_active": true, "created_at": "...", "last_login": "..."
    }
  ],
  "meta": { "page": 1, "per_page": 20, "total": 12, "total_pages": 1 }
}
```

---

### GET /users/{user_id}
Get a single user by ID.

**Required permission:** `users:read`

---

### PATCH /users/{user_id}
Update user role, active status, or email.

**Required permission:** `users:update`

**Request** (all fields optional)
```json
{ "role": "approver", "is_active": true, "email": "new@corp.com" }
```

---

### DELETE /users/{user_id}
Deactivate a user and revoke all their sessions.

**Required permission:** `users:delete`

**Response 204**

---

## Health & Readiness

### GET /health
Liveness probe. Always returns 200 if the process is running.

**Response 200** (no auth required)
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "timestamp": "2026-01-15T08:00:00Z"
}
```

---

### GET /health/ready
Readiness probe. Checks all downstream dependencies.

**Response 200 / 503**
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "timestamp": "2026-01-15T08:00:00Z",
  "uptime_s": 3600,
  "components": [
    { "name": "database",        "status": "ok",    "latency_ms": 2  },
    { "name": "auth_database",   "status": "ok",    "latency_ms": 1  },
    { "name": "circuit_breaker", "status": "ok",    "latency_ms": 0,
      "metadata": { "state": "CLOSED", "failure_count": 0 } },
    { "name": "cache",           "status": "ok",    "latency_ms": 0,
      "metadata": { "size": 12, "hit_rate": 0.87 } },
    { "name": "groq_api",        "status": "ok",    "latency_ms": 0  },
    { "name": "filesystem",      "status": "ok",    "latency_ms": 1  }
  ]
}
```

Returns `503` with `"status": "unhealthy"` if any critical component fails.

---

## Error Response Format

All errors follow this shape:

```json
{ "error": "InvalidCredentialsError", "detail": "Invalid username or password." }
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 202 | Accepted (async job submitted) |
| 204 | No Content |
| 400 | Bad Request — validation failed |
| 401 | Unauthorized — missing or invalid token |
| 403 | Forbidden — token valid but permission denied |
| 404 | Not Found |
| 409 | Conflict — duplicate resource |
| 422 | Unprocessable Entity — schema validation failed |
| 429 | Too Many Requests — rate limit (Groq API) |
| 500 | Internal Server Error |
| 503 | Service Unavailable — dependency failure |

---

## Rate Limiting

The Groq API backend enforces a 4-second guard between calls via a
token-bucket rate limiter. Under sustained load, the platform queues
requests rather than dropping them.

Circuit breaker trips after 5 consecutive API failures and suspends
outbound calls for 60 seconds before probing recovery.

---

## Pagination

All list endpoints support `?page=N&per_page=M` query parameters.
Maximum `per_page` is 100. Response always includes a `meta` object:

```json
{ "page": 2, "per_page": 20, "total": 157, "total_pages": 8 }
```

---

## Roles and Permissions

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
| tenants:* | ✅ | — | — | — | — |
