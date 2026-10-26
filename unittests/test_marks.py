import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError, Item
from bakalari.marks import (
    CertificateTerm,
    FinalMark,
    Mark,
    Marks,
    PedagogicalMeasure,
    SubjectMarks,
    parse_final_marks,
    parse_pedagogical_measures,
)

from .support import FORBIDDEN, empty_response, json_response, load_fixture, logged_in_client, text_response

SUMMER = dt.timezone(dt.timedelta(hours=2))
WINTER = dt.timezone(dt.timedelta(hours=1))
CZECH_ENTRIES = [
    {"Id": "QX7K0A{1}B", "MarkText": "1", "Weight": 2, "MaxPoints": 0, "SubjectId": " 4"},
    {"Id": "QX7K0A(2)C", "MarkText": "3-", "Weight": 4, "MaxPoints": 0, "SubjectId": " 4"},
    {"Id": "QX7K0B:3/D", "MarkText": "2", "Weight": 1, "MaxPoints": 0, "SubjectId": " 4"},
]


def parsed_marks():
    return Marks.from_json(load_fixture("marks.json"))


class MarkTest(unittest.TestCase):
    def setUp(self):
        self.czech, self.maths, self.physics = parsed_marks().subjects

    def test_confirmed_classic_mark(self):
        mark = self.czech.marks[0]
        self.assertEqual((mark.id, mark.subject_id, mark.text), ("QX7K0A{1}B", " 4", "1"))
        self.assertEqual((mark.caption, mark.theme), ("Diktát 1", "Vyjmenovaná slova po B"))
        self.assertEqual(mark.date, dt.date(2026, 9, 14))
        self.assertEqual(mark.edit_date, dt.datetime(2026, 9, 14, 13, 5, tzinfo=SUMMER))
        self.assertEqual((mark.teacher_id, mark.type, mark.type_note, mark.weight), ("UQX7K", "G", "diktát", 2))
        self.assertEqual((mark.is_new, mark.is_points, mark.is_invalid_date), (False, False, False))
        self.assertEqual((mark.points_text, mark.max_points, mark.calculated_text), ("", 0, ""))
        self.assertEqual((mark.class_rank_text, mark.verbal_evaluation), ("", ""))
        self.assertEqual((mark.confirmation_state, mark.confirmed_by), ("Confirmed", "RZP3M9WQ2KD"))
        self.assertEqual(mark.confirmed_at, dt.datetime(2026, 9, 16, 19, 42, 11, tzinfo=SUMMER))
        self.assertTrue(mark.is_confirmed)
        self.assertFalse(mark.is_unconfirmed)
        self.assertFalse(mark.is_hypothetical)
        self.assertEqual(mark.numeric_value, 1.0)
        self.assertEqual(mark.raw["Theme"], "Vyjmenovaná slova po B ")

    def test_new_unconfirmed_mark(self):
        mark = self.czech.marks[1]
        self.assertEqual((mark.text, mark.weight, mark.numeric_value), ("3-", 4, 3.5))
        self.assertEqual((mark.confirmation_state, mark.confirmed_at, mark.confirmed_by), ("Unconfirmed", None, ""))
        self.assertTrue(mark.is_new)
        self.assertTrue(mark.is_unconfirmed)
        self.assertFalse(mark.is_confirmed)

    def test_verbal_evaluation_and_invalid_date(self):
        mark = self.czech.marks[2]
        self.assertEqual((mark.caption, mark.theme), ("", "Interpunkce"))
        self.assertEqual(mark.verbal_evaluation, "Pěkná práce,\r\npozor na čárky.")
        self.assertTrue(mark.is_invalid_date)

    def test_point_marks_have_no_weight_and_no_classic_value(self):
        kinematics, lab = self.physics.marks
        self.assertEqual((kinematics.text, kinematics.max_points, kinematics.weight), ("42", 50, None))
        self.assertTrue(kinematics.is_points)
        self.assertEqual((lab.text, lab.max_points), ("5", 20))
        self.assertIsNone(lab.numeric_value)  # 5 points, not the classic mark 5
        self.assertTrue(self.physics.points_only)

    def test_numeric_value_of_classic_and_other_marks(self):
        cases = {"1": 1.0, "1-": 1.5, "2": 2.0, "2-": 2.5, "3": 3.0, "3-": 3.5, "4": 4.0, "4-": 4.5, "5": 5.0,
                 "5-": None, "N": None, "X": None, "?": None, "A": None, "": None, "0": None, "6": None, "1+": None}
        for mark_text, expected in cases.items():
            self.assertEqual(Mark("M1", "1", mark_text).numeric_value, expected, mark_text)
        self.assertIsNone(Mark("M1", "1", "1", is_points=True).numeric_value)
        self.assertEqual(Mark.from_json({"MarkText": " 2- "}).numeric_value, 2.5)
        self.assertIsNone(self.maths.marks[1].numeric_value)  # "N", not graded

    def test_missing_and_null_fields_default(self):
        self.assertEqual(Mark.from_json({"Id": "M1", "MarkText": "2"}), Mark("M1", "", "2"))
        nulls = Mark.from_json(dict.fromkeys(self.czech.marks[0].raw))
        self.assertEqual(nulls, Mark("", "", ""))
        self.assertEqual((nulls.max_points, nulls.weight, nulls.date, nulls.confirmed_at), (0, None, None, None))
        lenient = Mark.from_json({"Weight": "3", "MaxPoints": "x", "IsNew": "true", "MarkDate": "0001-01-01T00:00:00"})
        self.assertEqual((lenient.weight, lenient.max_points, lenient.is_new, lenient.date), (3, 0, True, None))

    def test_what_if_entry(self):
        self.assertEqual([mark.what_if_entry() for mark in self.czech.marks], CZECH_ENTRIES)
        self.assertEqual(self.physics.marks[0].what_if_entry(),
                         {"Id": "JT5R2H.6}K", "MarkText": "42", "Weight": None, "MaxPoints": 50, "SubjectId": "Q7"})
        self.assertIsNone(Mark("", " 4", "1", weight=3).what_if_entry()["Id"])

    def test_equal_marks_compare_and_hash_without_raw(self):
        again = parsed_marks()
        self.assertEqual(again.subjects[0], self.czech)
        self.assertEqual(len({*again.all_marks, *self.czech.marks, *self.physics.marks}), 7)

    def test_format(self):
        self.assertEqual(self.czech.marks[0].format(),
                         "2026-09-14  1       weight 2  Diktát 1: Vyjmenovaná slova po B (diktát)")
        self.assertEqual(self.czech.marks[1].format(),
                         "2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new, unconfirmed]")
        self.assertEqual(self.czech.marks[2].format(), "2026-10-08  2       weight 1  Interpunkce (ústní zkoušení)"
                                                       " - Pěkná práce, pozor na čárky. [unconfirmed]")
        self.assertEqual(self.physics.marks[0].format(),
                         "2026-09-21  42/50             Kinematika: Pohyb rovnoměrný (test)")
        self.assertEqual(Mark("", "1", "").format(), "-           - [hypothetical]")
        self.assertEqual(Mark("M1", "1", "A", verbal_evaluation="Nepsal").format(),
                         "-           A                 Nepsal")

    def test_format_keeps_multi_line_texts_on_one_line(self):
        mark = Mark.from_json({"Id": "M1", "MarkText": "2", "Caption": "Diktát\r\nčást 2",
                               "Theme": "Shoda  podmětu\ns přísudkem ", "TypeNote": "písemná\npráce"})
        self.assertEqual(mark.format(),
                         "-           2                 Diktát část 2: Shoda podmětu s přísudkem (písemná práce)")
        self.assertEqual(len(mark.format().splitlines()), 1)


