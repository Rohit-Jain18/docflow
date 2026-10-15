"""
Durable SQLite job queue and storage module for Docflow Windows Agent.

Implements the requirements specified in docs/AGENT_SPEC.md §§5, 6, 10:
- Uses SQLite with WAL mode, foreign keys, and busy timeout on every connection.
- Schema versioning and transactional migrations via `schema_migrations`.
- Atomic enqueueing with deterministic canonical fingerprinting (v1) and deduplication.
- Preserves local-only phone-bearing filenames and paths; never transmits or logs them.
- No PDF bytes stored in SQLite; media reference field is nullable.
- Safe worker lease management: atomic claims (BEGIN IMMEDIATE), renewal, release, and recovery.
- Validated lifecycle state transitions and conservative error handling.
- Source file retention metadata: tracks cleanup eligibility and operator hold.
- Agent settings for non-secret values only; rejects credentials and tokens.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import sqlite3
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from docflow_agent.config import AgentConfig, is_prohibited_key, normalize_key
from docflow_agent.pdf import DEFAULT_MAX_PDF_SIZE_BYTES, ValidationResult
from docflow_agent.quarantine import QuarantineResult
from docflow_agent.recipient import mask_phone
from docflow_agent.stability import StabilityResult
from docflow_agent.watcher import process_candidate_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class QueueError(Exception):
    """Base error for queue and storage operations."""


class DatabaseCorruptedError(QueueError):
    """Raised when the SQLite database fails integrity check."""


class MigrationError(QueueError):
    """Raised when schema migration fails."""


class InvalidStateTransitionError(QueueError):
    """Raised when an illegal job state transition is attempted."""


class ProhibitedSecretError(QueueError):
    """Raised when attempting to store sensitive keys/secrets in agent_settings."""


class JobNotFoundError(QueueError):
    """Raised when a requested job does not exist."""


class QueueStateError(QueueError):
    """Raised when queue state or arguments are invalid."""


# ---------------------------------------------------------------------------
# Job Status & Lifecycle State Machine
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    """Allowed job statuses as defined in docs/AGENT_SPEC.md §5."""

    DISCOVERED = "discovered"
    WAITING_STABILITY = "waiting_stability"
    QUEUED = "queued"
    VALIDATED = "validated"
    METADATA_REGISTERING = "metadata_registering"
    METADATA_REGISTERED = "metadata_registered"
    UPLOADING = "uploading"
    MEDIA_UPLOADED = "media_uploaded"
    MEDIA_REFERENCE_ATTACHING = "media_reference_attaching"
    REGISTERED = "registered"
    RETRY_WAIT = "retry_wait"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    READ = "read"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    ARCHIVED = "archived"


ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.DISCOVERED.value: frozenset({
        JobStatus.WAITING_STABILITY.value,
        JobStatus.QUARANTINED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.WAITING_STABILITY.value: frozenset({
        JobStatus.VALIDATED.value,
        JobStatus.QUEUED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.QUARANTINED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.QUEUED.value: frozenset({
        JobStatus.VALIDATED.value,
        JobStatus.METADATA_REGISTERING.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.QUARANTINED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.VALIDATED.value: frozenset({
        JobStatus.METADATA_REGISTERING.value,
        JobStatus.QUEUED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.QUARANTINED.value,
        JobStatus.FAILED.value,
        JobStatus.ARCHIVED.value,
    }),
    JobStatus.METADATA_REGISTERING.value: frozenset({
        JobStatus.METADATA_REGISTERED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.METADATA_REGISTERED.value: frozenset({
        JobStatus.UPLOADING.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.UPLOADING.value: frozenset({
        JobStatus.MEDIA_UPLOADED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.MEDIA_UPLOADED.value: frozenset({
        JobStatus.MEDIA_REFERENCE_ATTACHING.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.MEDIA_REFERENCE_ATTACHING.value: frozenset({
        JobStatus.REGISTERED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.REGISTERED.value: frozenset({
        JobStatus.ACCEPTED.value,
        JobStatus.RETRY_WAIT.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.RETRY_WAIT.value: frozenset({
        JobStatus.VALIDATED.value,
        JobStatus.METADATA_REGISTERING.value,
        JobStatus.UPLOADING.value,
        JobStatus.MEDIA_REFERENCE_ATTACHING.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
        JobStatus.FAILED.value,
    }),
    JobStatus.RECONCILIATION_REQUIRED.value: frozenset({
        JobStatus.REGISTERED.value,
        JobStatus.ACCEPTED.value,
        JobStatus.DELIVERED.value,
        JobStatus.READ.value,
        JobStatus.FAILED.value,
        JobStatus.RETRY_WAIT.value,
    }),
    JobStatus.ACCEPTED.value: frozenset({
        JobStatus.DELIVERED.value,
        JobStatus.READ.value,
        JobStatus.FAILED.value,
        JobStatus.RECONCILIATION_REQUIRED.value,
    }),
    JobStatus.DELIVERED.value: frozenset({
        JobStatus.READ.value,
        JobStatus.ARCHIVED.value,
    }),
    JobStatus.READ.value: frozenset({
        JobStatus.ARCHIVED.value,
    }),
    JobStatus.QUARANTINED.value: frozenset({
        JobStatus.ARCHIVED.value,
        JobStatus.VALIDATED.value,  # Authorized revalidation / release
    }),
    JobStatus.FAILED.value: frozenset({
        JobStatus.RETRY_WAIT.value,  # Authorized retry after operator review
        JobStatus.ARCHIVED.value,
    }),
    JobStatus.ARCHIVED.value: frozenset(),  # Terminal state
}

ALLOWLISTED_EVENT_DETAIL_KEYS = frozenset({
    "action",
    "attempt",
    "attempt_count",
    "cleanup_status",
    "duration_seconds",
    "error_code",
    "extension_seconds",
    "file_size_bytes",
    "from_status",
    "lease_duration_seconds",
    "mtime_ns",
    "operator_hold",
    "previous_worker_id",
    "reason",
    "reason_code",
    "recovered_count",
    "retry_delay_seconds",
    "status",
    "to_status",
    "worker_id",
})


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class JobRecord:
    """Immutable representation of a persistent job in the SQLite queue."""

    id: str
    source_path: str
    source_basename: str
    branch_id: str
    recipient_phone_e164: str
    content_sha256: str
    file_size_bytes: int
    mtime_ns: int
    idempotency_key: str
    status: str
    docflow_report_id: str | None = None
    media_reference: str | None = None
    media_reference_expires_at: str | None = None
    attempt_count: int = 0
    next_attempt_at: str | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    last_error_code: str | None = None
    created_at: str = ""
    updated_at: str = ""
    accepted_at: str | None = None
    archived_at: str | None = None
    terminal_confirmed_at: str | None = None
    cleanup_eligible_at: str | None = None
    cleanup_status: str = "retained_in_flight"
    operator_hold: bool = False
    deletion_verified_at: str | None = None

    @property
    def recipient_e164(self) -> str:
        """Alias for recipient_phone_e164."""
        return self.recipient_phone_e164

    def __repr__(self) -> str:
        """Privacy-preserving representation: masks phone and omits local file path."""
        masked = mask_phone(self.recipient_phone_e164)
        return (
            f"JobRecord(id={self.id!r}, status={self.status!r}, "
            f"recipient={masked!r}, content_sha256={self.content_sha256[:8]!r}..., "
            f"attempts={self.attempt_count})"
        )


@dataclasses.dataclass(frozen=True)
class JobEvent:
    """An audited lifecycle event for a job."""

    id: int
    job_id: str
    event_type: str
    occurred_at: str
    safe_details: dict[str, Any] | None = None
    error_code: str | None = None


@dataclasses.dataclass(frozen=True)
class EnqueueResult:
    """Outcome of attempting to enqueue a candidate file."""

    job: JobRecord
    is_duplicate: bool


# ---------------------------------------------------------------------------
# Idempotency & Canonical Fingerprint
# ---------------------------------------------------------------------------

def compute_fingerprint(
    branch_id: str,
    recipient_phone_e164: str,
    content_sha256: str,
) -> str:
    """Compute the deterministic 64-character lowercase hex canonical fingerprint.

    Formula from docs/AGENT_SPEC.md §6:
        sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)
    """
    if not branch_id or not isinstance(branch_id, str) or not branch_id.strip():
        raise QueueStateError("branch_id is required and must be a non-empty string.")
    if not recipient_phone_e164 or not isinstance(recipient_phone_e164, str):
        raise QueueStateError("recipient_phone_e164 is required.")
    if not content_sha256 or not isinstance(content_sha256, str):
        raise QueueStateError("content_sha256 is required.")

    canonical_str = (
        f"v1|{branch_id.strip()}|{recipient_phone_e164.strip()}|{content_sha256.strip().lower()}"
    )
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest().lower()


def sanitize_event_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Allowlist safe keys and redact any potentially sensitive keys/values."""
    if not details:
        return None
    sanitized: dict[str, Any] = {}
    for k, v in details.items():
        if k in ALLOWLISTED_EVENT_DETAIL_KEYS:
            sanitized[k] = v
    return sanitized or None


