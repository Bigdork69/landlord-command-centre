"""Database setup and connection management for SQLite and PostgreSQL."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Generator, Optional, Any

from models import (
    Certificate,
    CertificateType,
    ComplianceEvent,
    EventPriority,
    EventStatus,
    Property,
    PropertyType,
    RentFrequency,
    RequiredDocument,
    ServedDocument,
    Tenancy,
    User,
)

# Try to import psycopg2 for PostgreSQL support
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


# Database schema version for migrations
SCHEMA_VERSION = 1

# SQLite schema
SQLITE_SCHEMA = """
-- Users table (must be first for foreign keys)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    property_type TEXT NOT NULL DEFAULT 'house',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Tenancies table
CREATE TABLE IF NOT EXISTS tenancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    tenant_names TEXT NOT NULL,
    tenancy_start_date DATE,
    fixed_term_end_date DATE,
    rent_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    rent_frequency TEXT NOT NULL DEFAULT 'monthly',
    deposit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    deposit_protected BOOLEAN DEFAULT 0,
    deposit_protection_date DATE,
    deposit_scheme TEXT,
    prescribed_info_served BOOLEAN DEFAULT 0,
    prescribed_info_date DATE,
    how_to_rent_served BOOLEAN DEFAULT 0,
    how_to_rent_date DATE,
    is_active BOOLEAN DEFAULT 1,
    document_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

-- Certificates table
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    certificate_type TEXT NOT NULL,
    issue_date DATE,
    expiry_date DATE,
    document_path TEXT,
    served_to_tenant_date DATE,
    reference_number TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

-- Compliance events table
CREATE TABLE IF NOT EXISTS compliance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    tenancy_id INTEGER,
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    due_date DATE,
    completed_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id),
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id)
);

-- Documents served to tenants
CREATE TABLE IF NOT EXISTS served_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tenancy_id INTEGER NOT NULL,
    document_type TEXT NOT NULL,
    served_date DATE,
    proof_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id),
    UNIQUE(tenancy_id, document_type)
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