class SubjectMarksTest(unittest.TestCase):
    def setUp(self):
        self.czech = parsed_marks().subjects[0]

    def test_subject_average_and_flags(self):
        self.assertEqual(self.czech.subject, Item(" 4", "ČJL", "Český jazyk a literatura"))
        self.assertEqual((self.czech.average_text, self.czech.average), ("2,57", 2.57))
        self.assertEqual((self.czech.temporary_mark, self.czech.temporary_mark_note, self.czech.subject_note),
                         ("", "", ""))
        self.assertEqual((self.czech.points_only, self.czech.prediction_enabled), (False, True))
        self.assertEqual(len(self.czech.marks), 3)
        self.assertEqual(self.czech.raw["AverageText"], "2,57 ")

    def test_average_text_variants(self):
        cases = ((None, "", None), ("", "", None), (" ", "", None), ("N ", "N", None), ("1,00 ", "1,00", 1.0),
                 (2, "2", 2.0), ("NaN ", "NaN", None), ("Infinity", "Infinity", None), ("-inf", "-inf", None))
        for value, average_text, average in cases:
            subject = SubjectMarks.from_json({"Subject": {}, "Marks": [], "AverageText": value})
            self.assertEqual((subject.average_text, subject.average), (average_text, average), value)
            json.dumps(subject.to_dict(), allow_nan=False)  # strict JSON: no NaN or Infinity
        missing = SubjectMarks.from_json({"Subject": {"Id": "1"}, "Marks": []})
        self.assertEqual((missing.average_text, missing.average, missing.prediction_enabled), ("", None, False))

    def test_new_and_unconfirmed_marks(self):
        self.assertEqual([mark.id for mark in self.czech.new_marks], ["QX7K0A(2)C"])
        self.assertEqual([mark.id for mark in self.czech.unconfirmed_marks], ["QX7K0A(2)C", "QX7K0B:3/D"])

    def test_contract(self):
        with self.assertRaises(BakalariContractError) as raised:
            SubjectMarks.from_json({"Marks": None})
        self.assertEqual(raised.exception.problems, ["Missing list 'Marks'", "Missing object 'Subject'"])
        lenient = SubjectMarks.from_json({"Marks": None, "Subject": "?"}, validate=False)
        self.assertEqual((lenient.subject, lenient.marks), (Item("", "", ""), ()))
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                SubjectMarks.from_json([], validate=validate)

    def test_format(self):
        self.assertEqual(self.czech.format_summary(), "ČJL Český jazyk a literatura: average 2,57, 3 mark(s)")
        lines = self.czech.format().splitlines()
        self.assertEqual(lines[0], self.czech.format_summary())
        self.assertEqual(lines[1:], ["    " + mark.format() for mark in self.czech.marks])
        bare = SubjectMarks(Item(" 7", "", ""), temporary_mark="2")
        self.assertEqual(bare.format(), "7: average -, 0 mark(s), temporary mark 2")


