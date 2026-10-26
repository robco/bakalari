import datetime as dt
import json
import unittest
import urllib.parse

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError
from bakalari.payments import (
    CLASS_FUND_SORTS,
    ClassFundItem,
    ClassFundMonth,
    ClassFundPaymentInfo,
    ClassFundSummary,
    account_to_iban,
    format_iban,
    parse_class_fund_payments,
)

from .support import FORBIDDEN, json_response, load_fixture, logged_in_client

SUMMARY = load_fixture("payments_summary.json")
CLASS_FUND = load_fixture("payments_classfund.json")
PAYMENT_INFO = load_fixture("payments_info.json")
# The fixture account 35-1234567899/0100 (invented; it passes the Czech mod-11 check).
FIXTURE_IBAN = "CZ5901000000351234567899"
EMPTY_SEARCH = json_response(400, {
    "Message": "The request is invalid.",
    "ModelState": {
        "$type": "HttpError",
        "search.String": {"$type": "String[]", "$values": ["A value is required but was not present in the request."]},
    },
})


def mod97(iban):
    """The ISO 7064 mod-97 remainder of an IBAN, computed independently of the module (1 for a valid IBAN)."""
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(ord(character) - 55) if character.isalpha() else character for character in rearranged)
    return int(digits) % 97


def info(**fields):
    data = dict(PAYMENT_INFO)
    data.update(fields)
    return ClassFundPaymentInfo.from_json(data)


class IbanTest(unittest.TestCase):
    def test_known_example_with_a_prefix(self):
        iban = account_to_iban("19-2000145399/0800")
        self.assertEqual(iban, "CZ6508000000192000145399")
        self.assertEqual(format_iban(iban), "CZ65 0800 0000 1920 0014 5399")
        self.assertEqual(mod97(iban), 1)

    def test_account_without_a_prefix(self):
        iban = account_to_iban("1234567899/2010")
        self.assertEqual(iban, "CZ6920100000001234567899")
        bban = "2010" + "000000" + "1234567899"  # bank code, prefix padded to 6, number padded to 10 digits
        self.assertEqual(iban, "CZ%02d%s" % (98 - mod97("CZ00" + bban), bban))
        self.assertEqual(mod97(iban), 1)
        self.assertEqual(len(iban), 24)

    def test_fixture_account(self):
        self.assertEqual(account_to_iban(PAYMENT_INFO["BankAccount"]), FIXTURE_IBAN)
        self.assertEqual(mod97(FIXTURE_IBAN), 1)

    def test_spelling_variants_give_the_same_iban(self):
        for account in ("19-2000145399/0800", " 19 - 2000145399 / 0800 ", "000019-2000145399/0800",
                        "19–2000145399/0800", "CZ65 0800 0000 1920 0014 5399", "cz6508000000192000145399"):
            self.assertEqual(account_to_iban(account), "CZ6508000000192000145399", account)

    def test_short_numbers_are_padded(self):
        iban = account_to_iban("123/0800")
        self.assertEqual(iban, "CZ3808000000000000000123")
        self.assertEqual(mod97(iban), 1)

    def test_unusable_accounts_give_none(self):
        for account in (None, "", "   ", "abc", "2000145399", "19-2000145399", "19-2000145399/080",
                        "1234567-2000145399/0800", "19-12345678901/0800", "19-2000145398/0800", "18-2000145399/0800",
                        "00/0800", "CZ6608000000192000145399", "CZ65 0800 0000 1920 0014 539", 192000145399):
            self.assertIsNone(account_to_iban(account), account)

    def test_only_ascii_digits_count(self):
        # Other Unicode digits match \d and int() accepts them, but they must never end up in an IBAN.
        for account in ("١٩-٢٠٠٠١٤٥٣٩٩/٠٨٠٠", "１９-２０００１４５３９９/０８００", "19-2000145399/０８００",
                        "CZ６５08000000192000145399"):
            self.assertIsNone(account_to_iban(account), account)

    def test_format_iban_accepts_any_spacing(self):
        self.assertEqual(format_iban("cz69 2010 0000001234567899"), "CZ69 2010 0000 0012 3456 7899")
        self.assertEqual(format_iban(""), "")


