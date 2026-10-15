"""Print the class fund's payment instructions and the Czech QR payment string for a payment into the fund.

The script prints the fund's balance, the bank account with its IBAN, the variable and specific symbols, the
message for the recipient and the "QR Platba" (SPAYD) string that Czech banking apps scan. Draw the string as a QR
code with any QR code generator. Without an AMOUNT the string carries the amount the school set, if any, and the
payer fills it in otherwise.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/class_fund_qr.py [AMOUNT]          # e.g. 500 or 250,50 (CZK)

It only reads data. The class fund needs the school's Payments module; without it the server answers HTTP 403,
which the script reports.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariPermissionError


def czk(value: str) -> float:
    try:
        amount = float(value.replace(",", ".").replace(" ", ""))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an amount in CZK: {value!r}") from None
    if not 0 < amount <= 9_999_999.99:
        raise argparse.ArgumentTypeError(f"the amount must be between 0 and 9,999,999.99 CZK: {value!r}")
    return amount


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print the class fund payment instructions and QR payment string.")
    parser.add_argument("amount", nargs="?", type=czk, help="the amount to pay in CZK (default: the school's)")
    args = parser.parse_args(argv)

    try:
        client = BakalariClient.from_env()
        summary = client.class_fund_summary()
        info = client.class_fund_payment_info()
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariPermissionError as error:
        print("The class fund is not available: the Payments module is not enabled for this school or account "
              f"(HTTP 403: {error.message or 'no reason given'}).", file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1

    print(f"{summary.student_name_with_class}: balance {summary.balance:.2f} CZK, spent {summary.spent:.2f} CZK")
    if info.instructions:
        print(info.instructions)
    print(f"Account:         {info.bank_account or '-'}")
    print(f"IBAN:            {info.formatted_iban or '-'}")
    print(f"Variable symbol: {info.variable_symbol or '-'}")
    print(f"Specific symbol: {info.specific_symbol or '-'}")
    if info.amount > 0:
        print(f"Amount:          {info.amount:.2f} CZK")
    print(f"Message:         {info.message or '-'}")

    payment = info.qr_payment(amount=args.amount)
    if payment is None:
        print("\nNo QR payment: the bank account cannot be converted to an IBAN, or a symbol is not a number.")
        return 1
    print(f"\nQR payment string:\n{payment}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
