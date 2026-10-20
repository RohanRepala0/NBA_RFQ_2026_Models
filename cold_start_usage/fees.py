"""Venue taker fees, per order, rounded the way each venue rounds them.

All three venues charge rate x C x P x (1 - P) for C contracts at price P
(dollars). What differs is the rate and the rounding, and for orders of a few
contracts the rounding matters: one Kalshi contract at 50c pays 2c, not 1.75c.

- kalshi: rounded up to the next cent per order (KXNBAPTS fee_type "quadratic",
  fee_multiplier 1; resting orders pay no maker fee on this series).
- polymarket_us: feeCoefficient 0.0695, rounded to the cent, half to even.
- polymarket_intl: feeSchedule rate 0.05 (sports_fees_v3), 5 decimals. Reference only.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal

from . import config

_QUANTUM = {"up_cent": (Decimal("0.01"), ROUND_CEILING),
            "half_even_cent": (Decimal("0.01"), ROUND_HALF_EVEN),
            "5dp": (Decimal("0.00001"), ROUND_HALF_EVEN)}


def fee_total(venue: str, contracts: float, price: float, maker: bool = False,
              rate: float | None = None) -> float:
    """Fee in dollars for one order of `contracts` at `price`. Unknown venues raise."""
    spec = config.VENUE_FEES[venue]
    r = rate if rate is not None else (spec["maker_rate"] if maker else spec["rate"])
    if contracts <= 0 or not 0 < price < 1 or r == 0:
        return 0.0
    p = Decimal(str(price))
    exact = Decimal(str(r)) * Decimal(str(contracts)) * p * (1 - p)
    quantum, rounding = _QUANTUM[spec["rounding"]]
    return float(exact.quantize(quantum, rounding=rounding))


def fee_per_contract(venue: str, contracts: float, price: float, maker: bool = False,
                     rate: float | None = None) -> float:
    return fee_total(venue, contracts, price, maker, rate) / contracts if contracts > 0 else 0.0


def all_in_cost(venue: str, price: float, contracts: float = config.PLANNED_CONTRACTS,
                maker: bool = False, rate: float | None = None) -> float:
    """Price plus fee per contract, for an order of `contracts`."""
    return price + fee_per_contract(venue, contracts, price, maker, rate)