class SummaryTest(unittest.TestCase):
    def test_fields(self):
        summary = ClassFundSummary.from_json(SUMMARY)
        self.assertEqual(summary, ClassFundSummary("Kolářová Eliška (2.B)", 1250.5, -3870.25))
        self.assertEqual(summary.raw, SUMMARY)
        data = summary.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data, {"student_name_with_class": "Kolářová Eliška (2.B)", "balance": 1250.5,
                                "spent": -3870.25})

    def test_lenient_values(self):
        summary = ClassFundSummary.from_json({"StudentNameWithClass": " Kolářová Eliška (2.B) ", "Balance": "1 250,50"})
        self.assertEqual((summary.student_name_with_class, summary.balance, summary.spent),
                         ("Kolářová Eliška (2.B)", 1250.5, 0.0))
        self.assertEqual(ClassFundSummary.from_json({"Balance": None, "Spent": "x"}).balance, 0.0)

    def test_non_object_payload_raises(self):
        for payload in ([], None, 12):
            with self.assertRaises(BakalariContractError):
                ClassFundSummary.from_json(payload)

    def test_non_finite_amounts_become_zero(self):
        # json.loads accepts NaN and Infinity; to_dict() must still be strict JSON.
        summary = ClassFundSummary.from_json(json.loads('{"Balance": NaN, "Spent": -Infinity}'))
        self.assertEqual((summary.balance, summary.spent), (0.0, 0.0))
        json.dumps(summary.to_dict(), allow_nan=False)
        self.assertEqual(ClassFundSummary.from_json({"Balance": "inf", "Spent": -0.0}).to_dict()["balance"], 0.0)


class ClassFundPaymentsTest(unittest.TestCase):
    def test_months_and_items(self):
        months = parse_class_fund_payments(CLASS_FUND)
        self.assertEqual([month.month for month in months],
                         [dt.date(2026, 10, 1), dt.date(2026, 9, 1), dt.date(2026, 8, 1)])
        october, september, august = months
        self.assertEqual(october.balance, 160.0)
        self.assertIsInstance(october.balance, float)
        self.assertEqual(october.items, (
            ClassFundItem("Divadlo 2.B", dt.date(2026, 10, 8), -90.0),
            ClassFundItem("Příjem z banky (Kolářová Eliška)", dt.date(2026, 10, 2), 250.0),
        ))
        self.assertEqual(september.items[0].description, "Pracovní sešit Fyzika 2")
        self.assertEqual((september.balance, september.items[0].amount), (-49.5, -399.5))
        self.assertEqual(sum(item.amount for item in september.items), september.balance)
        self.assertEqual((august.balance, august.items), (0.0, ()))

    def test_to_dict_and_raw(self):
        october = parse_class_fund_payments(CLASS_FUND)[0]
        data = october.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data["month"], "2026-10-01")
        self.assertEqual(data["items"][0], {"description": "Divadlo 2.B", "date": "2026-10-08", "amount": -90.0})
        self.assertEqual(october.raw, CLASS_FUND["MonthlyData"][0])
        self.assertEqual(october.items[1].raw, CLASS_FUND["MonthlyData"][0]["Items"][1])

    def test_missing_optional_fields(self):
        month = ClassFundMonth.from_json({"Items": [None, {"Amount": "12,5"}]})
        self.assertEqual(month, ClassFundMonth(None, 0.0, (ClassFundItem("", None, 12.5),)))

    def test_non_finite_amounts_become_zero(self):
        payload = json.loads('{"MonthlyData": [{"MonthlyBalance": NaN, "Items": [{"Amount": Infinity}]}]}')
        (month,) = parse_class_fund_payments(payload)
        self.assertEqual((month.balance, month.items[0].amount), (0.0, 0.0))
        json.dumps(month.to_dict(), allow_nan=False)

    def test_contract(self):
        for payload in ([], None):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError):
                    parse_class_fund_payments(payload, validate=validate)
        with self.assertRaises(BakalariContractError) as raised:
            parse_class_fund_payments({"Monthly": []})
        self.assertEqual(raised.exception.problems, ["Missing list 'MonthlyData'"])
        self.assertEqual(parse_class_fund_payments({"Monthly": []}, validate=False), [])
        mixed = {"MonthlyData": [CLASS_FUND["MonthlyData"][2], "2026-07"]}
        with self.assertRaises(BakalariContractError):
            parse_class_fund_payments(mixed)
        self.assertEqual(len(parse_class_fund_payments(mixed, validate=False)), 1)