class MarksTest(unittest.TestCase):
    def setUp(self):
        self.marks = parsed_marks()

    def test_subjects_and_mark_options(self):
        self.assertEqual([subject.subject.abbrev for subject in self.marks.subjects], ["ČJL", "M", "F"])
        self.assertEqual([subject.subject.id for subject in self.marks.subjects], [" 4", "12", "Q7"])
        self.assertEqual(len(self.marks.mark_options), 15)
        self.assertEqual(self.marks.mark_options[9], Item("N", "N", "nehodnocen"))

    def test_mark_collections(self):
        self.assertEqual(len(self.marks.all_marks), 7)
        self.assertEqual(self.marks.all_marks[3].id, "BW2N1E[4]F")
        self.assertEqual([mark.id for mark in self.marks.new_marks], ["QX7K0A(2)C", "JT5R2J=7;L"])
        self.assertEqual([mark.id for mark in self.marks.unconfirmed_marks],
                         ["QX7K0A(2)C", "QX7K0B:3/D", "JT5R2J=7;L"])

    def test_marks_without_a_confirmation_state(self):
        data = load_fixture("marks.json")
        for subject in data["Subjects"]:
            for mark in subject["Marks"]:
                for key in ("MarkConfirmationState", "ConfirmedWhen", "ConfirmedBy"):
                    del mark[key]
        marks = Marks.from_json(data)
        self.assertEqual(marks.unconfirmed_marks, [])
        self.assertFalse(any(mark.is_confirmed for mark in marks.all_marks))

    def test_subject_lookup_by_id_abbreviation_or_name(self):
        cases = {" 4": "ČJL", "4": "ČJL", "čjl": "ČJL", "ČJL ": "ČJL", "český JAZYK a literatura": "ČJL", "12": "M",
                 "m": "M", "Q7": "F", "fyzika": "F"}
        for key, abbrev in cases.items():
            self.assertEqual(self.marks.subject(key).subject.abbrev, abbrev, key)
        self.assertEqual(self.marks.subject(12).subject.abbrev, "M")
        self.assertEqual(self.marks.subject(Item(" 4", "Čj", "Čeština")).subject.abbrev, "ČJL")
        self.assertEqual(self.marks.subject(Item("99", "F", "")).subject.abbrev, "F")
        for missing in ("Dějepis", "", "   ", Item("", "", "")):
            self.assertIsNone(self.marks.subject(missing), missing)

    def test_subject_lookup_prefers_ids(self):
        marks = Marks(subjects=(SubjectMarks(Item("12", "M", "Matematika")), SubjectMarks(Item("7", "12", "Dvanáct"))))
        self.assertEqual(marks.subject("12").subject.name, "Matematika")
        self.assertEqual(marks.subject(" 12").subject.name, "Matematika")
        self.assertEqual(marks.subject("dvanáct").subject.id, "7")

    def test_mark_option(self):
        self.assertEqual(self.marks.mark_option("N").name, "nehodnocen")
        self.assertEqual(self.marks.mark_option(" 1- ").id, "1-")
        self.assertEqual(self.marks.mark_option(self.marks.subjects[1].marks[1]).name, "nehodnocen")
        for missing in ("Z", "", None):
            self.assertIsNone(self.marks.mark_option(missing), missing)
        self.assertIsNone(Marks().mark_option("1"))
        by_abbrev = Marks(mark_options=(Item("10", "1", "výborně"),))
        self.assertEqual(by_abbrev.mark_option("1").name, "výborně")

    def test_to_dict_is_json_serialisable_without_raw(self):
        data = self.marks.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(set(data), {"subjects", "mark_options"})
        self.assertNotIn('"raw"', json.dumps(data))
        subject = data["subjects"][0]
        self.assertEqual(subject["subject"], {"id": " 4", "abbrev": "ČJL", "name": "Český jazyk a literatura"})
        self.assertEqual((subject["average_text"], subject["average"]), ("2,57", 2.57))
        self.assertEqual(subject["marks"][1], {
            "id": "QX7K0A(2)C", "subject_id": " 4", "text": "3-", "caption": "Slohová práce", "theme": "",
            "date": "2026-10-05", "edit_date": "2026-10-06T07:51:00+02:00", "teacher_id": "UQX7K", "type": "H",
            "type_note": "písemná práce", "weight": 4, "is_new": True, "is_points": False, "points_text": "",
            "max_points": 0, "calculated_text": "", "class_rank_text": "", "verbal_evaluation": "",
            "is_invalid_date": False, "confirmation_state": "Unconfirmed", "confirmed_at": None, "confirmed_by": "",
        })
        self.assertEqual(data["mark_options"][0], {"id": "1", "abbrev": "1", "name": "1"})

    def test_lenient_parsing(self):
        data = {
            "Subjects": [
                None,
                "x",
                {"Subject": None, "Marks": None, "AverageText": None},
                {"Subject": {"Id": "5", "Abbrev": "D ", "Name": "Dějepis"},
                 "Marks": [None, {"Id": "D1", "MarkText": "2", "Weight": "3", "IsNew": "true"}]},
            ],
            "MarkOptions": None,
        }
        marks = Marks.from_json(data, validate=False)
        self.assertEqual(len(marks.subjects), 2)
        self.assertEqual((marks.subjects[0].subject, marks.subjects[0].marks), (Item("", "", ""), ()))
        history = marks.subjects[1]
        self.assertEqual((history.subject.abbrev, len(history.marks)), ("D", 1))
        self.assertEqual((history.marks[0].weight, history.marks[0].is_new), (3, True))
        self.assertEqual(marks.mark_options, ())
        self.assertEqual(Marks.from_json({}, validate=False), Marks())

    def test_contract_problems_are_listed(self):
        with self.assertRaises(BakalariContractError) as raised:
            Marks.from_json({"Subjects": [{"Subject": {}, "Marks": []}, {"Marks": {}}, 7], "MarkOptions": []})
        self.assertEqual(raised.exception.problems, [
            "1 entry of 'Subjects' is not a JSON object",
            "Subjects[1]: Missing list 'Marks'",
            "Subjects[1]: Missing object 'Subject'",
        ])
        self.assertIn("The Bakaláři marks response violates its contract", str(raised.exception))
        for payload in ({}, {"Subjects": None}, {"MarkOptions": []}):
            with self.assertRaises(BakalariContractError) as raised:
                Marks.from_json(payload)
            self.assertEqual(raised.exception.problems, ["Missing list 'Subjects'"])
        for payload in ([], None, "marks"):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError) as raised:
                    Marks.from_json(payload, validate=validate)
                self.assertEqual(raised.exception.problems, ["The marks response must be a JSON object"])

    def test_format(self):
        lines = self.marks.format().splitlines()
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[0], "ČJL Český jazyk a literatura: average 2,57, 3 mark(s)")
        self.assertEqual(lines[4], "M Matematika: average 1,50, 2 mark(s)")
        self.assertEqual(lines[6], "    2026-10-01  N       weight 1  Test (test)")
        self.assertEqual(lines[9],
                         "    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new, unconfirmed]")
        self.assertEqual(Marks().format(), "")


