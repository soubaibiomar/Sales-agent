"""
Precise Money Representation and Arithmetic.
(Baseline Control 51; Exact Integer Minor Units / Cents; Strictly NO Float Arithmetic)
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN
from typing import Union, Tuple, Dict, Any

class CurrencyMismatchError(ValueError):
    pass

class NegativeQuantityError(ValueError):
    pass

class Money:
    """
    Immutable Money class represented in minor units (integer cents/centimes).
    Avoids all binary floating-point representation and rounding errors.
    """
    __slots__ = ("_cents", "_currency")

    def __init__(self, cents: int, currency: str = "MAD"):
        if not isinstance(cents, int):
            raise TypeError(f"Money cents must be an integer, got {type(cents).__name__}")
        self._cents = cents
        self._currency = currency.upper().strip()

    @property
    def cents(self) -> int:
        return self._cents

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def decimal_amount(self) -> Decimal:
        """Returns exact Decimal value in major units (e.g. 1050 cents -> Decimal('10.50'))."""
        return Decimal(self._cents) / Decimal(100)

    @classmethod
    def from_major(cls, amount: Union[Decimal, str, int], currency: str = "MAD") -> "Money":
        """Constructs Money from major units string or Decimal (e.g. '10.50' -> 1050 cents)."""
        dec = Decimal(str(amount))
        cents = int((dec * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cls(cents=cents, currency=currency)

    @classmethod
    def zero(cls, currency: str = "MAD") -> "Money":
        return cls(0, currency)

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(f"Cannot add {self._currency} and {other._currency}")
        return Money(self._cents + other._cents, self._currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(f"Cannot subtract {other._currency} from {self._currency}")
        return Money(self._cents - other._cents, self._currency)

    def __mul__(self, factor: Union[int, Decimal, str]) -> "Money":
        if isinstance(factor, float):
            raise TypeError("Floating point multiplication is strictly forbidden for Money. Use Decimal, int, or str.")
        dec_factor = Decimal(str(factor))
        new_cents = int((Decimal(self._cents) * dec_factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return Money(new_cents, self._currency)

    def __rmul__(self, factor: Union[int, Decimal, str]) -> "Money":
        return self.__mul__(factor)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self._cents == other._cents and self._currency == other._currency

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(f"Cannot compare {self._currency} and {other._currency}")
        return self._cents < other._cents

    def __le__(self, other: "Money") -> bool:
        return self < other or self == other

    def __gt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self._currency != other._currency:
            raise CurrencyMismatchError(f"Cannot compare {self._currency} and {other._currency}")
        return self._cents > other._cents

    def __ge__(self, other: "Money") -> bool:
        return self > other or self == other

    def __repr__(self) -> str:
        return f"Money({self._cents} cents, {self._currency})"

    def __str__(self) -> str:
        return f"{self._currency} {self.decimal_amount:.2f}"

    def format(self) -> str:
        """Formatted string with thousand separators (e.g. 'MAD 1,250.00')."""
        return f"{self._currency} {self.decimal_amount:,.2f}"

    def percentage(self, percent: Union[Decimal, str, int]) -> "Money":
        """Calculates percentage of money using exact integer rounding (ROUND_HALF_UP)."""
        dec_pct = Decimal(str(percent)) / Decimal(100)
        return self * dec_pct


def calculate_tax(amount_cents: int, tax_rate_percent: Union[Decimal, str, int, float]) -> int:
    """Calculates tax in integer minor units given base amount and tax rate percent."""
    rate = Decimal(str(tax_rate_percent)) / Decimal(100)
    tax_cents = (Decimal(amount_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(tax_cents)


def calculate_discount(amount_cents: int, discount_percent: Union[Decimal, str, int, float]) -> int:
    """Calculates discount amount in minor units."""
    rate = Decimal(str(discount_percent)) / Decimal(100)
    disc_cents = (Decimal(amount_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(disc_cents)


def calculate_margin_percent(revenue_cents: int, cost_cents: int) -> Decimal:
    """
    Calculates profit margin percent: ((revenue - cost) / revenue) * 100.
    Returns 0.00 if revenue <= 0.
    """
    if revenue_cents <= 0:
        return Decimal("0.00")
    rev = Decimal(revenue_cents)
    cost = Decimal(cost_cents)
    margin = ((rev - cost) / rev) * Decimal(100)
    return margin.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
