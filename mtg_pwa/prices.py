from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


EUR_FIELDS_BY_FINISH = {
    "nonfoil": "eur",
    "foil": "eur_foil",
    "etched": "eur_etched",
}


@dataclass(frozen=True)
class PricePoint:
    currency: str
    finish: str
    price: Decimal
    source: str
    is_fallback: bool = False


def parse_price(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def extract_eur_prices(card: dict[str, Any]) -> dict[str, Decimal]:
    prices = card.get("prices") or {}
    extracted: dict[str, Decimal] = {}

    for finish, field_name in EUR_FIELDS_BY_FINISH.items():
        parsed = parse_price(prices.get(field_name))
        if parsed is not None:
            extracted[finish] = parsed

    return extracted


def current_eur_price(card: dict[str, Any], finish: str) -> PricePoint | None:
    field_name = EUR_FIELDS_BY_FINISH.get(finish)
    if not field_name:
        return None

    parsed = parse_price((card.get("prices") or {}).get(field_name))
    if parsed is None:
        return None

    return PricePoint(
        currency="EUR",
        finish=finish,
        price=parsed,
        source="scryfall-cardmarket",
        is_fallback=False,
    )


def decimal_to_json(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