class PaymentInfoTest(unittest.TestCase):
    def test_fields(self):
        payment = ClassFundPaymentInfo.from_json(PAYMENT_INFO)
        self.assertEqual(payment.instructions, PAYMENT_INFO["Instructions"])
        self.assertEqual((payment.bank_account, payment.variable_symbol, payment.specific_symbol),
                         ("35-1234567899/0100", "2026001234", "2222"))
        self.assertEqual((payment.amount, payment.message), (0.0, "2.B  Kolářová Eliška třídní fond"))
        self.assertEqual(payment.iban, FIXTURE_IBAN)
        self.assertEqual(payment.formatted_iban, "CZ59 0100 0000 3512 3456 7899")
        self.assertEqual(payment.raw, PAYMENT_INFO)

    def test_to_dict_has_the_fields_only(self):
        data = ClassFundPaymentInfo.from_json(PAYMENT_INFO).to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(sorted(data), ["amount", "bank_account", "instructions", "message", "specific_symbol",
                                        "variable_symbol"])

    def test_symbols(self):
        for value, expected in ((None, ""), (0, ""), ("0", ""), (1111, "1111"), (1111.0, "1111"), (" 0042 ", "0042"),
                                (True, "")):
            self.assertEqual(info(VariableSymbol=value).variable_symbol, expected, value)

    def test_missing_fields_and_unusable_account(self):
        payment = ClassFundPaymentInfo.from_json({})
        self.assertEqual(payment, ClassFundPaymentInfo())
        self.assertIsNone(payment.iban)
        self.assertIsNone(payment.formatted_iban)
        with self.assertRaises(BakalariContractError):
            ClassFundPaymentInfo.from_json(["BankAccount"])


