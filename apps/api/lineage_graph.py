"""
Lineage Graph — OpenLineage/Marquez inspired, lightweight.

Concepts:
- OpenLineage: Dataset/Job/Run with lineage events (inputs/outputs)
- Marquez: lineage storage, APIs for upstream/downstream, graph visualization
- DataGuard native: LineageEdge table (source_dataset/column -> target_dataset/column via job/run)

Provides:
- CRUD for edges
- Graph traversal (BFS upstream/downstream with depth, cycle protection)
- Seed from lineage_config.json (demo) into DB on first use
- Fallback to config for demo if DB empty
"""
from typing import List, Dict, Any, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_
import models

def _ensure_seeded(db: Session):
    """Seed DB from lineage_config.json if edges table empty."""
    if db.query(models.LineageEdge).count() > 0:
        return
    try:
        from lineage import DEFAULT_LINEAGE_MAP
        # Also try to load from file if exists
        from pathlib import Path
        import json
        config_path = Path(__file__).parent / "lineage_config.json"
        cfg = DEFAULT_LINEAGE_MAP
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = DEFAULT_LINEAGE_MAP
        for key, assets in cfg.items():
            # key is "dataset.column"
            if "." not in key:
                continue
            ds, col = key.split(".", 1)
            for asset in assets:
                edge = models.LineageEdge(
                    source_dataset=ds,
                    source_column=col,
                    target_dataset=asset["name"],
                    target_column=None,
                    target_type=asset.get("asset_type", "SQL_MODEL"),
                    job_name=None,
                    relationship=asset.get("relationship", "DIRECT"),
                    description=f"Seeded from lineage_config.json: {key} -> {asset['name']}",
                    is_active=True,
                )
                db.add(edge)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except:
            pass

def normalize_dataset(name: str) -> str:
    return name.lower().replace(".csv", "").replace(".json", "").strip()