def split_sql_script(script: str) -> list[str]:
    """Split a SQL script into individual executable statements using sqlite3.complete_statement."""
    statements: list[str] = []
    current_statement: list[str] = []
    for line in script.splitlines(keepends=True):
        current_statement.append(line)
        combined = "".join(current_statement)
        if sqlite3.complete_statement(combined):
            stmt = combined.strip()
            if stmt:
                statements.append(stmt)
            current_statement = []
    if current_statement:
        combined = "".join(current_statement).strip()
        if combined:
            statements.append(combined)
    return statements


# ---------------------------------------------------------------------------
# Database Migrations
# ---------------------------------------------------------------------------

_MIGRATION_V1_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_basename TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    recipient_phone_e164 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    docflow_report_id TEXT,
    media_reference TEXT,
    media_reference_expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    accepted_at TEXT,
    archived_at TEXT,
    terminal_confirmed_at TEXT,
    cleanup_eligible_at TEXT,
    cleanup_status TEXT NOT NULL DEFAULT 'retained_in_flight',
    operator_hold INTEGER NOT NULL DEFAULT 0,
    deletion_verified_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(lease_owner, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_jobs_cleanup ON jobs(cleanup_status, cleanup_eligible_at);
CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    safe_details_json TEXT,
    error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);

