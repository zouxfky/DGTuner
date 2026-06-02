from difflib import SequenceMatcher
import math
import re


def sql_type(statement):
    upper = statement.strip().upper()
    if "SELECT" in upper and "VECTOR(" in upper:
        return "PRE_ANN_SELECT" if "/*+ VECTOR_PRE */" in upper else "ANN_SELECT"
    match = re.match(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)", statement, re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


def target_table(statement):
    patterns = [
        r"\bFROM\s+vector\s*\(\s*([a-zA-Z0-9_]+)",
        r"\bFROM\s+([a-zA-Z0-9_]+)",
        r"\bINTO\s+([a-zA-Z0-9_]+)",
        r"\bUPDATE\s+([a-zA-Z0-9_]+)",
        r"\bTABLE\s+([a-zA-Z0-9_]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, statement, re.IGNORECASE)
        if match:
            return match.group(1)
    return "UNKNOWN"


def selected_attributes(statement):
    match = re.search(r"\bselect\s+(.*?)\s+from\b", statement, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    return sorted(attr.strip().upper() for attr in match.group(1).split(","))


def clause_text(statement, start_keywords, stop_keywords):
    start = "|".join(start_keywords)
    stop = "|".join(stop_keywords)
    pattern = rf"\b({start})\b\s+(.*?)(?=\s*\b({stop})\b|$)"
    match = re.search(pattern, statement, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", match.group(2)).strip().upper() if match else ""


def sql_features(statement):
    return {
        "type": sql_type(statement),
        "table": target_table(statement),
        "attrs": selected_attributes(statement),
        "where": clause_text(statement, ["WHERE"], ["GROUP BY", "ORDER BY", "LIMIT"]),
        "group_by": clause_text(statement, ["GROUP BY"], ["ORDER BY", "LIMIT"]),
        "order_by": clause_text(statement, ["ORDER BY"], ["LIMIT"]),
    }


def similar_sql(left, right, threshold):
    if left["type"] != right["type"] or left["table"] != right["table"]:
        return False
    if left["type"] in {"ANN_SELECT", "PRE_ANN_SELECT"} and left["attrs"] != right["attrs"]:
        return False
    for field in ("where", "group_by", "order_by"):
        if left[field] or right[field]:
            if SequenceMatcher(None, left[field], right[field]).ratio() < threshold:
                return False
    return True


def group_similar_sql(statements, threshold):
    items = [
        {"sql_id": index + 1, "sql": statement, "features": sql_features(statement)}
        for index, statement in enumerate(statements)
    ]
    groups = []
    used = set()
    for index, item in enumerate(items):
        if index in used:
            continue
        group = [item]
        used.add(index)
        for other_index in range(index + 1, len(items)):
            if other_index not in used and similar_sql(item["features"], items[other_index]["features"], threshold):
                group.append(items[other_index])
                used.add(other_index)
        groups.append(group)
    return groups


def dissimilarity_score(item, group):
    if len(group) <= 1:
        return 1.0
    return sum(
        1.0 - SequenceMatcher(None, item["features"]["where"], other["features"]["where"]).ratio()
        for other in group
        if other is not item
    )


def select_initial_sql(statements, similarity_threshold, percent):
    groups = group_similar_sql(statements, similarity_threshold)
    selected = []
    for group in groups:
        keep_count = max(1, math.ceil(len(group) * percent / 100.0))
        ranked = sorted(group, key=lambda item: dissimilarity_score(item, group), reverse=True)
        selected.extend(ranked[:keep_count])
    return sorted(selected, key=lambda item: item["sql_id"]), groups