class QrPaymentTest(unittest.TestCase):
    def test_spayd_string_of_the_fixture(self):
        expected = f"SPD*1.0*ACC:{FIXTURE_IBAN}*CC:CZK*X-VS:2026001234*X-SS:2222*MSG:2.B Kolarova Eliska tridni fond"
        self.assertEqual(ClassFundPaymentInfo.from_json(PAYMENT_INFO).qr_payment(), expected)

    def test_spayd_structure(self):
        spayd = info(Amount=480.5).qr_payment()
        header, version, *pairs = spayd.split("*")
        self.assertEqual((header, version), ("SPD", "1.0"))
        keys = [pair.split(":", 1)[0] for pair in pairs]
        self.assertEqual(keys, ["ACC", "AM", "CC", "X-VS", "X-SS", "MSG"])
        self.assertTrue(all(":" in pair and pair.split(":", 1)[1] for pair in pairs))
        self.assertEqual(dict(pair.split(":", 1) for pair in pairs)["AM"], "480.50")

    def test_amount_from_the_server_or_the_caller(self):
        self.assertIn("*AM:300.00*CC:CZK*", info(Amount=300).qr_payment())
        self.assertIn(f"ACC:{FIXTURE_IBAN}*AM:450.00*CC:CZK*", info().qr_payment(amount=450))
        self.assertIn("*AM:1234.57*", info().qr_payment(amount=1234.567))
        self.assertNotIn("AM:", info(Amount=300).qr_payment(amount=0))
        self.assertNotIn("AM:", info(Amount=-20).qr_payment())

    def test_amounts_that_round_to_zero_are_left_out(self):
        for amount in (0.001, 0.004):
            self.assertNotIn("AM:", info().qr_payment(amount=amount), amount)
        self.assertNotIn("AM:", info(Amount=0.003).qr_payment())
        self.assertNotIn("AM:", info(Amount=float("nan")).qr_payment())
        self.assertIn("*AM:0.01*", info().qr_payment(amount=0.006))

    def test_invalid_amounts_raise(self):
        for amount in (-1, float("nan"), float("inf"), 10_000_000):
            with self.assertRaises(ValueError):
                info().qr_payment(amount=amount)
        self.assertIn("AM:9999999.99", info().qr_payment(amount=9_999_999.99))

    def test_message_is_cleaned_escaped_and_cut(self):
        self.assertTrue(info().qr_payment(message="Fond\n2.B\t*  Kolářová*").endswith("*MSG:Fond 2.B %2A Kolarova%2A"))
        self.assertNotIn("MSG", info().qr_payment(message=""))
        self.assertNotIn("MSG", info(Message="   ").qr_payment())
        long_message = info().qr_payment(message="x" * 70).split("*MSG:")[1]
        self.assertEqual(long_message, "x" * 60)
        cut = info().qr_payment(message="y" * 58 + "*z").split("*MSG:")[1]
        self.assertEqual(cut, "y" * 58)  # the escape %2A would not fit, so it is left out whole

    def test_message_is_plain_ascii(self):
        # SPAYD allows raw ISO-8859-1 only (no ř, č, ě, ů) and URL-decodes values, so the string must not depend on
        # the text encoding of the QR code.
        spayd = info().qr_payment(message="Šťukání: Dvořák, Ďůrová – „5%20“\u00a0€ ł​!\x00")
        self.assertTrue(spayd.endswith('*MSG:Stukani: Dvorak, Durova - "5%2520" %E2%82%AC %C5%82!'), spayd)
        self.assertEqual(spayd.encode("utf-8"), spayd.encode("latin-1"))
        self.assertTrue(all(" " <= character <= "~" for character in spayd))
        message = spayd.split("*MSG:")[1]
        self.assertEqual(urllib.parse.unquote(message), 'Stukani: Dvorak, Durova - "5%20" € ł!')

    def test_cut_message_keeps_escapes_whole_and_has_no_trailing_space(self):
        cut = info().qr_payment(message="z" * 55 + " €uro").split("*MSG:")[1]
        self.assertEqual(cut, "z" * 55)  # the space is dropped and the 9-character escape of € does not fit
        self.assertEqual(info().qr_payment(message="w" * 59 + " tail").split("*MSG:")[1], "w" * 59)
        self.assertEqual(len(info().qr_payment(message="ř" * 80).split("*MSG:")[1]), 60)

    def test_empty_parts_are_omitted(self):
        payment = info(VariableSymbol=None, SpecificSymbol=0, Message=None)
        self.assertEqual(payment.qr_payment(), f"SPD*1.0*ACC:{FIXTURE_IBAN}*CC:CZK")

    def test_an_iban_in_the_account_field_is_used(self):
        payment = info(BankAccount="CZ65 0800 0000 1920 0014 5399", SpecificSymbol=None)
        self.assertTrue(payment.qr_payment().startswith("SPD*1.0*ACC:CZ6508000000192000145399*CC:CZK*X-VS:2026001234*"))

    def test_no_qr_payment_without_an_iban_or_with_an_unusable_symbol(self):
        self.assertIsNone(info(BankAccount="").qr_payment())
        self.assertIsNone(info(BankAccount="19-2000145398/0800").qr_payment())
        self.assertIsNone(info(VariableSymbol="12/34").qr_payment())
        self.assertIsNone(info(SpecificSymbol=12345678901).qr_payment())
        self.assertIsNone(info(VariableSymbol="١٢٣").qr_payment())  # Arabic-Indic digits are not a SPAYD integer


