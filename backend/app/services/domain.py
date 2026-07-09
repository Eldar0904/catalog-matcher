"""Domain hints to block obviously wrong cross-domain matches."""
from typing import List, Set

from app.models.db_models import CatalogProduct

# Item text contains any of these → treat as medical/healthcare supply.
MEDICAL_KEYWORDS: List[str] = [
    "шприц", "грелк", "жгут", "катетер", "бинт", "шина", "стетоскоп",
    "тонометр", "небулайзер", "ингалятор", "физиотерап", "дарсонвал",
    "гальваниза", "магнитотерап", "ультразвук", "электрофорез", "аппарат для",
    "медицин", "кислородн", "перчатк мед", "маска мед", "халат",
]

# Catalog sections that should not match medical items (sports / gym inventory).
SPORTS_GYM_SECTIONS: Set[str] = {
    "522-101-1000",  # balls, bars, gym gear under «technical teaching aids»
    "521-402-0100",  # physical therapy / gym hall
    "521-301-0300",  # math cabinet — physics demo kits, not medical
}


def item_text(item_name: str = "", description: str = "") -> str:
    return f"{item_name or ''} {description or ''}".lower()


def is_medical_item(item_name: str = "", description: str = "") -> bool:
    text = item_text(item_name, description)
    return any(kw in text for kw in MEDICAL_KEYWORDS)


def blocked_product_ids_for_item(
    item_name: str,
    description: str,
    products: List[CatalogProduct],
) -> Set[int]:
    """Product ids that must not be suggested for this item."""
    if not is_medical_item(item_name, description):
        return set()
    return {
        p.id for p in products
        if p.category_code in SPORTS_GYM_SECTIONS
    }