class FinalMarksTest(unittest.TestCase):
    def setUp(self):
        self.terms = parse_final_marks(load_fixture("marks_final.json"))

    def test_certificate_terms(self):
        self.assertEqual(len(self.terms), 2)
        term = self.terms[0]
        self.assertEqual((term.school_year, term.semester, term.semester_name), ("2024/25", "2", "2."))
        self.assertEqual((term.grade, term.grade_name, term.year_in_school), (5, "pátý", 5))
        self.assertEqual((term.achievement_text, term.marks_average), ("prospěl s vyznamenáním", 1.33))
        self.assertEqual((term.absent_hours, term.not_excused_hours), (31, 0))
        self.assertEqual(term.certificate_date, dt.date(2025, 6, 27))
        self.assertEqual((term.repeated, term.closed), (False, True))
        self.assertEqual([subject.abbrev for subject in term.subjects], ["Chv", "ČJL", "M"])
        self.assertEqual(self.terms[1].marks_average, 2.0)

    def test_final_marks_resolve_their_subjects(self):
        mark = self.terms[0].final_marks[1]
        self.assertEqual((mark.id, mark.subject_id, mark.text), ("F5Q)2B", " 4", "2"))
        self.assertEqual(mark.subject, Item(" 4", "ČJL", "Český jazyk a literatura"))
        self.assertEqual(mark.date, dt.datetime(2025, 6, 22, 20, 40, tzinfo=SUMMER))
        self.assertEqual(mark.edit_date, dt.datetime(2025, 6, 24, 7, 15, tzinfo=SUMMER))
        self.assertEqual(mark.numeric_value, 2.0)
        self.assertEqual(self.terms[1].final_marks[0].date, dt.datetime(2026, 1, 26, 19, 30, tzinfo=WINTER))
        self.assertEqual([final.subject.abbrev for final in self.terms[1].final_marks], ["Chv", "ČJL", "M"])

    def test_unknown_and_padded_subject_ids(self):
        term = CertificateTerm.from_json({
            "Subjects": [
                {"Id": " 4", "Abbrev": "ČJL", "Name": "Český jazyk a literatura"},
                {"Id": "", "Abbrev": "", "Name": "Bez kódu"},
                None,
            ],
            "FinalMarks": [
                {"Id": "A", "SubjectId": "4", "MarkText": "1"},
                {"Id": "B", "SubjectId": "99", "MarkText": "N"},
                {"Id": "C", "MarkText": "2"},
                "x",
            ],
        })
        padded, unknown, missing = term.final_marks
        self.assertEqual(padded.subject.abbrev, "ČJL")
        self.assertIsNone(unknown.subject)
        self.assertIsNone(unknown.numeric_value)
        self.assertEqual((missing.subject_id, missing.subject), ("", None))
        self.assertIsNone(FinalMark.from_json({"SubjectId": "4"}).subject)

    def test_final_mark_lookup(self):
        term = self.terms[1]
        self.assertEqual(term.final_mark("ČJL").text, "3")
        self.assertEqual(term.final_mark("4").text, "3")
        self.assertEqual(term.final_mark("matematika").text, "2")
        self.assertIsNone(term.final_mark("Fyzika"))
        unresolved = CertificateTerm.from_json({"FinalMarks": [{"Id": "B", "SubjectId": "99", "MarkText": "N"}]})
        self.assertEqual(unresolved.final_mark("99").id, "B")

    def test_missing_optional_fields(self):
        self.assertEqual(CertificateTerm.from_json({}), CertificateTerm("", ""))
        term = CertificateTerm.from_json({"MarksAverage": None, "AbsentHours": None, "Grade": None,
                                          "CertificateDate": "0001-01-01T00:00:00+01:00", "Closed": None})
        self.assertEqual((term.marks_average, term.absent_hours, term.grade, term.certificate_date, term.closed),
                         (None, None, None, None, False))
        self.assertEqual(CertificateTerm.from_json({"MarksAverage": "1,5"}).marks_average, 1.5)

    def test_non_finite_average_is_none(self):
        for payload in ('{"MarksAverage": NaN}', '{"MarksAverage": Infinity}', '{"MarksAverage": "NaN"}'):
            term = CertificateTerm.from_json(json.loads(payload))
            self.assertIsNone(term.marks_average, payload)
            json.dumps(term.to_dict(), allow_nan=False)  # strict JSON: no NaN or Infinity
            self.assertEqual(term.format(), "")

    def test_contract(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_final_marks({"CertificateTerms": [{"FinalMarks": []}, {"Subjects": []}]})
        self.assertEqual(raised.exception.problems, [
            "CertificateTerms[0]: Missing list 'Subjects'", "CertificateTerms[1]: Missing list 'FinalMarks'",
        ])
        with self.assertRaises(BakalariContractError) as raised:
            parse_final_marks({})
        self.assertEqual(raised.exception.problems, ["Missing list 'CertificateTerms'"])
        self.assertEqual(parse_final_marks({"CertificateTerms": []}), [])
        lenient = parse_final_marks({"CertificateTerms": [{"SchoolYear": "2025/26"}, 3]}, validate=False)
        self.assertEqual([term.school_year for term in lenient], ["2025/26"])
        self.assertEqual(parse_final_marks({}, validate=False), [])
        with self.assertRaises(BakalariContractError):
            parse_final_marks([], validate=False)

    def test_to_dict_and_format(self):
        data = [term.to_dict() for term in self.terms]
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data[0]["final_marks"][0], {
            "id": "F5Q(1A", "subject_id": "26", "text": "1",
            "subject": {"id": "26", "abbrev": "Chv", "name": "Chování"},
            "date": "2025-06-23T18:12:00+02:00", "edit_date": "2025-06-23T18:12:00+02:00",
        })
        self.assertEqual((data[0]["certificate_date"], data[0]["marks_average"]), ("2025-06-27", 1.33))
        self.assertEqual(self.terms[1].format().splitlines(), [
            "2025/26 semester 1 (2026-01-29): prospěl, average 2.00, absent 12 h (2 unexcused)",
            "    Chv Chování: 1",
            "    ČJL Český jazyk a literatura: 3",
            "    M Matematika: 2",
        ])
        sparse = CertificateTerm("2025/26", "2", absent_hours=4, final_marks=(FinalMark("X", " 9", ""),))
        self.assertEqual(sparse.format(), "2025/26 semester 2: absent 4 h\n    9: -")
        self.assertEqual(CertificateTerm("2025/26", "1").format(), "2025/26 semester 1")


class PedagogicalMeasuresTest(unittest.TestCase):
    def setUp(self):
        self.measures = parse_pedagogical_measures(load_fixture("marks_measures.json"))

    def test_text_is_decoded_from_html_entities(self):
        praise, warning = self.measures
        self.assertEqual(praise.text, "za reprezentaci školy v matematické olympiádě & ve sběru papíru")
        self.assertEqual((praise.type_id, praise.type_label), ("pTU", "pochvala třídního učitele"))
        self.assertEqual((praise.school_year, praise.semester, praise.date), ("2025/26", "1", dt.date(2025, 12, 18)))
        self.assertEqual(warning.text, "za opakované zapomínání pomůcek")
        self.assertEqual(warning.raw["Text"], "za opakovan&#233; zapom&#237;n&#225;n&#237; pomůcek")

    def test_missing_fields_and_contract(self):
        self.assertEqual(PedagogicalMeasure.from_json({"Text": None}), PedagogicalMeasure(None, "", "", ""))
        self.assertEqual(PedagogicalMeasure.from_json({"Text": " &lt;b&gt; "}).text, "<b>")
        with self.assertRaises(BakalariContractError) as raised:
            parse_pedagogical_measures({"PedagogicalMeasures": [1]})
        self.assertEqual(raised.exception.problems, ["1 entry of 'PedagogicalMeasures' is not a JSON object"])
        lenient = parse_pedagogical_measures({"PedagogicalMeasures": [1, {"TypeId": "x"}]}, validate=False)
        self.assertEqual([measure.type_id for measure in lenient], ["x"])
        self.assertEqual(parse_pedagogical_measures({"PedagogicalMeasures": []}), [])
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                parse_pedagogical_measures(None, validate=validate)

    def test_to_dict_and_format(self):
        data = self.measures[1].to_dict()
        self.assertEqual(data, {"date": "2025-04-07", "type_id": "nTU", "type_label": "napomenutí třídního učitele",
                                "text": "za opakované zapomínání pomůcek", "school_year": "2024/25", "semester": "2"})
        self.assertEqual(self.measures[0].format(), "2025-12-18 pochvala třídního učitele: za reprezentaci školy v "
                                                    "matematické olympiádě & ve sběru papíru (2025/26, semester 1)")
        self.assertEqual(PedagogicalMeasure(None, "pTU", "", "").format(), "- pTU")
        self.assertEqual(PedagogicalMeasure(dt.date(2025, 12, 18), "", "", "za pomoc\r\nspolužákům").format(),
                         "2025-12-18: za pomoc spolužákům")


class MarksEndpointTest(unittest.TestCase):
    def test_marks_is_a_get_without_parameters(self):
        client, transport = logged_in_client(json_response(200, load_fixture("marks.json")))
        marks = client.marks()
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query, call.body), ("GET", "/api/3/marks", {}, None))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(marks, parsed_marks())

    def test_marks_since_sends_from(self):
        client, transport = logged_in_client(*(json_response(200, load_fixture("marks.json")) for _ in range(4)))
        client.marks(since=dt.date(2026, 10, 1))
        client.marks(since=dt.datetime(2026, 10, 1, 23, 30))
        client.marks(since="2026-10-01")
        client.marks(since="")
        self.assertEqual([call.query for call in transport.api_calls], [{"from": "2026-10-01"}] * 3 + [{}])

    def test_every_endpoint_rejects_a_non_json_body(self):
        page = text_response(200, "<html><head><title>Bakaláři</title></head></html>")
        calls = {
            "/api/3/marks": lambda client: client.marks(),
            "/api/3/marks/count-new": lambda client: client.new_marks_count(),
            "/api/3/marks/final": lambda client: client.final_marks(validate=False),
            "/api/3/marks/measures": lambda client: client.pedagogical_measures(validate=False),
            "/api/3/marks/what-if": lambda client: client.what_if(CZECH_ENTRIES, validate=False),
        }
        for path, call in calls.items():
            client, transport = logged_in_client(page)
            with self.assertRaises(BakalariContractError) as raised:
                call(client)
            self.assertIn(f"{path} returned text/html instead of JSON (HTTP 200)", str(raised.exception))
            self.assertEqual(transport.api_calls[0].api_path, path)

    def test_every_endpoint_lets_a_permission_error_propagate(self):
        czech = parsed_marks().subjects[0]
        calls = (
            lambda client: client.marks(),
            lambda client: client.new_marks_count(),
            lambda client: client.final_marks(),
            lambda client: client.pedagogical_measures(),
            lambda client: client.what_if(CZECH_ENTRIES),
            lambda client: client.predict_marks(czech, [("1", 1)]),
            lambda client: client.predict_marks("čjl", [("1", 1)]),
            lambda client: client.confirm_marks(["QX7K0A(2)C"]),
        )
        for call in calls:
            client, transport = logged_in_client(FORBIDDEN)
            with self.assertRaises(BakalariPermissionError) as raised:
                call(client)
            self.assertEqual((raised.exception.status, len(transport.api_calls)), (403, 1))

    def test_marks_contract_is_checked_unless_disabled(self):
        broken = {"Subjects": [{"Subject": {"Id": "1"}}]}
        client, _ = logged_in_client(json_response(200, broken), json_response(200, broken), json_response(200, []))
        with self.assertRaises(BakalariContractError):
            client.marks()
        self.assertEqual(client.marks(validate=False).subjects[0].subject.id, "1")
        with self.assertRaises(BakalariContractError):
            client.marks(validate=False)

    def test_marks_permission_error_propagates(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.marks()

    def test_new_marks_count(self):
        client, transport = logged_in_client(json_response(200, 0), json_response(200, 3), json_response(200, {}))
        self.assertEqual(client.new_marks_count(), 0)
        self.assertEqual(client.new_marks_count(), 3)
        with self.assertRaises(BakalariContractError):
            client.new_marks_count()
        self.assertEqual({(call.method, call.api_path) for call in transport.api_calls},
                         {("GET", "/api/3/marks/count-new")})

    def test_final_marks(self):
        client, transport = logged_in_client(
            json_response(200, load_fixture("marks_final.json")), json_response(200, {"CertificateTerms": []}),
            json_response(200, {"CertificateTerms": None}), json_response(200, {"CertificateTerms": None}),
        )
        self.assertEqual([term.school_year for term in client.final_marks()], ["2024/25", "2025/26"])
        self.assertEqual(client.final_marks(), [])
        with self.assertRaises(BakalariContractError):
            client.final_marks()
        self.assertEqual(client.final_marks(validate=False), [])
        self.assertEqual({(call.method, call.api_path) for call in transport.api_calls},
                         {("GET", "/api/3/marks/final")})

    def test_pedagogical_measures(self):
        client, transport = logged_in_client(
            json_response(200, load_fixture("marks_measures.json")), json_response(200, {"PedagogicalMeasures": []}),
            json_response(200, {}), json_response(200, {}),
        )
        self.assertEqual([measure.type_id for measure in client.pedagogical_measures()], ["pTU", "nTU"])
        self.assertEqual(client.pedagogical_measures(), [])
        with self.assertRaises(BakalariContractError):
            client.pedagogical_measures()
        self.assertEqual(client.pedagogical_measures(validate=False), [])
        self.assertEqual({(call.method, call.api_path) for call in transport.api_calls},
                         {("GET", "/api/3/marks/measures")})

    def test_what_if_posts_the_marks_as_json(self):
        body = CZECH_ENTRIES + [{"Id": None, "MarkText": "1", "Weight": 3, "MaxPoints": 0, "SubjectId": " 4"}]
        client, transport = logged_in_client(json_response(200, load_fixture("marks_what_if.json")))
        result = client.what_if(body)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("POST", "/api/3/marks/what-if", {}))
        self.assertEqual(call.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(call.json, body)
        self.assertEqual((result.subject.abbrev, result.average_text, result.average), ("ČJL", "2,10", 2.1))
        hypothetical = result.marks[-1]
        self.assertTrue(hypothetical.is_hypothetical)
        self.assertEqual((hypothetical.id, hypothetical.caption, hypothetical.teacher_id, hypothetical.type),
                         ("", "", "", ""))
        self.assertEqual((hypothetical.date, hypothetical.weight, hypothetical.confirmation_state),
                         (dt.date(2026, 10, 15), 3, ""))
        self.assertEqual(sum(mark.is_hypothetical for mark in result.marks), 1)

    def test_what_if_response_contract(self):
        client, _ = logged_in_client(json_response(200, {"Message": ""}), json_response(200, {"Message": ""}))
        with self.assertRaises(BakalariContractError):
            client.what_if([])
        self.assertEqual(client.what_if([], validate=False).marks, ())

    def test_what_if_rejects_bad_input_before_sending(self):
        client, transport = logged_in_client()
        for bad in ({"Id": None}, "1", None, 5, [("1", 3)], [None]):
            with self.assertRaises(TypeError):
                client.what_if(bad)
        self.assertEqual(transport.calls, [])

    def test_what_if_is_forbidden_when_prediction_is_disabled(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.what_if(CZECH_ENTRIES)

    def test_predict_marks_from_subject_marks(self):
        czech = parsed_marks().subjects[0]
        client, transport = logged_in_client(json_response(200, load_fixture("marks_what_if.json")))
        result = client.predict_marks(czech, [("1", 3), [" 2- ", 1]])
        self.assertEqual(result.average, 2.1)
        self.assertEqual(len(transport.api_calls), 1)
        self.assertEqual(transport.api_calls[0].json, CZECH_ENTRIES + [
            {"Id": None, "MarkText": "1", "Weight": 3, "MaxPoints": 0, "SubjectId": " 4"},
            {"Id": None, "MarkText": "2-", "Weight": 1, "MaxPoints": 0, "SubjectId": " 4"},
        ])

    def test_predict_marks_by_key_fetches_the_marks(self):
        client, transport = logged_in_client(
            json_response(200, load_fixture("marks.json")), json_response(200, load_fixture("marks_what_if.json"))
        )
        client.predict_marks("čjl", (pair for pair in [("1", 3)]))
        get, post = transport.api_calls
        self.assertEqual((get.method, get.api_path), ("GET", "/api/3/marks"))
        self.assertEqual((post.method, post.api_path), ("POST", "/api/3/marks/what-if"))
        self.assertEqual(post.json, CZECH_ENTRIES + [
            {"Id": None, "MarkText": "1", "Weight": 3, "MaxPoints": 0, "SubjectId": " 4"},
        ])

    def test_predict_marks_with_given_marks_sends_point_marks_unchanged(self):
        client, transport = logged_in_client(json_response(200, load_fixture("marks_what_if.json")))
        client.predict_marks(Item("Q7", "", ""), [("1", 1)], marks=parsed_marks())
        body = transport.api_calls[0].json
        self.assertEqual(len(transport.api_calls), 1)
        self.assertEqual(body[:2], [
            {"Id": "JT5R2H.6}K", "MarkText": "42", "Weight": None, "MaxPoints": 50, "SubjectId": "Q7"},
            {"Id": "JT5R2J=7;L", "MarkText": "5", "Weight": None, "MaxPoints": 20, "SubjectId": "Q7"},
        ])
        self.assertEqual(body[2], {"Id": None, "MarkText": "1", "Weight": 1, "MaxPoints": 0, "SubjectId": "Q7"})

    def test_predict_marks_again_from_a_prediction_result(self):
        previous = SubjectMarks.from_json(load_fixture("marks_what_if.json"))
        client, transport = logged_in_client(json_response(200, load_fixture("marks_what_if.json")))
        client.predict_marks(previous, [])
        self.assertEqual([entry["Id"] for entry in transport.api_calls[0].json],
                         ["QX7K0A{1}B", "QX7K0A(2)C", "QX7K0B:3/D", None])

    def test_predict_marks_falls_back_to_the_marks_subject_id(self):
        subject = SubjectMarks(Item("", "Z", ""), marks=(Mark("Z1", " 8", "2", weight=1),))
        client, transport = logged_in_client(json_response(200, load_fixture("marks_what_if.json")))
        client.predict_marks(subject, [("1", 2)])
        self.assertEqual(transport.api_calls[0].json[-1]["SubjectId"], " 8")

    def test_predict_marks_for_an_unknown_subject(self):
        client, transport = logged_in_client(json_response(200, load_fixture("marks.json")))
        with self.assertRaises(ValueError):
            client.predict_marks("Dějepis", [("1", 1)], marks=parsed_marks())
        self.assertEqual(transport.calls, [])
        with self.assertRaises(ValueError):
            client.predict_marks("Dějepis", [("1", 1)])
        self.assertEqual([call.api_path for call in transport.api_calls], ["/api/3/marks"])

    def test_predict_marks_rejects_bad_hypothetical_marks_before_any_request(self):
        client, transport = logged_in_client()
        for bad in ("1", None, {"1": 3}, [1], [("1",)], [("1", 3, 5)], [("1", "3")], [("1", 2.5)], [("1", True)]):
            with self.assertRaises(TypeError):
                client.predict_marks("čjl", bad)
        for bad in ([("", 3)], [(" ", 3)], [(None, 3)], [(1, 3)]):
            with self.assertRaises(ValueError):
                client.predict_marks("čjl", bad)
        self.assertEqual(transport.calls, [])

    def test_predict_marks_is_forbidden_when_prediction_is_disabled(self):
        maths = parsed_marks().subject("M")
        self.assertFalse(maths.prediction_enabled)
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.predict_marks(maths, [("1", 1)])

    def test_confirm_marks_posts_the_mark_ids(self):
        client, transport = logged_in_client(empty_response(200), empty_response(204))
        self.assertTrue(client.confirm_marks(["QX7K0A(2)C", "QX7K0B:3/D"]))
        self.assertFalse(client.confirm_marks(["QX7K0A(2)C"]))
        first = transport.api_calls[0]
        self.assertEqual((first.method, first.api_path, first.query),
                         ("POST", "/api/3/marks/SetClassificationConfirmation", {}))
        self.assertEqual(first.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(first.json, ["QX7K0A(2)C", "QX7K0B:3/D"])

    def test_confirm_marks_accepts_marks_and_a_single_id_and_drops_duplicates(self):
        marks = parsed_marks()
        client, transport = logged_in_client(empty_response(200), empty_response(200), empty_response(200))
        client.confirm_marks(marks.unconfirmed_marks)
        client.confirm_marks(" 1(x)")
        client.confirm_marks(iter([marks.all_marks[1], "QX7K0A(2)C", marks.all_marks[2]]))
        self.assertEqual([call.json for call in transport.api_calls], [
            ["QX7K0A(2)C", "QX7K0B:3/D", "JT5R2J=7;L"], [" 1(x)"], ["QX7K0A(2)C", "QX7K0B:3/D"],
        ])

    def test_confirm_marks_ignores_the_response_body(self):
        client, _ = logged_in_client(text_response(200, "OK", "text/plain"), json_response(200, None),
                                     text_response(204, ""))
        self.assertTrue(client.confirm_marks(["QX7K0A(2)C"]))
        self.assertTrue(client.confirm_marks(["QX7K0A(2)C"]))
        self.assertFalse(client.confirm_marks(["QX7K0A(2)C"]))

    def test_nothing_to_confirm_sends_no_request(self):
        client, transport = logged_in_client()
        self.assertFalse(client.confirm_marks([]))
        self.assertFalse(client.confirm_marks(Marks().unconfirmed_marks))
        self.assertEqual(transport.calls, [])

    def test_confirm_marks_rejects_invalid_ids(self):
        client, transport = logged_in_client()
        for bad in ([""], ["  "], [None], [3], [Mark("", " 4", "1")]):
            with self.assertRaises(ValueError):
                client.confirm_marks(bad)
        for bad in (None, 3, b"QX7K0A(2)C", {"Id": "QX7K0A(2)C"}):
            with self.assertRaises(TypeError):
                client.confirm_marks(bad)
        self.assertEqual(transport.calls, [])

    def test_confirm_marks_errors_propagate(self):
        client, _ = logged_in_client(FORBIDDEN, json_response(500, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariPermissionError):
            client.confirm_marks(["QX7K0A(2)C"])
        with self.assertRaises(BakalariHTTPError) as raised:
            client.confirm_marks(["QX7K0A(2)C"])
        self.assertEqual((raised.exception.status, raised.exception.message), (500, "An error has occurred."))


if __name__ == "__main__":
    unittest.main()
