"""
Excel import for catalog and internal-items spreadsheets.

Uses pandas (openpyxl engine) with tolerant header matching, since real
government/supplier files rarely have perfectly consistent column names.
"""
from typing import Dict, List, Optional

import pandas as pd

from app.services.normalize import build_normalized_text, clean_code, to_float


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
        if name is None or str(name).strip() == "" or str(name).lower() == "nan":
            continue  # skip blank rows

        code = clean_code(get("code"))
        brand = get("brand")
        model = get("model")
        description = get("description")
        technical_specs = get("technical_specs")
        price = to_float(get("price"))

        normalized_text = build_normalized_text(name, brand, model, description, technical_specs)

        rows.append({
            "code": code,
            "name": str(name).strip(),
            "brand": str(brand).strip() if brand is not None and str(brand).lower() != "nan" else None,
            "model": str(model).strip() if model is not None and str(model).lower() != "nan" else None,
            "description": str(description).strip() if description is not None and str(description).lower() != "nan" else None,
            "technical_specs": str(technical_specs).strip() if technical_specs is not None and str(technical_specs).lower() != "nan" else None,
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
        if item_name is None or str(item_name).strip() == "" or str(item_name).lower() == "nan":
            continue

        item_code = clean_code(get("item_code"))
        description = get("description")
        quantity = to_float(get("quantity"))

        normalized_text = build_normalized_text(item_name, description)

        rows.append({
            "item_code": item_code,
            "item_name": str(item_name).strip(),
            "description": str(description).strip() if description is not None and str(description).lower() != "nan" else None,
            "quantity": quantity,
            "normalized_text": normalized_text,
        })
    return rows
