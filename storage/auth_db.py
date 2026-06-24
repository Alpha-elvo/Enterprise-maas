"""
storage/auth_db.py — Authentication Persistence Layer
=======================================================
Additive extension to the existing storage layer.
Creates three new tables (auth_users, auth_sessions, auth_failed_logins)
in the SAME SQLite file as the main database.

Design rules:
  • Never modifies existing tables from storage/database.py
  • All new tables use the 'auth_' prefix to avoid collisions
  • Schema initialisation is idempotent (CREATE TABLE IF NOT EXISTS)
  • Uses parameterised queries throughout — no string interpolation
  • WAL mode inherited from the main connection pragma
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from auth.models import Role, UserRecord, SessionRecord
from config import config
from core.logger import get_logger

log = get_logger(__name__)

DB_PATH = config.STORAGE_DIR / "enterprise_maas.db"

# Lockout policy
_MAX_FAILED_ATTEMPTS  = 5
_LOCKOUT_WINDOW_MIN   = 15   # count failures within this window
_LOCKOUT_DURATION_MIN = 15   # lock for this long


class AuthDatabase:
    """
    Auth-specific database operations.

    Shares the existing SQLite file. Thread-safe when SQLite is compiled
    with SQLITE_THREADSAFE=1 (the default CPython distribution).
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_auth_schema()
        log.info("AuthDatabase initialised", extra={"db": str(self._path)})

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_auth_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                -- ── User accounts ────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id       TEXT PRIMARY KEY,
                    username      TEXT NOT NULL,
                    email         TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'viewer',
                    tenant_id     TEXT NOT NULL DEFAULT 'default',
                    is_active     INTEGER NOT NULL DEFAULT 1,
                    is_verified   INTEGER NOT NULL DEFAULT 0,
                    failed_logins INTEGER NOT NULL DEFAULT 0,
                    locked_until  TEXT,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL,
                    last_login    TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_auth_users_username_tenant
                    ON auth_users(username, tenant_id);
                CREATE INDEX IF NOT EXISTS
                    idx_auth_users_tenant
                    ON auth_users(tenant_id);
                CREATE INDEX IF NOT EXISTS
                    idx_auth_users_email
                    ON auth_users(email, tenant_id);

                -- ── JWT sessions (JTI revocation store) ──────────────────────
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    jti        TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    tenant_id  TEXT NOT NULL DEFAULT 'default',
                    token_type TEXT NOT NULL DEFAULT 'access',
                    issued_at  TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked    INTEGER NOT NULL DEFAULT 0,
                    ip_address TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
                );
                CREATE INDEX IF NOT EXISTS
                    idx_auth_sessions_user_id
                    ON auth_sessions(user_id);
                CREATE INDEX IF NOT EXISTS
                    idx_auth_sessions_revoked
                    ON auth_sessions(revoked, expires_at);

                -- ── Failed login tracking ─────────────────────────────────────
                CREATE TABLE IF NOT EXISTS auth_failed_logins (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    username   TEXT NOT NULL,
                    tenant_id  TEXT NOT NULL DEFAULT 'default',
                    ip_address TEXT DEFAULT '',
                    attempted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS
                    idx_auth_failed_username
                    ON auth_failed_logins(username, tenant_id, attempted_at);
            """)

    # ── User CRUD ─────────────────────────────────────────────────────────────

    def create_user(self, user: UserRecord) -> UserRecord:
        """
        Insert a new user record.

        Raises:
            sqlite3.IntegrityError: If username+tenant_id already exists.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_users
                    (user_id, username, email, password_hash, role, tenant_id,
                     is_active, is_verified, failed_logins, locked_until,
                     created_at, updated_at, last_login)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    user.user_id, user.username, user.email,
                    user.password_hash, user.role, user.tenant_id,
                    int(user.is_active), int(user.is_verified),
                    user.failed_logins, user.locked_until,
                    user.created_at, user.updated_at, user.last_login,
                ),
            )
        log.info(
            "User created",
            extra={"user_id": user.user_id, "username": user.username,
                   "tenant_id": user.tenant_id},
        )
        return user

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM auth_users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_username(
        self, username: str, tenant_id: str = "default"
    ) -> Optional[UserRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM auth_users WHERE username = ? AND tenant_id = ?",
                (username, tenant_id),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_email(
        self, email: str, tenant_id: str = "default"
    ) -> Optional[UserRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ? AND tenant_id = ?",
                (email, tenant_id),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def update_user(self, user: UserRecord) -> None:
        user.updated_at = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE auth_users SET
                    email=?, password_hash=?, role=?, is_active=?,
                    is_verified=?, failed_logins=?, locked_until=?,
                    updated_at=?, last_login=?
                WHERE user_id=?
                """,
                (
                    user.email, user.password_hash, user.role,
                    int(user.is_active), int(user.is_verified),
                    user.failed_logins, user.locked_until,
                    user.updated_at, user.last_login,
                    user.user_id,
                ),
            )

    def delete_user(self, user_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM auth_users WHERE user_id=?", (user_id,)
            )
        return cur.rowcount > 0

    def list_users(
        self,
        tenant_id: str = "default",
        limit:     int = 100,
        offset:    int = 0,
    ) -> list[UserRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM auth_users
                WHERE tenant_id=?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (tenant_id, limit, offset),
            ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def count_users(self, tenant_id: str = "default") -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM auth_users WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]

    # ── Session management ────────────────────────────────────────────────────

    def create_session(self, session: SessionRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions
                    (jti, user_id, tenant_id, token_type, issued_at,
                     expires_at, revoked, ip_address, user_agent)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    session.jti, session.user_id, session.tenant_id,
                    session.token_type, session.issued_at,
                    session.expires_at, int(session.revoked),
                    session.ip_address, session.user_agent,
                ),
            )

    def get_session(self, jti: str) -> Optional[SessionRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE jti=?", (jti,)
            ).fetchone()
        if not row:
            return None
        return SessionRecord(
            jti        = row["jti"],
            user_id    = row["user_id"],
            tenant_id  = row["tenant_id"],
            token_type = row["token_type"],
            issued_at  = row["issued_at"],
            expires_at = row["expires_at"],
            revoked    = bool(row["revoked"]),
            ip_address = row["ip_address"] or "",
            user_agent = row["user_agent"] or "",
        )

    def revoke_session(self, jti: str) -> bool:
        """Mark a single JTI as revoked. Returns True if found."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE auth_sessions SET revoked=1 WHERE jti=?", (jti,)
            )
        return cur.rowcount > 0

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (e.g., on password change)."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE auth_sessions SET revoked=1 WHERE user_id=? AND revoked=0",
                (user_id,),
            )
        count = cur.rowcount
        log.info(
            "All sessions revoked",
            extra={"user_id": user_id, "session_count": count},
        )
        return count

    def is_session_revoked(self, jti: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT revoked FROM auth_sessions WHERE jti=?", (jti,)
            ).fetchone()
        if row is None:
            return True     # Unknown JTI treated as revoked (fail-secure)
        return bool(row[0])

    def purge_expired_sessions(self) -> int:
        """Remove expired sessions. Call periodically (e.g., nightly cron)."""
        cutoff = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at < ?", (cutoff,)
            )
        return cur.rowcount

    # ── Brute-force protection ────────────────────────────────────────────────

    def record_failed_login(
        self, username: str, tenant_id: str = "default", ip_address: str = ""
    ) -> int:
        """
        Record a failed login attempt and return the failure count within the window.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_failed_logins (username, tenant_id, ip_address, attempted_at)
                VALUES (?,?,?,?)
                """,
                (username, tenant_id, ip_address, _now()),
            )
        return self.get_failed_login_count(username, tenant_id)

    def get_failed_login_count(
        self,
        username:  str,
        tenant_id: str = "default",
        window_minutes: int = _LOCKOUT_WINDOW_MIN,
    ) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        ).isoformat()
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT COUNT(*) FROM auth_failed_logins
                WHERE username=? AND tenant_id=? AND attempted_at > ?
                """,
                (username, tenant_id, cutoff),
            ).fetchone()[0]

    def reset_failed_logins(self, username: str, tenant_id: str = "default") -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM auth_failed_logins WHERE username=? AND tenant_id=?",
                (username, tenant_id),
            )

    def lock_user(
        self,
        user_id:          str,
        duration_minutes: int = _LOCKOUT_DURATION_MIN,
    ) -> str:
        """Set a lockout timestamp and return it."""
        locked_until = (
            datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        ).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_users SET locked_until=?, updated_at=? WHERE user_id=?",
                (locked_until, _now(), user_id),
            )
        log.warning(
            "User account locked",
            extra={"user_id": user_id, "locked_until": locked_until},
        )
        return locked_until

    def unlock_user(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_users SET locked_until=NULL, failed_logins=0, "
                "updated_at=? WHERE user_id=?",
                (_now(), user_id),
            )

    def is_user_locked(self, user: UserRecord) -> bool:
        if not user.locked_until:
            return False
        try:
            locked_dt = datetime.fromisoformat(user.locked_until)
            return datetime.now(timezone.utc) < locked_dt
        except ValueError:
            return False

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_auth_stats(self, tenant_id: str = "default") -> dict:
        with self._connect() as conn:
            total_users   = conn.execute(
                "SELECT COUNT(*) FROM auth_users WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]
            active_users  = conn.execute(
                "SELECT COUNT(*) FROM auth_users WHERE tenant_id=? AND is_active=1",
                (tenant_id,),
            ).fetchone()[0]
            active_sessions = conn.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE tenant_id=? AND revoked=0",
                (tenant_id,),
            ).fetchone()[0]
            role_counts = {}
            for row in conn.execute(
                "SELECT role, COUNT(*) FROM auth_users WHERE tenant_id=? GROUP BY role",
                (tenant_id,),
            ).fetchall():
                role_counts[row[0]] = row[1]
        return {
            "total_users":     total_users,
            "active_users":    active_users,
            "active_sessions": active_sessions,
            "users_by_role":   role_counts,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id       = row["user_id"],
            username      = row["username"],
            email         = row["email"],
            password_hash = row["password_hash"],
            role          = row["role"],
            tenant_id     = row["tenant_id"],
            is_active     = bool(row["is_active"]),
            is_verified   = bool(row["is_verified"]),
            failed_logins = row["failed_logins"],
            locked_until  = row["locked_until"],
            created_at    = row["created_at"],
            updated_at    = row["updated_at"],
            last_login    = row["last_login"],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