# PostgreSQL schema
POSTGRES_SCHEMA = """
-- Users table (must be first for foreign keys)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    property_type TEXT NOT NULL DEFAULT 'house',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tenancies table
CREATE TABLE IF NOT EXISTS tenancies (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    property_id INTEGER NOT NULL REFERENCES properties(id),
    tenant_names TEXT NOT NULL,
    tenancy_start_date DATE,
    fixed_term_end_date DATE,
    rent_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    rent_frequency TEXT NOT NULL DEFAULT 'monthly',
    deposit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    deposit_protected BOOLEAN DEFAULT FALSE,
    deposit_protection_date DATE,
    deposit_scheme TEXT,
    prescribed_info_served BOOLEAN DEFAULT FALSE,
    prescribed_info_date DATE,
    how_to_rent_served BOOLEAN DEFAULT FALSE,
    how_to_rent_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    document_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Certificates table
CREATE TABLE IF NOT EXISTS certificates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    property_id INTEGER NOT NULL REFERENCES properties(id),
    certificate_type TEXT NOT NULL,
    issue_date DATE,
    expiry_date DATE,
    document_path TEXT,
    served_to_tenant_date DATE,
    reference_number TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Compliance events table
CREATE TABLE IF NOT EXISTS compliance_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    property_id INTEGER NOT NULL REFERENCES properties(id),
    tenancy_id INTEGER REFERENCES tenancies(id),
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    due_date DATE,
    completed_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documents served to tenants
CREATE TABLE IF NOT EXISTS served_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tenancy_id INTEGER NOT NULL REFERENCES tenancies(id),
    document_type TEXT NOT NULL,
    served_date DATE,
    proof_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenancy_id, document_type)
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


class Database:
    """Database manager supporting both SQLite and PostgreSQL."""

    def __init__(self, db_path: Path = None):
        """Initialize database connection.

        Uses DATABASE_URL environment variable for PostgreSQL if set,
        otherwise falls back to SQLite at db_path.
        """
        self.database_url = os.environ.get("DATABASE_URL")
        self.use_postgres = bool(self.database_url) and HAS_POSTGRES

        if self.use_postgres:
            # Fix Render's postgres:// URL to postgresql://
            if self.database_url.startswith("postgres://"):
                self.database_url = self.database_url.replace("postgres://", "postgresql://", 1)
        else:
            self.db_path = db_path
            if self.db_path:
                self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists (SQLite only)."""
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        """Context manager for database connections."""
        if self.use_postgres:
            conn = psycopg2.connect(self.database_url)
            conn.autocommit = False
            # Use RealDictCursor for dict-like row access
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                yield _PostgresConnection(conn, cursor)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
                conn.close()
        else:
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            conn.row_factory = sqlite3.Row
            try:
                yield _SqliteConnection(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def initialize(self) -> None:
        """Initialize the database schema."""
        if self.use_postgres:
            with self.connection() as conn:
                # Execute each statement separately for PostgreSQL
                for statement in POSTGRES_SCHEMA.split(';'):
                    statement = statement.strip()
                    if statement:
                        conn.execute(statement)
                # Set schema version if not exists
                conn.execute("SELECT version FROM schema_version LIMIT 1")
                if conn.fetchone() is None:
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (%s)",
                        (SCHEMA_VERSION,),
                    )
        else:
            with self.connection() as conn:
                conn.executescript(SQLITE_SCHEMA)
                cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
                if cursor.fetchone() is None:
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )

    def _placeholder(self) -> str:
        """Return the appropriate placeholder for the database type."""
        return "%s" if self.use_postgres else "?"

    def _placeholders(self, count: int) -> str:
        """Return multiple placeholders."""
        p = self._placeholder()
        return ", ".join([p] * count)

    def get_schema_version(self) -> int:
        """Get current schema version."""
        with self.connection() as conn:
            conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = conn.fetchone()
            return row["version"] if row else 0

    # Property CRUD operations

    def create_property(self, prop: Property, user_id: int) -> int:
        """Create a new property and return its ID."""
        p = self._placeholder()
        with self.connection() as conn:
            if self.use_postgres:
                conn.execute(
                    f"""INSERT INTO properties (user_id, address, postcode, property_type)
                       VALUES ({p}, {p}, {p}, {p}) RETURNING id""",
                    (user_id, prop.address, prop.postcode, prop.property_type.value),
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO properties (user_id, address, postcode, property_type)
                       VALUES ({p}, {p}, {p}, {p})""",
                    (user_id, prop.address, prop.postcode, prop.property_type.value),
                )
                return cursor.lastrowid

    def get_property(self, property_id: int, user_id: int) -> Optional[Property]:
        """Get a property by ID (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM properties WHERE id = {p} AND user_id = {p}",
                (property_id, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_property(row)
            return None

    def get_property_by_address(self, address: str, postcode: str) -> Optional[Property]:
        """Find a property by address and postcode."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM properties WHERE address = {p} AND postcode = {p}",
                (address, postcode),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_property(row)
            return None

    def list_properties(self, user_id: int) -> list[Property]:
        """List all properties for a user."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM properties WHERE user_id = {p} ORDER BY address",
                (user_id,),
            )
            return [self._row_to_property(row) for row in conn.fetchall()]

    def _row_to_property(self, row) -> Property:
        """Convert database row to Property object."""
        return Property(
            id=row["id"],
            address=row["address"],
            postcode=row["postcode"],
            property_type=PropertyType(row["property_type"]),
            created_at=self._parse_datetime(row["created_at"]),
        )

    def _parse_datetime(self, value) -> datetime:
        """Parse datetime from database (handles both string and datetime)."""
        if value is None:
            return datetime.now()
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _parse_date(self, value) -> Optional[date]:
        """Parse date from database (handles both string and date)."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        return date.fromisoformat(value)

    # Tenancy CRUD operations

    def create_tenancy(self, tenancy: Tenancy, user_id: int) -> int:
        """Create a new tenancy and return its ID."""
        p = self._placeholder()
        with self.connection() as conn:
            params = (
                user_id,
                tenancy.property_id,
                tenancy.tenant_names,
                tenancy.tenancy_start_date.isoformat() if tenancy.tenancy_start_date else None,
                tenancy.fixed_term_end_date.isoformat() if tenancy.fixed_term_end_date else None,
                str(tenancy.rent_amount),
                tenancy.rent_frequency.value,
                str(tenancy.deposit_amount),
                tenancy.deposit_protected,
                tenancy.deposit_protection_date.isoformat() if tenancy.deposit_protection_date else None,
                tenancy.deposit_scheme,
                tenancy.prescribed_info_served,
                tenancy.prescribed_info_date.isoformat() if tenancy.prescribed_info_date else None,
                tenancy.how_to_rent_served,
                tenancy.how_to_rent_date.isoformat() if tenancy.how_to_rent_date else None,
                tenancy.is_active,
                tenancy.document_path,
                tenancy.notes,
            )
            if self.use_postgres:
                conn.execute(
                    f"""INSERT INTO tenancies (
                        user_id, property_id, tenant_names, tenancy_start_date, fixed_term_end_date,
                        rent_amount, rent_frequency, deposit_amount, deposit_protected,
                        deposit_protection_date, deposit_scheme, prescribed_info_served,
                        prescribed_info_date, how_to_rent_served, how_to_rent_date,
                        is_active, document_path, notes
                    ) VALUES ({self._placeholders(18)}) RETURNING id""",
                    params,
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO tenancies (
                        user_id, property_id, tenant_names, tenancy_start_date, fixed_term_end_date,
                        rent_amount, rent_frequency, deposit_amount, deposit_protected,
                        deposit_protection_date, deposit_scheme, prescribed_info_served,
                        prescribed_info_date, how_to_rent_served, how_to_rent_date,
                        is_active, document_path, notes
                    ) VALUES ({self._placeholders(18)})""",
                    params,
                )
                return cursor.lastrowid

    def get_tenancy(self, tenancy_id: int, user_id: int) -> Optional[Tenancy]:
        """Get a tenancy by ID (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM tenancies WHERE id = {p} AND user_id = {p}",
                (tenancy_id, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_tenancy(row)
            return None

    def list_tenancies(self, user_id: int, active_only: bool = False) -> list[Tenancy]:
        """List tenancies for a user, optionally filtered to active only."""
        p = self._placeholder()
        with self.connection() as conn:
            if active_only:
                conn.execute(
                    f"SELECT * FROM tenancies WHERE user_id = {p} AND is_active = true ORDER BY created_at DESC",
                    (user_id,),
                )
            else:
                conn.execute(
                    f"SELECT * FROM tenancies WHERE user_id = {p} ORDER BY created_at DESC",
                    (user_id,),
                )
            return [self._row_to_tenancy(row) for row in conn.fetchall()]

    def list_tenancies_for_property(
        self, property_id: int, user_id: int, active_only: bool = False
    ) -> list[Tenancy]:
        """List tenancies for a specific property (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            if active_only:
                conn.execute(
                    f"""SELECT * FROM tenancies
                       WHERE property_id = {p} AND user_id = {p} AND is_active = true
                       ORDER BY created_at DESC""",
                    (property_id, user_id),
                )
            else:
                conn.execute(
                    f"SELECT * FROM tenancies WHERE property_id = {p} AND user_id = {p} ORDER BY created_at DESC",
                    (property_id, user_id),
                )
            return [self._row_to_tenancy(row) for row in conn.fetchall()]

    def update_tenancy(self, tenancy: Tenancy, user_id: int) -> None:
        """Update an existing tenancy (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"""UPDATE tenancies SET
                    tenant_names = {p}, tenancy_start_date = {p}, fixed_term_end_date = {p},
                    rent_amount = {p}, rent_frequency = {p}, deposit_amount = {p},
                    deposit_protected = {p}, deposit_protection_date = {p}, deposit_scheme = {p},
                    prescribed_info_served = {p}, prescribed_info_date = {p},
                    how_to_rent_served = {p}, how_to_rent_date = {p},
                    is_active = {p}, document_path = {p}, notes = {p}
                WHERE id = {p} AND user_id = {p}""",
                (
                    tenancy.tenant_names,
                    tenancy.tenancy_start_date.isoformat() if tenancy.tenancy_start_date else None,
                    tenancy.fixed_term_end_date.isoformat() if tenancy.fixed_term_end_date else None,
                    str(tenancy.rent_amount),
                    tenancy.rent_frequency.value,
                    str(tenancy.deposit_amount),
                    tenancy.deposit_protected,
                    tenancy.deposit_protection_date.isoformat() if tenancy.deposit_protection_date else None,
                    tenancy.deposit_scheme,
                    tenancy.prescribed_info_served,
                    tenancy.prescribed_info_date.isoformat() if tenancy.prescribed_info_date else None,
                    tenancy.how_to_rent_served,
                    tenancy.how_to_rent_date.isoformat() if tenancy.how_to_rent_date else None,
                    tenancy.is_active,
                    tenancy.document_path,
                    tenancy.notes,
                    tenancy.id,
                    user_id,
                ),
            )

    def _row_to_tenancy(self, row) -> Tenancy:
        """Convert database row to Tenancy object."""
        return Tenancy(
            id=row["id"],
            property_id=row["property_id"],
            tenant_names=row["tenant_names"],
            tenancy_start_date=self._parse_date(row["tenancy_start_date"]),
            fixed_term_end_date=self._parse_date(row["fixed_term_end_date"]),
            rent_amount=Decimal(row["rent_amount"]) if row["rent_amount"] else Decimal("0"),
            rent_frequency=RentFrequency(row["rent_frequency"]),
            deposit_amount=Decimal(row["deposit_amount"]) if row["deposit_amount"] else Decimal("0"),
            deposit_protected=bool(row["deposit_protected"]),
            deposit_protection_date=self._parse_date(row["deposit_protection_date"]),
            deposit_scheme=row["deposit_scheme"] or "",
            prescribed_info_served=bool(row["prescribed_info_served"]),
            prescribed_info_date=self._parse_date(row["prescribed_info_date"]),
            how_to_rent_served=bool(row["how_to_rent_served"]),
            how_to_rent_date=self._parse_date(row["how_to_rent_date"]),
            is_active=bool(row["is_active"]),
            document_path=row["document_path"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # Certificate CRUD operations

    def create_certificate(self, cert: Certificate, user_id: int) -> int:
        """Create a new certificate and return its ID."""
        p = self._placeholder()
        params = (
            user_id,
            cert.property_id,
            cert.certificate_type.value,
            cert.issue_date.isoformat() if cert.issue_date else None,
            cert.expiry_date.isoformat() if cert.expiry_date else None,
            cert.document_path,
            cert.served_to_tenant_date.isoformat() if cert.served_to_tenant_date else None,
            cert.reference_number,
            cert.notes,
        )
        with self.connection() as conn:
            if self.use_postgres:
                conn.execute(
                    f"""INSERT INTO certificates (
                        user_id, property_id, certificate_type, issue_date, expiry_date,
                        document_path, served_to_tenant_date, reference_number, notes
                    ) VALUES ({self._placeholders(9)}) RETURNING id""",
                    params,
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO certificates (
                        user_id, property_id, certificate_type, issue_date, expiry_date,
                        document_path, served_to_tenant_date, reference_number, notes
                    ) VALUES ({self._placeholders(9)})""",
                    params,
                )
                return cursor.lastrowid

    def get_certificate(self, cert_id: int, user_id: int) -> Optional[Certificate]:
        """Get a certificate by ID (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM certificates WHERE id = {p} AND user_id = {p}",
                (cert_id, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_certificate(row)
            return None

    def list_certificates_for_property(self, property_id: int, user_id: int) -> list[Certificate]:
        """List all certificates for a property (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM certificates WHERE property_id = {p} AND user_id = {p} ORDER BY created_at DESC",
                (property_id, user_id),
            )
            return [self._row_to_certificate(row) for row in conn.fetchall()]

    def get_latest_certificate(
        self, property_id: int, cert_type: CertificateType, user_id: int
    ) -> Optional[Certificate]:
        """Get the most recent certificate of a type for a property (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"""SELECT * FROM certificates
                   WHERE property_id = {p} AND certificate_type = {p} AND user_id = {p}
                   ORDER BY issue_date DESC LIMIT 1""",
                (property_id, cert_type.value, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_certificate(row)
            return None

    def _row_to_certificate(self, row) -> Certificate:
        """Convert database row to Certificate object."""
        return Certificate(
            id=row["id"],
            property_id=row["property_id"],
            certificate_type=CertificateType(row["certificate_type"]),
            issue_date=self._parse_date(row["issue_date"]),
            expiry_date=self._parse_date(row["expiry_date"]),
            document_path=row["document_path"] or "",
            served_to_tenant_date=self._parse_date(row["served_to_tenant_date"]),
            reference_number=row["reference_number"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    def update_certificate(self, cert_id: int, user_id: int, issue_date=None, expiry_date=None, notes: str = None) -> bool:
        """Update certificate dates and/or notes (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            updates = []
            params = []

            if issue_date is not None:
                updates.append(f"issue_date = {p}")
                params.append(issue_date.isoformat() if issue_date else None)

            if expiry_date is not None:
                updates.append(f"expiry_date = {p}")
                params.append(expiry_date.isoformat() if expiry_date else None)

            if notes is not None:
                updates.append(f"notes = {p}")
                params.append(notes)

            if not updates:
                return False

            params.append(cert_id)
            params.append(user_id)
            conn.execute(
                f"UPDATE certificates SET {', '.join(updates)} WHERE id = {p} AND user_id = {p}",
                params,
            )
            return True

    # Compliance Events CRUD operations

    def create_event(self, event: ComplianceEvent, user_id: int) -> int:
        """Create a new compliance event and return its ID."""
        p = self._placeholder()
        params = (
            user_id,
            event.property_id,
            event.tenancy_id,
            event.event_type,
            event.event_name,
            event.due_date.isoformat() if event.due_date else None,
            event.completed_date.isoformat() if event.completed_date else None,
            event.status.value,
            event.priority.value,
            event.notes,
        )
        with self.connection() as conn:
            if self.use_postgres:
                conn.execute(
                    f"""INSERT INTO compliance_events (
                        user_id, property_id, tenancy_id, event_type, event_name,
                        due_date, completed_date, status, priority, notes
                    ) VALUES ({self._placeholders(10)}) RETURNING id""",
                    params,
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO compliance_events (
                        user_id, property_id, tenancy_id, event_type, event_name,
                        due_date, completed_date, status, priority, notes
                    ) VALUES ({self._placeholders(10)})""",
                    params,
                )
                return cursor.lastrowid

    def get_event(self, event_id: int, user_id: int) -> Optional[ComplianceEvent]:
        """Get an event by ID (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM compliance_events WHERE id = {p} AND user_id = {p}",
                (event_id, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_event(row)
            return None

    def list_events(
        self,
        user_id: int,
        property_id: Optional[int] = None,
        tenancy_id: Optional[int] = None,
        status: Optional[EventStatus] = None,
    ) -> list[ComplianceEvent]:
        """List compliance events for a user with optional filters."""
        p = self._placeholder()
        with self.connection() as conn:
            query = f"SELECT * FROM compliance_events WHERE user_id = {p}"
            params = [user_id]

            if property_id is not None:
                query += f" AND property_id = {p}"
                params.append(property_id)
            if tenancy_id is not None:
                query += f" AND tenancy_id = {p}"
                params.append(tenancy_id)
            if status is not None:
                query += f" AND status = {p}"
                params.append(status.value)

            query += " ORDER BY due_date ASC"
            conn.execute(query, params)
            return [self._row_to_event(row) for row in conn.fetchall()]

    def update_event_status(
        self, event_id: int, user_id: int, status: EventStatus, completed_date: Optional[date] = None
    ) -> None:
        """Update the status of a compliance event (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"""UPDATE compliance_events
                SET status = {p}, completed_date = {p}
                WHERE id = {p} AND user_id = {p}""",
                (
                    status.value,
                    completed_date.isoformat() if completed_date else None,
                    event_id,
                    user_id,
                ),
            )

    def delete_events_for_tenancy(self, tenancy_id: int, user_id: int) -> None:
        """Delete all compliance events for a tenancy (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM compliance_events WHERE tenancy_id = {p} AND user_id = {p}",
                (tenancy_id, user_id),
            )

    def delete_events_for_property(self, property_id: int, user_id: int) -> None:
        """Delete all compliance events for a property (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM compliance_events WHERE property_id = {p} AND user_id = {p}",
                (property_id, user_id),
            )

    def delete_tenancy(self, tenancy_id: int, user_id: int) -> None:
        """Delete a tenancy and its associated events (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM compliance_events WHERE tenancy_id = {p} AND user_id = {p}",
                (tenancy_id, user_id),
            )
            conn.execute(
                f"DELETE FROM served_documents WHERE tenancy_id = {p} AND user_id = {p}",
                (tenancy_id, user_id),
            )
            conn.execute(
                f"DELETE FROM tenancies WHERE id = {p} AND user_id = {p}",
                (tenancy_id, user_id),
            )

    def delete_certificates_for_property(self, property_id: int, user_id: int) -> None:
        """Delete all certificates for a property (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM certificates WHERE property_id = {p} AND user_id = {p}",
                (property_id, user_id),
            )

    def delete_property(self, property_id: int, user_id: int) -> None:
        """Delete a property and all associated data (only if it belongs to user)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM compliance_events WHERE property_id = {p} AND user_id = {p}",
                (property_id, user_id),
            )
            if self.use_postgres:
                conn.execute(
                    f"""DELETE FROM served_documents WHERE user_id = {p} AND tenancy_id IN
                       (SELECT id FROM tenancies WHERE property_id = {p} AND user_id = {p})""",
                    (user_id, property_id, user_id),
                )
            else:
                conn.execute(
                    f"""DELETE FROM served_documents WHERE user_id = {p} AND tenancy_id IN
                       (SELECT id FROM tenancies WHERE property_id = {p} AND user_id = {p})""",
                    (user_id, property_id, user_id),
                )
            conn.execute(
                f"DELETE FROM tenancies WHERE property_id = {p} AND user_id = {p}",
                (property_id, user_id),
            )
            conn.execute(
                f"DELETE FROM certificates WHERE property_id = {p} AND user_id = {p}",
                (property_id, user_id),
            )
            conn.execute(
                f"DELETE FROM properties WHERE id = {p} AND user_id = {p}",
                (property_id, user_id),
            )

    def _row_to_event(self, row) -> ComplianceEvent:
        """Convert database row to ComplianceEvent object."""
        return ComplianceEvent(
            id=row["id"],
            property_id=row["property_id"],
            tenancy_id=row["tenancy_id"],
            event_type=row["event_type"],
            event_name=row["event_name"],
            due_date=self._parse_date(row["due_date"]),
            completed_date=self._parse_date(row["completed_date"]),
            status=EventStatus(row["status"]),
            priority=EventPriority(row["priority"]),
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # Served Documents CRUD operations

    def mark_document_served(
        self, tenancy_id: int, document_type: RequiredDocument, served_date: date, user_id: int, proof_path: str = "", notes: str = ""
    ) -> int:
        """Mark a document as served to tenant. Returns the record ID."""
        p = self._placeholder()
        with self.connection() as conn:
            if self.use_postgres:
                # PostgreSQL upsert syntax
                conn.execute(
                    f"""INSERT INTO served_documents (user_id, tenancy_id, document_type, served_date, proof_path, notes)
                    VALUES ({self._placeholders(6)})
                    ON CONFLICT(tenancy_id, document_type) DO UPDATE SET
                        served_date = EXCLUDED.served_date,
                        proof_path = EXCLUDED.proof_path,
                        notes = EXCLUDED.notes
                    RETURNING id""",
                    (user_id, tenancy_id, document_type.value, served_date.isoformat(), proof_path, notes),
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO served_documents (user_id, tenancy_id, document_type, served_date, proof_path, notes)
                    VALUES ({self._placeholders(6)})
                    ON CONFLICT(tenancy_id, document_type) DO UPDATE SET
                        served_date = excluded.served_date,
                        proof_path = excluded.proof_path,
                        notes = excluded.notes""",
                    (user_id, tenancy_id, document_type.value, served_date.isoformat(), proof_path, notes),
                )
                return cursor.lastrowid

    def get_served_documents(self, tenancy_id: int, user_id: int) -> list[ServedDocument]:
        """Get all served documents for a tenancy (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM served_documents WHERE tenancy_id = {p} AND user_id = {p} ORDER BY served_date",
                (tenancy_id, user_id),
            )
            return [self._row_to_served_document(row) for row in conn.fetchall()]

    def get_served_document(self, tenancy_id: int, document_type: RequiredDocument, user_id: int) -> Optional[ServedDocument]:
        """Get a specific served document record (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"SELECT * FROM served_documents WHERE tenancy_id = {p} AND document_type = {p} AND user_id = {p}",
                (tenancy_id, document_type.value, user_id),
            )
            row = conn.fetchone()
            if row:
                return self._row_to_served_document(row)
            return None

    def delete_served_document(self, tenancy_id: int, document_type: RequiredDocument, user_id: int) -> None:
        """Delete a served document record (only for user's data)."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM served_documents WHERE tenancy_id = {p} AND document_type = {p} AND user_id = {p}",
                (tenancy_id, document_type.value, user_id),
            )

    def _row_to_served_document(self, row) -> ServedDocument:
        """Convert database row to ServedDocument object."""
        return ServedDocument(
            id=row["id"],
            tenancy_id=row["tenancy_id"],
            document_type=RequiredDocument(row["document_type"]),
            served_date=self._parse_date(row["served_date"]),
            proof_path=row["proof_path"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # User operations
    def create_user(self, user: User) -> int:
        """Create a new user and return their ID."""
        p = self._placeholder()
        with self.connection() as conn:
            if self.use_postgres:
                conn.execute(
                    f"""INSERT INTO users (email, password_hash, name, is_active)
                       VALUES ({self._placeholders(4)}) RETURNING id""",
                    (user.email, user.password_hash, user.name, user.is_active),
                )
                return conn.fetchone()["id"]
            else:
                cursor = conn.execute(
                    f"""INSERT INTO users (email, password_hash, name, is_active)
                       VALUES ({self._placeholders(4)})""",
                    (user.email, user.password_hash, user.name, user.is_active),
                )
                return cursor.lastrowid

    def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(f"SELECT * FROM users WHERE id = {p}", (user_id,))
            row = conn.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email address."""
        p = self._placeholder()
        with self.connection() as conn:
            conn.execute(f"SELECT * FROM users WHERE email = {p}", (email,))
            row = conn.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None

    def update_user(self, user_id: int, name: str = None, password_hash: str = None) -> None:
        """Update user details."""
        p = self._placeholder()
        with self.connection() as conn:
            if name is not None:
                conn.execute(f"UPDATE users SET name = {p} WHERE id = {p}", (name, user_id))
            if password_hash is not None:
                conn.execute(f"UPDATE users SET password_hash = {p} WHERE id = {p}", (password_hash, user_id))


class _SqliteConnection:
    """Wrapper to provide consistent interface for SQLite."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, query: str, params: tuple = None):
        """Execute a query."""
        if params:
            self._cursor = self._conn.execute(query, params)
        else:
            self._cursor = self._conn.execute(query)
        return self._cursor

    def executescript(self, script: str):
        """Execute a SQL script."""
        return self._conn.executescript(script)

    def fetchone(self):
        """Fetch one row."""
        return self._cursor.fetchone() if self._cursor else None

    def fetchall(self):
        """Fetch all rows."""
        return self._cursor.fetchall() if self._cursor else []


class _PostgresConnection:
    """Wrapper to make psycopg2 cursor work like sqlite3 connection."""

    def __init__(self, conn, cursor):
        self._conn = conn
        self._cursor = cursor

    def execute(self, query: str, params: tuple = None):
        """Execute a query."""
        if params:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
        return self._cursor

    def fetchone(self):
        """Fetch one row."""
        return self._cursor.fetchone()

    def fetchall(self):
        """Fetch all rows."""
        return self._cursor.fetchall()
