"""
Excel import for catalog and internal-items spreadsheets.

Uses pandas (openpyxl engine) with tolerant header matching, since real
government/supplier files rarely have perfectly consistent column names.
"""
from typing import Dict, List, Optional

import pandas as pd

from app.services.normalize import build_normalized_text, clean_code, to_float, is_missing


# Maps canonical field name -> list of acceptable header aliases (lowercased).
# Includes English (government/standard) and Russian (common local supplier
# exports) variants. Add more aliases here as new source files show up —
# no other code needs to change.
CATALOG_HEADER_ALIASES: Dict[str, List[str]] = {
    "code": [
        "government code", "gov code", "code", "government_code",
        "код", "код тру", "гос код",
    ],
    "name": [
        "product name", "name", "product_name",
        "наименование товара", "наименование", "название", "название товара",
    ],
    "brand": ["brand", "manufacturer", "бренд", "производитель"],
    "model": ["model", "model number", "model_number", "модель"],
    "description": ["description", "desc", "описание"],
    "technical_specs": [
        "technical specifications", "technical specs", "specs", "specifications",
        "технические характеристики", "технические спецификации", "характеристики",
    ],
    "price": [
        "price", "unit price", "cost",
        "цена", "цена с ндс, в тенге", "цена с ндс", "цена, тенге", "стоимость",
    ],
}

ITEM_HEADER_ALIASES: Dict[str, List[str]] = {
    "item_code": ["item code", "item_code", "code", "код"],
    "item_name": [
        "item name", "item_name", "name",
        "наименование товара", "наименование", "название",
    ],
    "description": ["description", "desc", "описание"],
    "quantity": ["quantity", "qty", "количество", "кол-во"],
}


def _map_headers(columns: List[str], aliases: Dict[str, List[str]]) -> Dict[str, str]:
    """Return {canonical_field: actual_column_name} for whatever matches."""
    lower_map = {str(c).strip().lower(): c for c in columns}
    resolved = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            if candidate in lower_map:
                resolved[field] = lower_map[candidate]
                break
    return resolved


def read_catalog_excel(file_path: str) -> List[dict]:
    """Parse a government/supplier catalog Excel file into normalized dicts."""
    df = pd.read_excel(file_path, engine="openpyxl")
    df = df.dropna(how="all")
    header_map = _map_headers(list(df.columns), CATALOG_HEADER_ALIASES)

    missing = [f for f in ("name",) if f not in header_map]
    if missing:
        raise ValueError(
            f"Catalog file is missing required column(s): {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    rows = []
    for _, row in df.iterrows():
        def get(field: str) -> Optional[str]:
            col = header_map.get(field)
            return row[col] if col is not None and col in row else None

        name = get("name")
        if is_missing(name):
            continue  # skip blank rows

        code = clean_code(get("code"))
        brand = get("brand")
        model = get("model")
        description = get("description")
        technical_specs = get("technical_specs")
        price = to_float(get("price"))

        normalized_text = build_normalized_text(code, name, brand, model, description, technical_specs)

        def _str_field(val) -> Optional[str]:
            if is_missing(val):
                return None
            return str(val).strip()

        rows.append({
            "code": code,
            "name": _str_field(name),
            "brand": _str_field(brand),
            "model": _str_field(model),
            "description": _str_field(description),
            "technical_specs": _str_field(technical_specs),
            "price": price,
            "normalized_text": normalized_text,
        })
    return rows


def read_items_excel(file_path: str) -> List[dict]:
    """Parse Our_Items.xlsx into normalized dicts."""
    df = pd.read_excel(file_path, engine="openpyxl")
    df = df.dropna(how="all")
    header_map = _map_headers(list(df.columns), ITEM_HEADER_ALIASES)

    missing = [f for f in ("item_name",) if f not in header_map]
    if missing:
        raise ValueError(
            f"Items file is missing required column(s): {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    rows = []
    for _, row in df.iterrows():
        def get(field: str) -> Optional[str]:
            col = header_map.get(field)
            return row[col] if col is not None and col in row else None

        item_name = get("item_name")
        if is_missing(item_name):
            continue

        item_code = clean_code(get("item_code"))
        description = get("description")
        quantity = to_float(get("quantity"))

        normalized_text = build_normalized_text(item_code, item_name, description)

        rows.append({
            "item_code": item_code,
            "item_name": str(item_name).strip(),
            "description": None if is_missing(description) else str(description).strip(),
            "quantity": quantity,
            "normalized_text": normalized_text,
        })
    return rows