CREATE TABLE IF NOT EXISTS processed_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""

DEFAULT_MIGRATIONS: list[tuple[int, str]] = [
    (1, _MIGRATION_V1_SQL),
]


# ---------------------------------------------------------------------------
# JobQueue Class
# ---------------------------------------------------------------------------

class JobQueue:
    """Thread-safe, durable SQLite job queue."""

    def __init__(
        self,
        db_path: pathlib.Path | str,
        *,
        busy_timeout_seconds: float = 5.0,
        cleanup_retention_hours: int = 24,
        failed_retention_days: int = 14,
        migrations: list[tuple[int, str]] | None = None,
    ) -> None:
        self.db_path = pathlib.Path(db_path).resolve()
        self.busy_timeout_seconds = max(0.1, float(busy_timeout_seconds))
        self.cleanup_retention_hours = max(1, int(cleanup_retention_hours))
        self.failed_retention_days = max(1, int(failed_retention_days))
        self._migrations = migrations if migrations is not None else DEFAULT_MIGRATIONS

        # Verify integrity of existing database before modifying
        self._check_integrity_if_exists()

        # Initialize schema and apply pending migrations
        self._initialize_database()

    @classmethod
    def from_config(cls, config: AgentConfig) -> JobQueue:
        """Create a JobQueue instance from an AgentConfig."""
        return cls(
            db_path=config.db_path,
            cleanup_retention_hours=config.cleanup_retention_hours,
            failed_retention_days=config.failed_retention_days,
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a dedicated, configured connection with strict pragmas."""
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.busy_timeout_seconds,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Disable automatic transaction management so we can use explicit BEGIN IMMEDIATE
        conn.isolation_level = None

        # Apply mandatory SQLite pragmas
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)};")
        with contextlib.suppress(sqlite3.DatabaseError):
            conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        return conn

    @contextlib.contextmanager
    def _read_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing a configured read connection."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _write_transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager executing inside an atomic write transaction (BEGIN IMMEDIATE)."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                with contextlib.suppress(Exception):
                    conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _check_integrity_if_exists(self) -> None:
        """Verify database integrity. Fail closed and preserve the file if corrupt."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return

        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=self.busy_timeout_seconds)
            cur = conn.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
            if not rows or rows[0][0] != "ok":
                errors = "; ".join(str(r[0]) for r in rows)
                raise DatabaseCorruptedError(
                    f"SQLite database failed integrity check: {errors}. "
                    "Preserving database file for diagnostic analysis."
                )
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            raise DatabaseCorruptedError(
                f"SQLite database is corrupt or unreadable: {type(exc).__name__}. "
                "Preserving database file for diagnostic analysis."
            ) from exc
        finally:
            if conn is not None:
                conn.close()

    def _initialize_database(self) -> None:
        """Ensure schema_migrations exists and apply pending migrations atomically in order."""
        conn = self._connect()
        try:
            # 1. Ensure schema_migrations table exists under an immediate write lock
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                """)
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    with contextlib.suppress(Exception):
                        conn.execute("ROLLBACK")
                raise

            # 2. Apply each pending migration in self._migrations atomically
            for version, sql in self._migrations:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = conn.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?;",
                        (version,),
                    )
                    if cur.fetchone() is not None:
                        # Already applied by another process or earlier step
                        conn.execute("COMMIT")
                        continue

                    # Execute each statement in the migration within the active transaction
                    statements = split_sql_script(sql)
                    for stmt in statements:
                        conn.execute(stmt)

                    now_iso = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                        (version, now_iso),
                    )
                    conn.execute("COMMIT")
                except Exception as exc:
                    if conn.in_transaction:
                        with contextlib.suppress(Exception):
                            conn.execute("ROLLBACK")
                    raise MigrationError(
                        f"Migration to schema version {version} failed: {exc}. "
                        "Preserving database file for diagnosis."
                    ) from exc
        finally:
            conn.close()

    def get_schema_version(self) -> int:
        """Get the highest applied schema migration version."""
        with self._read_connection() as conn:
            cur = conn.execute("SELECT MAX(version) AS max_v FROM schema_migrations;")
            row = cur.fetchone()
            return int(row["max_v"]) if row and row["max_v"] is not None else 0

    # -----------------------------------------------------------------------
    # Helper: Convert SQLite row to JobRecord
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_job(row: sqlite3.Row | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord(
            id=str(row["id"]),
            source_path=str(row["source_path"]),
            source_basename=str(row["source_basename"]),
            branch_id=str(row["branch_id"]),
            recipient_phone_e164=str(row["recipient_phone_e164"]),
            content_sha256=str(row["content_sha256"]),
            file_size_bytes=int(row["file_size_bytes"]),
            mtime_ns=int(row["mtime_ns"]),
            idempotency_key=str(row["idempotency_key"]),
            status=str(row["status"]),
            docflow_report_id=str(row["docflow_report_id"]) if row["docflow_report_id"] else None,
            media_reference=str(row["media_reference"]) if row["media_reference"] else None,
            media_reference_expires_at=(
                str(row["media_reference_expires_at"]) if row["media_reference_expires_at"] else None
            ),
            attempt_count=int(row["attempt_count"]),
            next_attempt_at=str(row["next_attempt_at"]) if row["next_attempt_at"] else None,
            lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
            lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] else None,
            last_error_code=str(row["last_error_code"]) if row["last_error_code"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            accepted_at=str(row["accepted_at"]) if row["accepted_at"] else None,
            archived_at=str(row["archived_at"]) if row["archived_at"] else None,
            terminal_confirmed_at=(
                str(row["terminal_confirmed_at"]) if row["terminal_confirmed_at"] else None
            ),
            cleanup_eligible_at=(
                str(row["cleanup_eligible_at"]) if row["cleanup_eligible_at"] else None
            ),
            cleanup_status=str(row["cleanup_status"]),
            operator_hold=bool(row["operator_hold"]),
            deletion_verified_at=(
                str(row["deletion_verified_at"]) if row["deletion_verified_at"] else None
            ),
        )

    # -----------------------------------------------------------------------
    # Enqueue & Fingerprint Deduplication
    # -----------------------------------------------------------------------

    def enqueue(
        self,
        validation_result: ValidationResult,
        branch_id: str,
    ) -> EnqueueResult:
        """Atomically enqueue a validated PDF job or return existing duplicate job."""
        if not validation_result.is_valid:
            raise QueueStateError("Cannot enqueue an invalid validation result.")
        if not validation_result.content_sha256:
            raise QueueStateError("ValidationResult is missing content_sha256.")
        if not validation_result.recipient_phone_e164:
            raise QueueStateError("ValidationResult is missing recipient_phone_e164.")

        fingerprint = compute_fingerprint(
            branch_id=branch_id,
            recipient_phone_e164=validation_result.recipient_phone_e164,
            content_sha256=validation_result.content_sha256,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        with self._write_transaction() as conn:
            # Check for existing fingerprint
            cur = conn.execute(
                "SELECT job_id FROM processed_fingerprints WHERE fingerprint = ?;",
                (fingerprint,),
            )
            existing_fp = cur.fetchone()

            if existing_fp is not None:
                job_id = existing_fp["job_id"]
                conn.execute(
                    "UPDATE processed_fingerprints SET last_seen_at = ? WHERE fingerprint = ?;",
                    (now_iso, fingerprint),
                )
                cur_job = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
                job = self._row_to_job(cur_job.fetchone())
                if job is None:
                    raise QueueStateError(f"Fingerprint points to missing job '{job_id}'.")

                # Record duplicate replay event
                self._append_event_conn(
                    conn,
                    job_id=job.id,
                    event_type="duplicate_fingerprint_observed",
                    safe_details={"action": "ignored_duplicate"},
                )

                logger.debug("Duplicate fingerprint observed for job %s", job.id)
                return EnqueueResult(job=job, is_duplicate=True)

            # Insert new job
            import uuid
            new_job_id = str(uuid.uuid4())

            conn.execute(
                """
                INSERT INTO jobs (
                    id, source_path, source_basename, branch_id, recipient_phone_e164,
                    content_sha256, file_size_bytes, mtime_ns, idempotency_key, status,
                    attempt_count, cleanup_status, operator_hold, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    new_job_id,
                    str(validation_result.source_path),
                    validation_result.source_basename,
                    branch_id.strip(),
                    validation_result.recipient_phone_e164,
                    validation_result.content_sha256,
                    validation_result.file_size_bytes,
                    validation_result.mtime_ns,
                    fingerprint,
                    JobStatus.VALIDATED.value,
                    0,
                    "retained_in_flight",
                    0,
                    now_iso,
                    now_iso,
                ),
            )

            # Insert processed fingerprint record
            conn.execute(
                """
                INSERT INTO processed_fingerprints (
                    fingerprint, job_id, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?);
                """,
                (fingerprint, new_job_id, now_iso, now_iso),
            )

            # Record initial enqueued event
            self._append_event_conn(
                conn,
                job_id=new_job_id,
                event_type="job_enqueued",
                safe_details={
                    "status": JobStatus.VALIDATED.value,
                    "file_size_bytes": validation_result.file_size_bytes,
                    "mtime_ns": validation_result.mtime_ns,
                },
            )

            cur_new = conn.execute("SELECT * FROM jobs WHERE id = ?;", (new_job_id,))
            created_job = self._row_to_job(cur_new.fetchone())
            if created_job is None:
                raise QueueStateError(f"Failed to retrieve newly created job '{new_job_id}'.")

            logger.info("Enqueued job %s (status=validated)", created_job.id)
            return EnqueueResult(job=created_job, is_duplicate=False)

    # -----------------------------------------------------------------------
    # Job Queries
    # -----------------------------------------------------------------------

    def get_job(self, job_id: str) -> JobRecord | None:
        """Fetch a job by its UUID."""
        with self._read_connection() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            return self._row_to_job(cur.fetchone())

    def get_job_by_fingerprint(self, fingerprint: str) -> JobRecord | None:
        """Fetch a job by its unique fingerprint / idempotency key."""
        with self._read_connection() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?;", (fingerprint,))
            return self._row_to_job(cur.fetchone())

    def list_jobs(
        self,
        status: JobStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRecord]:
        """List jobs with bounded pagination."""
        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)

        status_str = status.value if isinstance(status, JobStatus) else status

        with self._read_connection() as conn:
            if status_str is not None:
                cur = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at ASC
                    LIMIT ? OFFSET ?;
                    """,
                    (status_str, bounded_limit, bounded_offset),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT * FROM jobs
                    ORDER BY created_at ASC
                    LIMIT ? OFFSET ?;
                    """,
                    (bounded_limit, bounded_offset),
                )

            return [self._row_to_job(row) for row in cur.fetchall() if row is not None]  # type: ignore[misc]

    def get_queue_counts(self) -> dict[str, int]:
        """Return counts of queued, retry_wait, and quarantined jobs for heartbeat telemetry."""
        with self._read_connection() as conn:
            cur = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status IN ('validated', 'metadata_registering', 'metadata_registered', 'uploading', 'media_uploaded', 'media_reference_attaching', 'registered') THEN 1 ELSE 0 END) AS queued,
                    SUM(CASE WHEN status = 'retry_wait' THEN 1 ELSE 0 END) AS retry_wait,
                    SUM(CASE WHEN status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined
                FROM jobs;
                """
            )
            row = cur.fetchone()
            return {
                "queued": int(row["queued"] or 0) if row else 0,
                "retry_wait": int(row["retry_wait"] or 0) if row else 0,
                "quarantined": int(row["quarantined"] or 0) if row else 0,
            }

    def get_last_successful_job_at(self) -> str | None:
        """Return the timestamp of the most recent successful job (accepted/delivered/read)."""
        with self._read_connection() as conn:
            cur = conn.execute(
                """
                SELECT MAX(COALESCE(accepted_at, terminal_confirmed_at)) AS last_success
                FROM jobs
                WHERE status IN ('accepted', 'delivered', 'read');
                """
            )
            row = cur.fetchone()
            return str(row["last_success"]) if row and row["last_success"] else None

    # -----------------------------------------------------------------------
    # State Transitions & Lifecycle Updates
    # -----------------------------------------------------------------------

    def update_status(
        self,
        job_id: str,
        new_status: JobStatus | str,
        *,
        error_code: str | None = None,
        next_attempt_at: str | None = None,
        increment_attempt: bool = False,
        docflow_report_id: str | None = None,
        media_reference: str | None = None,
        media_reference_expires_at: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> JobRecord:
        """Perform a validated lifecycle transition and update job fields."""
        target_status = new_status.value if isinstance(new_status, JobStatus) else str(new_status)

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if row is None:
                raise JobNotFoundError(f"Job '{job_id}' not found.")

            current_status = row["status"]

            # Validate transition if status is changing
            if target_status != current_status:
                allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, frozenset())
                if target_status not in allowed:
                    raise InvalidStateTransitionError(
                        f"Illegal transition for job '{job_id}': '{current_status}' -> '{target_status}'."
                    )

            # Determine updated terminal and retention values
            terminal_confirmed_at = row["terminal_confirmed_at"]
            cleanup_eligible_at = row["cleanup_eligible_at"]
            cleanup_status = row["cleanup_status"]
            accepted_at = row["accepted_at"]
            archived_at = row["archived_at"]
            operator_hold = bool(row["operator_hold"])

            if target_status in (JobStatus.DELIVERED.value, JobStatus.READ.value):
                terminal_confirmed_at = terminal_confirmed_at or now_iso
                if not operator_hold:
                    cleanup_status = "retention_active"
                    cleanup_eligible_at = (
                        now_dt + timedelta(hours=self.cleanup_retention_hours)
                    ).isoformat()
                else:
                    cleanup_status = "operator_hold"

            elif target_status in (JobStatus.FAILED.value, JobStatus.QUARANTINED.value):
                terminal_confirmed_at = terminal_confirmed_at or now_iso
                if not operator_hold:
                    cleanup_status = "retention_active"
                    cleanup_eligible_at = (
                        now_dt + timedelta(days=self.failed_retention_days)
                    ).isoformat()
                else:
                    cleanup_status = "operator_hold"

            elif target_status in (JobStatus.RETRY_WAIT.value, JobStatus.VALIDATED.value):
                # Retry invalidates previous cleanup eligibility
                if current_status in (JobStatus.FAILED.value, JobStatus.QUARANTINED.value):
                    cleanup_eligible_at = None
                    cleanup_status = "retained_in_flight"

            elif target_status == JobStatus.ACCEPTED.value:
                accepted_at = accepted_at or now_iso

            elif target_status == JobStatus.ARCHIVED.value:
                archived_at = archived_at or now_iso

            # Update attempts and fields
            new_attempt_count = row["attempt_count"] + (1 if increment_attempt else 0)
            final_report_id = docflow_report_id if docflow_report_id is not None else row["docflow_report_id"]
            final_media_ref = media_reference if media_reference is not None else row["media_reference"]
            final_media_exp = (
                media_reference_expires_at
                if media_reference_expires_at is not None
                else row["media_reference_expires_at"]
            )
            final_next_attempt = (
                next_attempt_at if next_attempt_at is not None else row["next_attempt_at"]
            )
            final_error_code = error_code if error_code is not None else row["last_error_code"]

            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    attempt_count = ?,
                    docflow_report_id = ?,
                    media_reference = ?,
                    media_reference_expires_at = ?,
                    next_attempt_at = ?,
                    last_error_code = ?,
                    accepted_at = ?,
                    archived_at = ?,
                    terminal_confirmed_at = ?,
                    cleanup_eligible_at = ?,
                    cleanup_status = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    target_status,
                    new_attempt_count,
                    final_report_id,
                    final_media_ref,
                    final_media_exp,
                    final_next_attempt,
                    final_error_code,
                    accepted_at,
                    archived_at,
                    terminal_confirmed_at,
                    cleanup_eligible_at,
                    cleanup_status,
                    now_iso,
                    job_id,
                ),
            )

            # Record event
            event_details = {"from_status": current_status, "to_status": target_status}
            if details:
                event_details.update(details)
            self._append_event_conn(
                conn,
                job_id=job_id,
                event_type="status_changed",
                safe_details=event_details,
                error_code=final_error_code,
            )

            cur_updated = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            updated_job = self._row_to_job(cur_updated.fetchone())
            if updated_job is None:
                raise QueueStateError(f"Failed to fetch updated job '{job_id}'.")
            return updated_job

    # -----------------------------------------------------------------------
    # Worker Leases
    # -----------------------------------------------------------------------

    def claim_job(
        self,
        worker_id: str,
        lease_duration_seconds: float = 60.0,
        eligible_statuses: list[str] | None = None,
    ) -> JobRecord | None:
        """Atomically claim the next eligible job for worker_id."""
        if not worker_id or not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string.")

        if eligible_statuses is None:
            eligible_statuses = [
                JobStatus.VALIDATED.value,
                JobStatus.RETRY_WAIT.value,
                JobStatus.QUEUED.value,
            ]

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        lease_expires_iso = (now_dt + timedelta(seconds=max(1.0, lease_duration_seconds))).isoformat()

        placeholders = ",".join("?" for _ in eligible_statuses)

        with self._write_transaction() as conn:
            # Query candidate job
            query = f"""
                SELECT id FROM jobs
                WHERE (lease_owner IS NULL OR lease_expires_at <= ?)
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND status IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT 1;
            """
            cur = conn.execute(query, [now_iso, now_iso, *eligible_statuses])
            row = cur.fetchone()
            if row is None:
                return None

            job_id = row["id"]

            # Conditional atomic claim
            claim_query = """
                UPDATE jobs
                SET lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND (lease_owner IS NULL OR lease_expires_at <= ?);
            """
            cur_claim = conn.execute(
                claim_query,
                (worker_id.strip(), lease_expires_iso, now_iso, job_id, now_iso),
            )
            if cur_claim.rowcount == 0:
                # Concurrent worker claim race; failed to claim
                return None

            self._append_event_conn(
                conn,
                job_id=job_id,
                event_type="lease_claimed",
                safe_details={
                    "worker_id": worker_id.strip(),
                    "lease_duration_seconds": lease_duration_seconds,
                },
            )

            cur_claimed = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            return self._row_to_job(cur_claimed.fetchone())

    def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        extension_seconds: float = 60.0,
    ) -> bool:
        """Extend the lease expiry for an actively claimed job."""
        if not job_id or not worker_id:
            return False

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        new_expires_iso = (now_dt + timedelta(seconds=max(1.0, extension_seconds))).isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND lease_owner = ?
                  AND lease_expires_at > ?;
                """,
                (new_expires_iso, now_iso, job_id, worker_id.strip(), now_iso),
            )
            if cur.rowcount > 0:
                self._append_event_conn(
                    conn,
                    job_id=job_id,
                    event_type="lease_renewed",
                    safe_details={
                        "worker_id": worker_id.strip(),
                        "extension_seconds": extension_seconds,
                    },
                )
                return True
            return False

    def release_lease(self, job_id: str, worker_id: str) -> bool:
        """Release a worker's active lease immediately."""
        if not job_id or not worker_id:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND lease_owner = ?;
                """,
                (now_iso, job_id, worker_id.strip()),
            )
            if cur.rowcount > 0:
                self._append_event_conn(
                    conn,
                    job_id=job_id,
                    event_type="lease_released",
                    safe_details={"worker_id": worker_id.strip()},
                )
                return True
            return False

    def recover_expired_leases(self, now_iso: str | None = None) -> int:
        """Clear expired worker leases without deleting or losing jobs."""
        current_time = now_iso or datetime.now(timezone.utc).isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute(
                """
                SELECT id, lease_owner FROM jobs
                WHERE lease_owner IS NOT NULL
                  AND lease_expires_at <= ?;
                """,
                (current_time,),
            )
            expired_rows = cur.fetchall()
            if not expired_rows:
                return 0

            conn.execute(
                """
                UPDATE jobs
                SET lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE lease_owner IS NOT NULL
                  AND lease_expires_at <= ?;
                """,
                (current_time, current_time),
            )

            for row in expired_rows:
                self._append_event_conn(
                    conn,
                    job_id=row["id"],
                    event_type="expired_lease_recovered",
                    safe_details={"previous_worker_id": row["lease_owner"]},
                )

            logger.info("Recovered %d expired worker lease(s)", len(expired_rows))
            return len(expired_rows)

    # -----------------------------------------------------------------------
    # Operator Hold & Cleanup State
    # -----------------------------------------------------------------------

    def set_operator_hold(self, job_id: str, hold: bool) -> JobRecord:
        """Place or release an operator hold suspending source-file deletion."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if row is None:
                raise JobNotFoundError(f"Job '{job_id}' not found.")

            terminal_confirmed_at = row["terminal_confirmed_at"]
            cleanup_eligible_at = row["cleanup_eligible_at"]

            if hold:
                new_hold = 1
                new_cleanup_status = "operator_hold"
                event_type = "operator_hold_set"
            else:
                new_hold = 0
                event_type = "operator_hold_released"
                if terminal_confirmed_at is not None:
                    # In terminal state: resume retention clock
                    new_cleanup_status = "retention_active"
                    # If deadline expired or < 24h away, give at least 24h retention window
                    recalc_dt = now_dt + timedelta(hours=24)
                    if cleanup_eligible_at is None or cleanup_eligible_at <= now_iso:
                        cleanup_eligible_at = recalc_dt.isoformat()
                else:
                    new_cleanup_status = "retained_in_flight"

            conn.execute(
                """
                UPDATE jobs
                SET operator_hold = ?,
                    cleanup_status = ?,
                    cleanup_eligible_at = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (new_hold, new_cleanup_status, cleanup_eligible_at, now_iso, job_id),
            )

            self._append_event_conn(
                conn,
                job_id=job_id,
                event_type=event_type,
                safe_details={"operator_hold": bool(new_hold), "cleanup_status": new_cleanup_status},
            )

            cur_updated = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            updated_job = self._row_to_job(cur_updated.fetchone())
            if updated_job is None:
                raise QueueStateError(f"Failed to fetch updated job '{job_id}'.")
            return updated_job

    def get_cleanup_candidates(
        self,
        now_iso: str | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        """Fetch jobs eligible for source PDF cleanup verification."""
        current_time = now_iso or datetime.now(timezone.utc).isoformat()
        bounded_limit = max(1, min(limit, 500))

        with self._read_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('delivered', 'read', 'failed', 'quarantined')
                  AND cleanup_status IN ('retention_active', 'eligible_for_deletion')
                  AND operator_hold = 0
                  AND cleanup_eligible_at IS NOT NULL
                  AND cleanup_eligible_at <= ?
                  AND (lease_owner IS NULL OR lease_expires_at <= ?)
                ORDER BY cleanup_eligible_at ASC
                LIMIT ?;
                """,
                (current_time, current_time, bounded_limit),
            )
            return [self._row_to_job(r) for r in cur.fetchall() if r is not None]  # type: ignore[misc]

    def mark_source_deleted(
        self,
        job_id: str,
        deletion_verified_at: str | None = None,
    ) -> JobRecord:
        """Atomically record verified best-effort source PDF deletion in SQLite."""
        now_iso = deletion_verified_at or datetime.now(timezone.utc).isoformat()

        with self._write_transaction() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET cleanup_status = 'deleted',
                    deletion_verified_at = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (now_iso, now_iso, job_id),
            )
            if cur.rowcount == 0:
                raise JobNotFoundError(f"Job '{job_id}' not found.")

            self._append_event_conn(
                conn,
                job_id=job_id,
                event_type="source_file_deleted",
                safe_details={"cleanup_status": "deleted"},
            )

            cur_job = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
            updated = self._row_to_job(cur_job.fetchone())
            if updated is None:
                raise QueueStateError(f"Failed to fetch updated job '{job_id}'.")
            return updated

    # -----------------------------------------------------------------------
    # Job Events
    # -----------------------------------------------------------------------

    def append_event(
        self,
        job_id: str,
        event_type: str,
        safe_details: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> JobEvent:
        """Append an audited event to job_events."""
        with self._write_transaction() as conn:
            return self._append_event_conn(
                conn,
                job_id=job_id,
                event_type=event_type,
                safe_details=safe_details,
                error_code=error_code,
            )

    def _append_event_conn(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        event_type: str,
        safe_details: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> JobEvent:
        """Internal helper to insert an event within an existing connection."""
        sanitized = sanitize_event_details(safe_details)
        details_json = json.dumps(sanitized, sort_keys=True) if sanitized else None
        now_iso = datetime.now(timezone.utc).isoformat()

        cur = conn.execute(
            """
            INSERT INTO job_events (
                job_id, event_type, occurred_at, safe_details_json, error_code
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (job_id, event_type, now_iso, details_json, error_code),
        )
        return JobEvent(
            id=int(cur.lastrowid),
            job_id=job_id,
            event_type=event_type,
            occurred_at=now_iso,
            safe_details=sanitized,
            error_code=error_code,
        )

    def list_events(self, job_id: str) -> list[JobEvent]:
        """Fetch all events for a given job in chronological order."""
        with self._read_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY id ASC;
                """,
                (job_id,),
            )
            events: list[JobEvent] = []
            for row in cur.fetchall():
                details = None
                if row["safe_details_json"]:
                    with contextlib.suppress(Exception):
                        details = json.loads(row["safe_details_json"])
                events.append(
                    JobEvent(
                        id=int(row["id"]),
                        job_id=str(row["job_id"]),
                        event_type=str(row["event_type"]),
                        occurred_at=str(row["occurred_at"]),
                        safe_details=details,
                        error_code=str(row["error_code"]) if row["error_code"] else None,
                    )
                )
            return events

    # -----------------------------------------------------------------------
    # Non-Secret Agent Settings
    # -----------------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """Fetch a non-secret setting value from agent_settings."""
        with self._read_connection() as conn:
            cur = conn.execute("SELECT value FROM agent_settings WHERE key = ?;", (key,))
            row = cur.fetchone()
            return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Persist a non-secret setting. Prohibits secret keys/credentials/tokens."""
        norm = normalize_key(key)
        if is_prohibited_key(norm) or any(
            stem in norm for stem in ("token", "secret", "password", "credential", "auth")
        ):
            raise ProhibitedSecretError(
                f"Prohibited secret key '{key}' cannot be stored in agent_settings. "
                "Credentials and tokens must be stored in secure credential storage."
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO agent_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at;
                """,
                (key, str(value), now_iso),
            )

    def set_settings_atomic(self, settings_dict: dict[str, str]) -> None:
        """Persist multiple non-secret settings within a single atomic write transaction."""
        for key in settings_dict:
            norm = normalize_key(key)
            if is_prohibited_key(norm) or any(
                stem in norm for stem in ("token", "secret", "password", "credential", "auth")
            ):
                raise ProhibitedSecretError(
                    f"Prohibited secret key '{key}' cannot be stored in agent_settings. "
                    "Credentials and tokens must be stored in secure credential storage."
                )

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._write_transaction() as conn:
            for key, value in settings_dict.items():
                conn.execute(
                    """
                    INSERT INTO agent_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at;
                    """,
                    (key, str(value), now_iso),
                )

    def list_settings(self) -> dict[str, str]:
        """List all non-secret settings currently persisted."""
        with self._read_connection() as conn:
            cur = conn.execute("SELECT key, value FROM agent_settings ORDER BY key ASC;")
            return {str(row["key"]): str(row["value"]) for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Watcher Pipeline Integration Adapter
# ---------------------------------------------------------------------------

def handle_watcher_result(
    queue: JobQueue,
    branch_id: str,
    stability: StabilityResult,
    validation: ValidationResult | None,
    quarantine: QuarantineResult | None,
) -> EnqueueResult | None:
    """Adapter accepting watcher pipeline results and enqueueing only valid, stable PDFs.

    Rules:
    - If stability check timed out, do not enqueue (remain retryable, never quarantined).
    - If quarantine occurred or validation failed, do not enqueue.
    - If stable and valid, enqueue into queue.
    """
    if not stability.is_stable:
        return None
    if quarantine is not None or validation is None or not validation.is_valid:
        return None
    return queue.enqueue(validation, branch_id=branch_id)


def create_watcher_enqueue_adapter(
    queue: JobQueue,
    branch_id: str,
    *,
    watch_folder: pathlib.Path | str | None = None,
    quarantine_folder: pathlib.Path | str | None = None,
    max_size_bytes: int = DEFAULT_MAX_PDF_SIZE_BYTES,
    default_region: str = "IN",
    sample_interval_seconds: float = 2.0,
    required_samples: int = 3,
    timeout_seconds: float = 120.0,
) -> Callable[[pathlib.Path | str], EnqueueResult | None]:
    """Create a callback for Watcher that runs candidate processing and enqueues valid PDFs."""
    def callback(path: pathlib.Path | str) -> EnqueueResult | None:
        stab, val, quar = process_candidate_file(
            path,
            watch_folder=watch_folder,
            quarantine_folder=quarantine_folder,
            max_size_bytes=max_size_bytes,
            default_region=default_region,
            sample_interval_seconds=sample_interval_seconds,
            required_samples=required_samples,
            timeout_seconds=timeout_seconds,
        )
        return handle_watcher_result(queue, branch_id, stab, val, quar)

    return callback