def create_edge(db: Session, data: Dict[str, Any]) -> models.LineageEdge:
    # Validate
    if not data.get("source_dataset") or not data.get("target_dataset"):
        raise ValueError("source_dataset and target_dataset required")
    edge = models.LineageEdge(
        source_dataset=normalize_dataset(data["source_dataset"]),
        source_column=data.get("source_column"),
        target_dataset=data["target_dataset"].strip(),
        target_column=data.get("target_column"),
        target_type=data.get("target_type", "DATASET"),
        job_name=data.get("job_name"),
        run_id=data.get("run_id"),
        relationship=data.get("relationship", "DIRECT"),
        description=data.get("description"),
        is_active=data.get("is_active", True),
        created_by=data.get("created_by", "system"),
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge

def list_edges(
    db: Session,
    source_dataset: Optional[str] = None,
    source_column: Optional[str] = None,
    target_dataset: Optional[str] = None,
    job_name: Optional[str] = None,
    active_only: bool = True,
) -> List[models.LineageEdge]:
    _ensure_seeded(db)
    q = db.query(models.LineageEdge)
    if active_only:
        q = q.filter(models.LineageEdge.is_active == True)
    if source_dataset:
        q = q.filter(models.LineageEdge.source_dataset == normalize_dataset(source_dataset))
    if source_column is not None:
        q = q.filter(models.LineageEdge.source_column == source_column)
    if target_dataset:
        q = q.filter(models.LineageEdge.target_dataset == target_dataset)
    if job_name:
        q = q.filter(models.LineageEdge.job_name == job_name)
    return q.order_by(models.LineageEdge.created_at.desc()).all()

def get_direct_downstream(
    db: Session,
    dataset: str,
    column: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Direct downstream (1 hop) for dataset.column or dataset-level if column None."""
    _ensure_seeded(db)
    ds_norm = normalize_dataset(dataset)
    q = db.query(models.LineageEdge).filter(
        models.LineageEdge.source_dataset == ds_norm,
        models.LineageEdge.is_active == True
    )
    if column is not None:
        # Column-level: match exact column or dataset-level edges (source_column is None means dataset-level)
        # For column query, return edges where source_column == column OR source_column is None (dataset-level)
        # To keep precise, we return both but prioritize column-level
        all_edges = q.all()
        # Filter to column-specific
        col_edges = [e for e in all_edges if e.source_column is None or e.source_column.lower() == column.lower()]
        # If column-specific exists, return those, else return dataset-level as fallback
        column_specific = [e for e in col_edges if e.source_column and e.source_column.lower() == column.lower()]
        edges = column_specific if column_specific else col_edges
    else:
        edges = q.all()
    result = []
    for e in edges:
        result.append({
            "id": e.id,
            "source_dataset": e.source_dataset,
            "source_column": e.source_column,
            "target_dataset": e.target_dataset,
            "target_column": e.target_column,
            "target_type": e.target_type,
            "job_name": e.job_name,
            "relationship": e.relationship,
            "description": e.description,
        })
    return result

def get_direct_upstream(
    db: Session,
    dataset: str,
    column: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Direct upstream (1 hop) where dataset is target."""
    _ensure_seeded(db)
    # Target could be dataset name or column? For now target_dataset is the asset name
    # For upstream, we look for edges where target_dataset == dataset
    # This supports traversing back from downstream assets
    q = db.query(models.LineageEdge).filter(
        models.LineageEdge.target_dataset == dataset,
        models.LineageEdge.is_active == True
    )
    if column is not None:
        q = q.filter(
            or_(
                models.LineageEdge.target_column == column,
                models.LineageEdge.target_column == None
            )
        )
    edges = q.all()
    result = []
    for e in edges:
        result.append({
            "id": e.id,
            "source_dataset": e.source_dataset,
            "source_column": e.source_column,
            "target_dataset": e.target_dataset,
            "target_column": e.target_column,
            "target_type": e.target_type,
            "job_name": e.job_name,
            "relationship": e.relationship,
        })
    return result

def traverse_graph(
    db: Session,
    start_dataset: str,
    start_column: Optional[str] = None,
    direction: str = "downstream",
    max_depth: int = 3,
) -> Dict[str, Any]:
    """
    BFS traversal for lineage graph.
    Returns nodes and edges with depth.
    Direction: downstream (follow source->target) or upstream (target->source).
    """
    _ensure_seeded(db)
    start_ds = normalize_dataset(start_dataset)
    visited: Set[Tuple[str, Optional[str]]] = set()
    queue: List[Tuple[str, Optional[str], int]] = [(start_ds, start_column, 0)]
    visited.add((start_ds, start_column.lower() if start_column else None))
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_edges: Set[int] = set()

    # Add start node
    nodes.append({"dataset": start_ds, "column": start_column, "depth": 0, "type": "START"})

    while queue:
        cur_ds, cur_col, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        if direction == "downstream":
            next_edges = get_direct_downstream(db, cur_ds, cur_col)
            # For dataset-level traversal, cur_col may be None; need to handle
            # get_direct_downstream already handles column filtering
        else:
            next_edges = get_direct_upstream(db, cur_ds, cur_col)

        for e in next_edges:
            if e["id"] in seen_edges:
                continue
            seen_edges.add(e["id"])
            edges.append({**e, "depth": depth + 1})
            # Determine next node to traverse
            if direction == "downstream":
                next_ds = e["target_dataset"]
                next_col = e["target_column"]
                # Normalize for visited check
                next_key = (next_ds.lower(), next_col.lower() if next_col else None)
                if next_key not in visited:
                    visited.add(next_key)
                    queue.append((next_ds, next_col, depth + 1))
                    nodes.append({"dataset": next_ds, "column": next_col, "depth": depth + 1, "type": e["target_type"], "via_job": e["job_name"]})
            else:
                next_ds = e["source_dataset"]
                next_col = e["source_column"]
                next_key = (next_ds.lower(), next_col.lower() if next_col else None)
                if next_key not in visited:
                    visited.add(next_key)
                    queue.append((next_ds, next_col, depth + 1))
                    nodes.append({"dataset": next_ds, "column": next_col, "depth": depth + 1, "type": "SOURCE"})

    return {
        "start": {"dataset": start_ds, "column": start_column, "direction": direction, "max_depth": max_depth},
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }

def get_lineage_graph(
    db: Session,
    dataset: str,
    column: Optional[str] = None,
    depth: int = 3,
) -> Dict[str, Any]:
    """Return both upstream and downstream for a node."""
    downstream = traverse_graph(db, dataset, column, direction="downstream", max_depth=depth)
    upstream = traverse_graph(db, dataset, column, direction="upstream", max_depth=depth)
    return {
        "dataset": dataset,
        "column": column,
        "depth": depth,
        "downstream": downstream,
        "upstream": upstream,
    }
