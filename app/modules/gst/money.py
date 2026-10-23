"""Decimal-only money helpers for the GST engine.

Money is never a float. Amounts are Decimal and rounded half-up
(0.005 -> 0.01, ties go away from zero), as is usual on GST invoices.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.exceptions import ValidationError

PAISE = Decimal("0.01")
RUPEE = Decimal("1")
HUNDRED = Decimal("100")


def to_decimal(value, field: str = "value") -> Decimal:
    """Convert int, str or Decimal to a finite Decimal. Floats and bools are rejected."""
    if isinstance(value, (bool, float)):
        raise ValidationError(
            f"{field} must be Decimal, int or str, not {type(value).__name__}"
        )
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"{field} is not a valid number: {value!r}") from None
    if not result.is_finite():
        raise ValidationError(f"{field} must be a finite number: {value!r}")
    return result


def round_paise(value: Decimal) -> Decimal:
    """Round to 2 decimal places, half-up."""
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def round_rupee(value: Decimal) -> Decimal:
    """Round to a whole rupee, half-up."""
    return value.quantize(RUPEE, rounding=ROUND_HALF_UP)


def percent_of(base: Decimal, rate_percent: Decimal) -> Decimal:
    """rate_percent% of base, rounded to paise."""
    return round_paise(base * rate_percent / HUNDRED)


def round_off(total: Decimal) -> tuple[Decimal, Decimal]:
    """Return (nearest-rupee total, round-off adjustment), both with 2 decimals."""
    rounded = round_rupee(total).quantize(PAISE)
    return rounded, round_paise(rounded - total)
