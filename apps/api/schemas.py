from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict

# --- Dataset Schemas ---
class DatasetBase(BaseModel):
    name: str
    filename: str
    file_type: str

class DatasetResponse(DatasetBase):
    id: int
    row_count: int
    column_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DatasetUploadResponse(BaseModel):
    dataset_id: int
    filename: str
    row_count: int
    column_count: int

# --- Schema & Column Schemas ---
class SchemaColumnResponse(BaseModel):
    id: int
    column_name: str
    data_type: str
    nullable: bool
    unique_count: int
    null_count: int
    sample_values: List[Any] = []
    # Watchtower-adapted extended profiling
    null_rate: float = 0.0
    unique_ratio: float = 0.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    p05: Optional[float] = None
    p95: Optional[float] = None
    outlier_count: Optional[int] = 0
    outlier_rate: Optional[float] = 0.0
    top_values: List[Any] = []
    model_config = ConfigDict(from_attributes=True)

class SchemaResponse(BaseModel):
    id: int
    dataset_id: int
    fingerprint: str
    created_at: datetime
    columns: List[SchemaColumnResponse] = []
    model_config = ConfigDict(from_attributes=True)

from pydantic import BaseModel, ConfigDict, Field

# --- Issue Schemas ---
class IssueResponse(BaseModel):
    id: int
    scan_id: int
    issue_type: str
    severity: str
    column_name: Optional[str] = None
    description: str
    issue_metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="issue_metadata", serialization_alias="metadata")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

# --- AI Analysis Schemas ---
class AIAnalysisRequest(BaseModel):
    pass

class AIAnalysisResponse(BaseModel):
    id: Optional[int] = None
    scan_id: int
    summary: str
    severity: str
    root_cause: str
    impact: str
    affected_assets: List[str] = []
    recommended_action: str
    confidence: float
    requires_human_approval: bool = True
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# --- Remediation Schemas ---
class RemediationActionRequest(BaseModel):
    decision_by: Optional[str] = "analyst@dataguard.internal"
    notes: Optional[str] = None

class RemediationResponse(BaseModel):
    id: int
    scan_id: int
    suggestion: str
    status: str
    decision_by: Optional[str] = None
    decision_at: Optional[datetime] = None
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# --- Scan Schemas ---
class ScanResponse(BaseModel):
    id: int
    dataset_id: int
    status: str
    healthy_count: int
    warning_count: int
    critical_count: int
    started_at: datetime
    completed_at: datetime
    issues: List[IssueResponse] = []
    ai_analyses: List[AIAnalysisResponse] = []
    remediations: List[RemediationResponse] = []
    model_config = ConfigDict(from_attributes=True)

# --- Lineage & Impact Schemas ---
class DownstreamAsset(BaseModel):
    name: str
    asset_type: str # SQL_MODEL, DASHBOARD
    relationship: str

class ColumnImpactResponse(BaseModel):
    column_name: str
    dataset_name: str
    affected_assets: List[DownstreamAsset] = []

# --- Health Schema ---
class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime
