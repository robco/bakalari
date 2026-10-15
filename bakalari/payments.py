"""Payments: the class fund (its balance, its income and expenses by month, how to pay into it) and the regular
payments summary.

Every endpoint needs the Payments module of the school; without it the server answers HTTP 403
(:class:`~bakalari.BakalariPermissionError`). Amounts are in CZK. The mobile app draws the QR code for a payment
into the fund itself from the payment instructions; :meth:`ClassFundPaymentInfo.qr_payment` builds such a Czech
"QR Platba" (SPAYD) string and :func:`account_to_iban` converts a Czech account number to its IBAN.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

from ._core import ClientCore, api_path
from ._parse import check_shape, objects, parse_date, require_mapping, text, to_float
from .models import Model

CLASS_FUND_SORTS = ("asc", "desc")

__all__ = [
    "CLASS_FUND_SORTS",
    "ClassFundItem",
    "ClassFundMonth",
    "ClassFundPaymentInfo",
    "ClassFundSummary",
    "PaymentsEndpoints",
    "account_to_iban",
    "format_iban",
    "parse_class_fund_payments",
]

# A Czech account number: an optional prefix of up to 6 digits, the number of 2 to 10 digits and the bank code.
# ASCII digits only ([0-9], not \d), so the IBAN and the SPAYD symbols never contain other Unicode digits.
_CZECH_ACCOUNT = re.compile(r"(?:([0-9]{1,6})-)?([0-9]{2,10})/([0-9]{4})")
_IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
_IBAN_LENGTHS = {"CZ": 24, "SK": 24}
# Weights of the mod-11 check that every Czech account prefix and number passes (CNB decree 169/2011).
_PREFIX_WEIGHTS = (10, 5, 8, 4, 2, 1)
_NUMBER_WEIGHTS = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)
_SPAYD_CURRENCY = "CZK"
_SPAYD_MESSAGE_LENGTH = 60
_SPAYD_MAX_AMOUNT = 9_999_999.99
_SPAYD_SYMBOL = re.compile(r"[0-9]{1,10}")
_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2212", "-"))
# Typographic quotes (the Czech low-high pair, curly and angle quotes) read better as ASCII quotes than as escapes.
_QUOTES = str.maketrans({
    **dict.fromkeys("\u201e\u201c\u201d\u00ab\u00bb", '"'),
    **dict.fromkeys("\u201a\u2018\u2019", "'"),
})


def _iban_remainder(iban: str) -> int:
    """The ISO 13616 mod-97 remainder of an IBAN (1 for a valid one): the country code and check digits move to the
    end and letters become numbers (A=10 ... Z=35)."""
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(character, 36)) for character in rearranged)) % 97


def _passes_mod11(digits: str, weights: Tuple[int, ...]) -> bool:
    return sum(int(digit) * weight for digit, weight in zip(digits, weights)) % 11 == 0


def account_to_iban(account: Any) -> Optional[str]:
    """The IBAN (without spaces) of a Czech account number ``prefix-number/bank`` such as ``19-2000145399/0800``
    (``CZ6508000000192000145399``); the prefix is optional and spaces are ignored. An IBAN is returned normalised.
    ``None`` when the value is empty, malformed, fails the Czech mod-11 check or is an invalid IBAN."""
    compact = re.sub(r"\s+", "", text(account)).upper().translate(_DASHES)
    if _IBAN.fullmatch(compact):
        valid = len(compact) == _IBAN_LENGTHS.get(compact[:2], len(compact)) and _iban_remainder(compact) == 1
        return compact if valid else None
    match = _CZECH_ACCOUNT.fullmatch(compact)
    if not match:
        return None
    prefix, number, bank = (match.group(1) or "").zfill(6), match.group(2).zfill(10), match.group(3)
    if int(number) == 0 or not (_passes_mod11(prefix, _PREFIX_WEIGHTS) and _passes_mod11(number, _NUMBER_WEIGHTS)):
        return None
    bban = bank + prefix + number
    return f"CZ{98 - _iban_remainder('CZ00' + bban):02d}{bban}"


def format_iban(iban: str) -> str:
    """An IBAN in its printed form, in groups of four characters: ``CZ65 0800 0000 1920 0014 5399``."""
    compact = re.sub(r"\s+", "", iban).upper()
    return " ".join(compact[index:index + 4] for index in range(0, len(compact), 4))


def _amount(value: Any) -> float:
    """An amount in CZK; missing, unparseable and non-finite values (``NaN``, which ``json`` accepts) are 0."""
    amount = to_float(value)
    return amount if amount and math.isfinite(amount) else 0.0


def _symbol(value: Any) -> str:
    """A variable or specific symbol as the digits the server sends as a number; ``null`` and 0 mean none."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    symbol = text(value)
    return symbol if symbol.strip("0") else ""


def _spayd_text(value: str, limit: int) -> str:
    """A SPAYD text value in printable ASCII, cut to ``limit`` characters without splitting an escape.

    SPAYD allows only ISO-8859-1 characters as they are, which leaves out most Czech letters (``ř``, ``č``, ``ě``),
    and it URL-decodes values. So letters lose their diacritics (``Kolářová`` becomes ``Kolarova``, as common QR
    payment generators do), typographic dashes and quotes become ``-`` and ``"``, whitespace collapses to single
    spaces, invisible characters are dropped, and the separator ``*``, ``%`` and any remaining character outside
    printable ASCII are percent-encoded as UTF-8 (``%2A``, ``%25``, ``%E2%82%AC``). The result is the same in
    whatever text encoding the QR code is drawn.
    """
    kept: List[str] = []
    for character in unicodedata.normalize("NFKD", value.translate(_DASHES).translate(_QUOTES)):
        category = unicodedata.category(character)
        if category == "Cc" or category.startswith("Z"):  # line breaks, tabs, no-break spaces
            kept.append(" ")
        elif category != "Mn" and not category.startswith("C"):  # Mn: the diacritics NFKD splits off
            kept.append(character)
    pieces: List[str] = []
    length = 0
    for character in " ".join("".join(kept).split()):
        plain = " " <= character <= "~" and character not in "*%"
        piece = character if plain else urllib.parse.quote(character, safe="")
        if length + len(piece) > limit:
            break
        pieces.append(piece)
        length += len(piece)
    return "".join(pieces).rstrip()


