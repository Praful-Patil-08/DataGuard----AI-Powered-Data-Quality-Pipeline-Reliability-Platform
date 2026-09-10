from typing import List, Dict, Any

def detect_schema_drift(
    baseline_columns: List[Dict[str, Any]],
    current_columns: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Compares baseline schema columns against current schema columns deterministically.
    Returns a list of structured issue dictionaries.
    """
    issues = []

    baseline_map = {col["column_name"]: col for col in baseline_columns}
    current_map = {col["column_name"]: col for col in current_columns}

    # 1. Detect COLUMN_REMOVED
    for col_name, base_col in baseline_map.items():
        if col_name not in current_map:
            # Missing column is CRITICAL if it was non-nullable or standard identifier/value
            severity = "CRITICAL"
            issues.append({
                "issue_type": "COLUMN_REMOVED",
                "severity": severity,
                "column_name": col_name,
                "description": f"Column '{col_name}' was present in baseline schema ({base_col['data_type']}) but removed in current dataset.",
                "metadata": {
                    "previous_type": base_col["data_type"],
                    "previous_nullable": base_col["nullable"],
                }
            })

    # 2. Detect COLUMN_ADDED
    for col_name, curr_col in current_map.items():
        if col_name not in baseline_map:
            issues.append({
                "issue_type": "COLUMN_ADDED",
                "severity": "WARNING",
                "column_name": col_name,
                "description": f"New column '{col_name}' ({curr_col['data_type']}) added that was not present in baseline schema.",
                "metadata": {
                    "current_type": curr_col["data_type"],
                    "current_nullable": curr_col["nullable"],
                }
            })

    # 3. Detect TYPE_CHANGED and NULLABILITY_CHANGED
    for col_name in baseline_map.keys() & current_map.keys():
        base_col = baseline_map[col_name]
        curr_col = current_map[col_name]

        # Datatype change
        if base_col["data_type"] != curr_col["data_type"]:
            # Type change from numeric/date to string is breaking -> CRITICAL
            breaking_transitions = {
                ("FLOAT", "STRING"),
                ("INTEGER", "STRING"),
                ("DATE", "STRING"),
                ("INTEGER", "BOOLEAN"),
                ("FLOAT", "INTEGER"),
            }
            is_breaking = (base_col["data_type"], curr_col["data_type"]) in breaking_transitions or curr_col["data_type"] == "STRING"
            severity = "CRITICAL" if is_breaking else "WARNING"

            issues.append({
                "issue_type": "TYPE_CHANGED",
                "severity": severity,
                "column_name": col_name,
                "description": f"Column '{col_name}' changed type from {base_col['data_type']} to {curr_col['data_type']}.",
                "metadata": {
                    "previous_type": base_col["data_type"],
                    "current_type": curr_col["data_type"],
                }
            })

        # Nullability change
        if not base_col["nullable"] and curr_col["nullable"]:
            issues.append({
                "issue_type": "NULLABILITY_CHANGED",
                "severity": "WARNING",
                "column_name": col_name,
                "description": f"Column '{col_name}' was previously non-nullable, but current dataset contains {curr_col['null_count']} null values.",
                "metadata": {
                    "previous_nullable": False,
                    "current_nullable": True,
                    "null_count": curr_col["null_count"],
                }
            })

    return issues
