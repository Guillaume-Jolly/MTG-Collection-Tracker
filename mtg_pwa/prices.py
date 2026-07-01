from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


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


VALID_FINISHES = {"nonfoil", "foil", "etched"}


FINISH_ORDER = ("nonfoil", "foil", "etched")


def available_finishes_for_card(
    card: dict[str, Any],
    *,
    extra_finishes: Iterable[str] | None = None,
) -> list[str]:
    seen: set[str] = set()
    finishes: list[str] = []

    def add(finish: str) -> None:
        if finish not in VALID_FINISHES or finish in seen:
            return
        seen.add(finish)
        finishes.append(finish)

    for finish in card.get("finishes") or []:
        add(finish)
    for finish in extract_eur_prices(card):
        add(finish)
    for finish in extra_finishes or ():
        add(finish)

    if not finishes:
        return ["nonfoil"]
    return sorted(finishes, key=lambda finish: FINISH_ORDER.index(finish) if finish in FINISH_ORDER else len(FINISH_ORDER))


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


CHART_PRICE_SOURCES: dict[str, dict[str, str]] = {
    "cardmarket": {
        "source": "cardmarket-guide",
        "currency": "EUR",
        "label": "Cardmarket",
    },
    "cardkingdom": {
        "source": "mtgjson-cardkingdom",
        "currency": "USD",
        "label": "Card Kingdom",
    },
    "manapool": {
        "source": "mtgjson-manapool",
        "currency": "USD",
        "label": "ManaPool",
    },
    "tcgplayer": {
        "source": "mtgjson-tcgplayer",
        "currency": "USD",
        "label": "TCGPlayer",
    },
}


def chart_price_source(key: str) -> dict[str, str]:
    return CHART_PRICE_SOURCES.get(key) or CHART_PRICE_SOURCES["cardmarket"]


def chart_price_source_keys() -> list[str]:
    return list(CHART_PRICE_SOURCES)
