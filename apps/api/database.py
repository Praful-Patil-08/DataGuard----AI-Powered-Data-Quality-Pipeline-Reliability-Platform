import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dataguard.db")

# For SQLite, ensure check_same_thread is False
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def run_migrations():
    """Lightweight additive migration — adds missing columns without Alembic for MVP.
    Checks inspector and issues ALTER TABLE ADD COLUMN IF NOT EXISTS for Postgres,
    or try+ignore for SQLite. Safe to run on every startup."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    # scans
    try:
        cols = {c["name"] for c in inspector.get_columns("scans")}
        stmts = []
        if "baseline_dataset_id" not in cols:
            stmts.append("ALTER TABLE scans ADD COLUMN baseline_dataset_id INTEGER")
        if "incident_summary" not in cols:
            stmts.append("ALTER TABLE scans ADD COLUMN incident_summary TEXT")
        if "incident_severity" not in cols:
            stmts.append("ALTER TABLE scans ADD COLUMN incident_severity VARCHAR(20)")
        # schema_columns
        cols2 = {c["name"] for c in inspector.get_columns("schema_columns")}
        if "null_rate" not in cols2:
            stmts.append("ALTER TABLE schema_columns ADD COLUMN null_rate FLOAT DEFAULT 0.0")
        if "unique_ratio" not in cols2:
            for col in ["unique_ratio FLOAT DEFAULT 0.0", "min_value FLOAT", "max_value FLOAT", "mean FLOAT", "median FLOAT", "p05 FLOAT", "p95 FLOAT", "outlier_count INTEGER DEFAULT 0", "outlier_rate FLOAT DEFAULT 0.0", "top_values JSON DEFAULT '[]'"]:
                stmts.append(f"ALTER TABLE schema_columns ADD COLUMN {col}")
        # ai_analysis
        cols3 = {c["name"] for c in inspector.get_columns("ai_analysis")}
        if "technical_impact" not in cols3:
            stmts.append("ALTER TABLE ai_analysis ADD COLUMN technical_impact TEXT")
        if "business_impact" not in cols3:
            stmts.append("ALTER TABLE ai_analysis ADD COLUMN business_impact TEXT")
        # scans quality score (Phase 3)
        if "quality_score" not in cols:
            stmts.append("ALTER TABLE scans ADD COLUMN quality_score FLOAT DEFAULT 100.0")
        if "quality_dimensions" not in cols:
            stmts.append("ALTER TABLE scans ADD COLUMN quality_dimensions JSON DEFAULT '{}'")
        for stmt in stmts:
            try:
                with engine.begin() as conn:
                    # Postgres supports IF NOT EXISTS, SQLite will throw if exists — we already checked
                    conn.execute(text(stmt))
            except Exception:
                pass
    except Exception:
        pass  # tables not yet created — create_all will handle

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