class PaymentsEndpointTest(unittest.TestCase):
    def test_class_fund_summary(self):
        client, transport = logged_in_client(json_response(200, SUMMARY))
        self.assertEqual(client.class_fund_summary().balance, 1250.5)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/payments/classfund/summary", {}))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")

    def test_class_fund_payments_default_to_newest_first(self):
        client, transport = logged_in_client(json_response(200, CLASS_FUND))
        months = client.class_fund_payments()
        self.assertEqual(len(months), 3)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query),
                         ("GET", "/api/3/payments/classfund", {"sort": "desc"}))

    def test_class_fund_payments_sort_and_search(self):
        client, transport = logged_in_client(json_response(200, {"MonthlyData": []}))
        self.assertEqual(client.class_fund_payments(sort="asc", search="kino & divadlo 0"), [])
        call = transport.api_calls[0]
        self.assertEqual(call.query, {"sort": "asc", "search": "kino & divadlo 0"})
        self.assertIn("search=kino+%26+divadlo+0", call.url)
        self.assertEqual(CLASS_FUND_SORTS, ("asc", "desc"))

    def test_invalid_arguments_are_rejected_before_any_request(self):
        client, transport = logged_in_client()
        for kwargs in ({"search": ""}, {"search": "  "}, {"sort": "newest"}, {"sort": "ASC"}):
            with self.assertRaises(ValueError):
                client.class_fund_payments(**kwargs)
        self.assertEqual(transport.calls, [])

    def test_server_rejection_of_a_search_propagates(self):
        client, _ = logged_in_client(EMPTY_SEARCH)
        with self.assertRaises(BakalariHTTPError) as raised:
            client.class_fund_payments(search="x")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("search.String", raised.exception.body["ModelState"])

    def test_validation_can_be_turned_off(self):
        client, _ = logged_in_client(json_response(200, {}), json_response(200, {}))
        with self.assertRaises(BakalariContractError):
            client.class_fund_payments()
        self.assertEqual(client.class_fund_payments(validate=False), [])

    def test_class_fund_payment_info(self):
        client, transport = logged_in_client(json_response(200, PAYMENT_INFO))
        payment = client.class_fund_payment_info()
        self.assertEqual(payment.iban, FIXTURE_IBAN)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("GET", "/api/3/payments/classfund/paymentsinfo"))

    def test_regular_payments_summary_is_raw_json(self):
        payload = {"Payments": [{"Name": "Školné", "Amount": 500}], "$type": "Summary"}
        client, transport = logged_in_client(json_response(200, payload))
        self.assertEqual(client.regular_payments_summary(), payload)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("GET", "/api/3/payments/regularpayments/summary"))

    def test_disabled_module_raises_permission_errors(self):
        client, _ = logged_in_client(FORBIDDEN, FORBIDDEN, FORBIDDEN, FORBIDDEN)
        for method in (client.class_fund_summary, client.class_fund_payments, client.class_fund_payment_info,
                       client.regular_payments_summary):
            with self.assertRaises(BakalariPermissionError) as raised:
                method()
            self.assertEqual(raised.exception.message, "An error has occurred.")

    def test_unexpected_payloads_are_contract_errors(self):
        client, _ = logged_in_client(json_response(200, []), json_response(200, "info"))
        with self.assertRaises(BakalariContractError):
            client.class_fund_summary()
        with self.assertRaises(BakalariContractError):
            client.class_fund_payment_info()


if __name__ == "__main__":
    unittest.main()
