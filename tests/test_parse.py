import datetime as dt
import json
import unittest
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from bakalari import AttachmentInfo, BakalariContractError, Item, Model
from bakalari._parse import (
    check_shape,
    format_date,
    html_to_text,
    ident,
    objects,
    parse_date,
    parse_datetime,
    quote_segment,
    require_int,
    require_list,
    require_mapping,
    shape_problems,
    strings,
    text,
    to_bool,
    to_float,
    to_int,
    to_jsonable,
)

PRAGUE = dt.timezone(dt.timedelta(hours=2))


class DateTimeTest(unittest.TestCase):
    def test_server_timestamps(self):
        self.assertEqual(parse_datetime("2026-10-12T08:00:00+02:00"), dt.datetime(2026, 10, 12, 8, 0, tzinfo=PRAGUE))
        self.assertEqual(parse_datetime("2026-10-12T08:00:00.1234567+02:00"),
                         dt.datetime(2026, 10, 12, 8, 0, 0, 123456, tzinfo=PRAGUE))
        self.assertEqual(parse_datetime("2026-10-12T08:00:00.5Z"),
                         dt.datetime(2026, 10, 12, 8, 0, 0, 500000, tzinfo=dt.timezone.utc))
        self.assertEqual(parse_datetime("2026-10-12T08:00:00+0200"), dt.datetime(2026, 10, 12, 8, 0, tzinfo=PRAGUE))
        self.assertEqual(parse_datetime("2026-10-12T08:00:00"), dt.datetime(2026, 10, 12, 8, 0))
        self.assertEqual(parse_datetime("2026-10-12"), dt.datetime(2026, 10, 12))

    def test_empty_minimum_and_garbage_are_none(self):
        for value in (None, "", "   ", "0001-01-01T00:00:00+01:00", "not a date", "12.10."):
            self.assertIsNone(parse_datetime(value), value)

    def test_date_keeps_the_server_calendar_day(self):
        self.assertEqual(parse_date("2026-10-12T00:00:00+02:00"), dt.date(2026, 10, 12))
        self.assertEqual(parse_date(dt.date(2026, 1, 2)), dt.date(2026, 1, 2))
        self.assertEqual(parse_datetime(dt.date(2026, 1, 2)), dt.datetime(2026, 1, 2))
        self.assertIsNone(parse_date(None))

    def test_format_date(self):
        self.assertEqual(format_date(dt.date(2026, 10, 1)), "2026-10-01")
        self.assertEqual(format_date(dt.datetime(2026, 10, 1, 23, 59)), "2026-10-01")
        self.assertEqual(format_date("2026-10-01"), "2026-10-01")
        self.assertIsNone(format_date(None))
        self.assertIsNone(format_date(""))


class ScalarTest(unittest.TestCase):
    def test_text_and_ident(self):
        self.assertEqual(text("ČJL "), "ČJL")
        self.assertEqual(text(None), "")
        self.assertEqual(ident(" 2"), " 2")
        self.assertEqual(ident(None), "")
        self.assertEqual(ident(5), "5")

    def test_numbers(self):
        self.assertEqual(to_float("2,86 "), 2.86)
        self.assertEqual(to_float(" 1\u00a0000,5"), 1000.5)
        self.assertEqual(to_float(3), 3.0)
        self.assertIsNone(to_float(""))
        self.assertIsNone(to_float(True))
        self.assertEqual(to_int("7"), 7)
        self.assertEqual(to_int("7,9"), 7)
        self.assertEqual(to_int(None, 0), 0)
        self.assertIsNone(to_int("x"))
        self.assertEqual(to_int(True), 1)
        for value in ("inf", "Infinity", "1e400", float("inf"), float("nan"), "NaN"):
            self.assertIsNone(to_int(value), value)
            self.assertIsNone(to_float(value), value)
        self.assertEqual(to_float("1e400", 0.0), 0.0)

    def test_booleans(self):
        self.assertTrue(to_bool(True))
        self.assertTrue(to_bool("true"))
        self.assertFalse(to_bool("False"))
        self.assertFalse(to_bool(None))

    def test_collections(self):
        self.assertEqual(objects([{"a": 1}, None, 3, {"b": 2}]), [{"a": 1}, {"b": 2}])
        self.assertEqual(objects(None), [])
        self.assertEqual(strings(["A", None, 1]), ("A", "1"))
        self.assertEqual(strings("A"), ())

    def test_quote_segment(self):
        self.assertEqual(quote_segment("ZSQCVE[IMJ"), "ZSQCVE%5BIMJ")
        self.assertEqual(quote_segment("U   4AAAAG"), "U%20%20%204AAAAG")
        self.assertEqual(quote_segment("a/b(c)"), "a%2Fb%28c%29")


class HtmlToTextTest(unittest.TestCase):
    def test_blocks_breaks_lists_and_entities(self):
        source = ("<div>Dobr&#253; den,</div><p>zítra <b>nebude</b> výuka.<br/>Děkuji</p>"
                  "<ul><li>první</li><li>druhý</li></ul><script>alert(1)</script><style>p{}</style>")
        self.assertEqual(html_to_text(source), "Dobrý den,\n\nzítra nebude výuka.\nDěkuji\n\n- první\n- druhý")

    def test_links_and_images(self):
        source = ('<p>Viz <a href="https://example.com/x">rozpis</a> a <a href="https://example.com/y">'
                  'https://example.com/y</a>.</p><img src="data:image/png;base64,AAAA">')
        self.assertEqual(html_to_text(source), "Viz rozpis (https://example.com/x) a https://example.com/y.")

    def test_empty(self):
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text(""), "")
        self.assertEqual(html_to_text("plain text"), "plain text")


@dataclass(frozen=True)
class _Sample(Model):
    name: str
    when: Optional[dt.datetime]
    items: Tuple[Item, ...] = ()
    secret: str = field(default="", repr=False)
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


class ModelTest(unittest.TestCase):
    def test_to_dict_skips_raw_and_hidden_fields(self):
        when = dt.datetime(2026, 10, 12, 8, 0, tzinfo=PRAGUE)
        sample = _Sample("x", when, (Item("1", "A", "Alfa"),), "pwd", {"Id": 1})
        data = sample.to_dict()
        self.assertEqual(data, {"name": "x", "when": "2026-10-12T08:00:00+02:00",
                                "items": [{"id": "1", "abbrev": "A", "name": "Alfa"}]})
        json.dumps(data)
        converted = to_jsonable({"d": dt.date(2026, 1, 1), "b": b"x", "s": {1}})
        self.assertEqual(converted, {"d": "2026-01-01", "b": None, "s": [1]})

    def test_item(self):
        item = Item.from_json({"Id": " 2", "Abbrev": "ČJL ", "Name": " Český jazyk "})
        self.assertEqual((item.id, item.abbrev, item.name, str(item)), (" 2", "ČJL", "Český jazyk", "Český jazyk"))
        self.assertIsNone(Item.optional(None))
        self.assertIsNone(Item.optional({"Id": "", "Abbrev": "", "Name": ""}))
        self.assertEqual(str(Item("X", "", "")), "X")

    def test_attachment_info(self):
        info = AttachmentInfo.from_json({"Id": "U   4AAAAG", "Name": "a.pdf", "Type": "application/pdf", "Size": 6094})
        self.assertEqual((info.id, info.name, info.content_type), ("U   4AAAAG", "a.pdf", "application/pdf"))
        self.assertEqual(info.size, 6094)
        expected = {"id": "U   4AAAAG", "name": "a.pdf", "content_type": "application/pdf", "size": 6094}
        self.assertEqual(info.to_dict(), expected)


class ShapeTest(unittest.TestCase):
    def test_shape_problems(self):
        self.assertEqual(shape_problems([], "marks"), ["The marks must be a JSON object"])
        problems = shape_problems(
            {"Subjects": [{}, 1, "x"]}, "marks", lists=("Subjects", "MarkOptions"), objects_=("Subject",)
        )
        self.assertEqual(problems, [
            "Missing list 'MarkOptions'", "Missing object 'Subject'", "2 entries of 'Subjects' are not JSON objects"
        ])
        self.assertEqual(shape_problems({"A": [1]}, "x", lists=("A",)), ["1 entry of 'A' is not a JSON object"])

    def test_check_and_require(self):
        self.assertEqual(check_shape({"A": []}, "x", lists=("A",)), {"A": []})
        with self.assertRaises(BakalariContractError) as raised:
            check_shape({}, "marks", lists=("Subjects",))
        self.assertIn("The Bakaláři marks violates its contract", str(raised.exception))
        self.assertEqual(raised.exception.problems, ["Missing list 'Subjects'"])
        with self.assertRaises(BakalariContractError):
            require_mapping([], "x")
        with self.assertRaises(BakalariContractError):
            require_list({}, "x")
        self.assertEqual(require_int(3, "counter"), 3)
        self.assertEqual(require_int("4", "counter"), 4)
        for bad in (None, True, {}, "x", "Infinity", float("nan")):
            with self.assertRaises(BakalariContractError):
                require_int(bad, "counter")


if __name__ == "__main__":
    unittest.main()