@dataclass(frozen=True)
class ClassFundSummary(Model):
    """The state of the student's class fund account: ``balance`` and the amount ``spent`` so far (the server
    sends it as a negative number)."""

    student_name_with_class: str
    balance: float = 0.0
    spent: float = 0.0
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any) -> "ClassFundSummary":
        """Parses the summary payload; a payload that is not a JSON object raises
        :class:`~bakalari.BakalariContractError`."""
        payload = require_mapping(data, "class fund summary")
        return cls(
            student_name_with_class=text(payload.get("StudentNameWithClass")),
            balance=_amount(payload.get("Balance")),
            spent=_amount(payload.get("Spent")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ClassFundItem(Model):
    """One movement of the class fund: an income (positive ``amount``) or an expense (negative)."""

    description: str
    date: Optional[dt.date] = None
    amount: float = 0.0
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ClassFundItem":
        """Parses one entry of a month's ``Items``."""
        return cls(
            description=text(data.get("Description")),
            date=parse_date(data.get("Date")),
            amount=_amount(data.get("Amount")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class ClassFundMonth(Model):
    """The class fund movements of one month: ``month`` is its first day and ``balance`` the sum of its income and
    expenses."""

    month: Optional[dt.date]
    balance: float = 0.0
    items: Tuple[ClassFundItem, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ClassFundMonth":
        """Parses one entry of the ``MonthlyData`` list."""
        return cls(
            month=parse_date(data.get("Date")),
            balance=_amount(data.get("MonthlyBalance")),
            items=tuple(ClassFundItem.from_json(item) for item in objects(data.get("Items"))),
            raw=dict(data),
        )


@dataclass(frozen=True)
class ClassFundPaymentInfo(Model):
    """How to pay into the class fund: the ``instructions`` text, the ``bank_account`` (Czech ``prefix-number/bank``
    format), the variable and specific symbols (``""`` when there is none), the ``amount`` (0 when none is set) and
    the ``message`` for the recipient."""

    instructions: str = ""
    bank_account: str = ""
    variable_symbol: str = ""
    specific_symbol: str = ""
    amount: float = 0.0
    message: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any) -> "ClassFundPaymentInfo":
        """Parses the payment instructions payload; a payload that is not a JSON object raises
        :class:`~bakalari.BakalariContractError`."""
        payload = require_mapping(data, "class fund payment info")
        return cls(
            instructions=text(payload.get("Instructions")),
            bank_account=text(payload.get("BankAccount")),
            variable_symbol=_symbol(payload.get("VariableSymbol")),
            specific_symbol=_symbol(payload.get("SpecificSymbol")),
            amount=_amount(payload.get("Amount")),
            message=text(payload.get("Message")),
            raw=dict(payload),
        )

    @property
    def iban(self) -> Optional[str]:
        """The IBAN of ``bank_account`` without spaces (see :func:`account_to_iban`), or ``None`` when the account
        cannot be converted."""
        return account_to_iban(self.bank_account)

    @property
    def formatted_iban(self) -> Optional[str]:
        """The IBAN in groups of four characters (``CZ65 0800 0000 1920 0014 5399``), or ``None``."""
        iban = self.iban
        return format_iban(iban) if iban else None

    def qr_payment(self, *, amount: Optional[float] = None, message: Optional[str] = None) -> Optional[str]:
        """The Czech QR payment ("QR Platba", SPAYD 1.0) string to draw as a QR code,
        ``SPD*1.0*ACC:<IBAN>*AM:<amount>*CC:CZK*X-VS:<vs>*X-SS:<ss>*MSG:<message>`` without the empty parts.

        ``amount`` and ``message`` replace the server's values; an amount that rounds to 0.00 is left out, so the
        payer fills it in. The message becomes plain ASCII (letters lose their diacritics; ``*``, ``%`` and other
        characters are percent-encoded as SPAYD allows) cut to 60 characters, so the string is the same in any text
        encoding. Returns ``None`` when the bank account has no IBAN or a symbol is not a number of at most 10 digits;
        an ``amount`` that is negative, not finite or above 9,999,999.99 raises ``ValueError``."""
        if amount is not None and not (math.isfinite(amount) and 0 <= amount <= _SPAYD_MAX_AMOUNT):
            raise ValueError(f"A QR payment amount must be between 0 and {_SPAYD_MAX_AMOUNT:.2f} CZK, got {amount!r}")
        iban = self.iban
        symbols = (("X-VS", self.variable_symbol), ("X-SS", self.specific_symbol))
        if iban is None or any(symbol and not _SPAYD_SYMBOL.fullmatch(symbol) for _, symbol in symbols):
            return None
        total = self.amount if amount is None else amount
        parts = ["SPD", "1.0", f"ACC:{iban}"]
        if math.isfinite(total) and 0 < round(total, 2) <= _SPAYD_MAX_AMOUNT:
            parts.append(f"AM:{total:.2f}")
        parts.append(f"CC:{_SPAYD_CURRENCY}")
        parts.extend(f"{key}:{symbol}" for key, symbol in symbols if symbol)
        note = _spayd_text(self.message if message is None else message, _SPAYD_MESSAGE_LENGTH)
        if note:
            parts.append(f"MSG:{note}")
        return "*".join(parts)


def parse_class_fund_payments(data: Any, *, validate: bool = True) -> List[ClassFundMonth]:
    """Parses a ``{"MonthlyData": [...]}`` payload. With ``validate`` (default) a payload without that list of
    objects raises :class:`~bakalari.BakalariContractError`; a payload that is not a JSON object always raises."""
    if validate:
        payload = check_shape(data, "class fund payment list", lists=("MonthlyData",))
    else:
        payload = require_mapping(data, "class fund payment list")
    return [ClassFundMonth.from_json(month) for month in objects(payload.get("MonthlyData"))]


class PaymentsEndpoints(ClientCore):
    """Payment endpoints of :class:`~bakalari.BakalariClient`."""

    def class_fund_summary(self) -> ClassFundSummary:
        """``GET /api/3/payments/classfund/summary``: the student's class fund balance and how much has been spent."""
        return ClassFundSummary.from_json(self.get_json(api_path("payments", "classfund", "summary")))

    def class_fund_payments(
        self, *, sort: str = "desc", search: Optional[str] = None, validate: bool = True
    ) -> List[ClassFundMonth]:
        """``GET /api/3/payments/classfund?sort=&search=``: the income and expenses of the class fund grouped by
        month, newest first (``sort="desc"``, the server's default) or oldest first (``"asc"``), optionally only those
        matching ``search``. The server rejects an empty search with HTTP 400, so it raises ``ValueError`` here."""
        if sort not in CLASS_FUND_SORTS:
            raise ValueError(f"Unknown sort order {sort!r}: use 'asc' or 'desc'")
        if search is not None and not search.strip():
            raise ValueError("The class fund search text must not be empty")
        data = self.get_json(api_path("payments", "classfund"), {"sort": sort, "search": search})
        return parse_class_fund_payments(data, validate=validate)

    def class_fund_payment_info(self) -> ClassFundPaymentInfo:
        """``GET /api/3/payments/classfund/paymentsinfo``: how to pay into the class fund (bank account, symbols,
        amount and message); see :meth:`ClassFundPaymentInfo.qr_payment` for the QR payment string."""
        return ClassFundPaymentInfo.from_json(self.get_json(api_path("payments", "classfund", "paymentsinfo")))

    def regular_payments_summary(self) -> Any:
        """``GET /api/3/payments/regularpayments/summary``: the summary of the regular payments (such as school fees)
        as raw JSON, because its payload is undocumented."""
        return self.get_json(api_path("payments", "regularpayments", "summary"))
