import copy
import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError
from bakalari.absence import DAY_COUNTERS, Absence, AbsenceDay, SubjectAbsence

from .support import FORBIDDEN, json_response, load_fixture, logged_in_client, text_response

FIXTURE = "absence.json"


class AbsenceModelTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture(FIXTURE)
        self.absence = Absence.from_json(self.data)

    def test_threshold_is_a_fraction(self):
        self.assertEqual(self.absence.percentage_threshold, 0.25)

    def test_days_keep_the_server_order_and_their_counters(self):
        self.assertEqual(
            [day.date for day in self.absence.days], [dt.date(2026, 9, 14), dt.date(2026, 9, 22), dt.date(2026, 10, 6)]
        )
        day = self.absence.days[1]
        self.assertEqual(
            (day.unsolved, day.ok, day.missed, day.late, day.soon, day.school, day.distance_teaching),
            (2, 0, 1, 1, 0, 0, 0),
        )
        self.assertEqual(day.raw, self.data["Absences"][1])

    def test_day_counts_and_total(self):
        last = self.absence.days[2]
        self.assertEqual(
            last.counts(),
            {"unsolved": 0, "ok": 0, "missed": 0, "late": 0, "soon": 1, "school": 3, "distance_teaching": 1},
        )
        self.assertEqual(tuple(last.counts()), DAY_COUNTERS)
        self.assertEqual([day.total for day in self.absence.days], [5, 4, 5])
        self.assertEqual(AbsenceDay(None).total, 0)

    def test_subjects_keep_the_server_order_and_the_nameless_entry(self):
        names = [subject.subject_name for subject in self.absence.subjects]
        self.assertEqual(names, ["Český jazyk a literatura", "Matematika", "Fyzika", ""])
        physics = self.absence.subjects[2]
        self.assertEqual((physics.lessons_count, physics.base, physics.late, physics.soon), (8, 3, 0, 0))
        self.assertEqual((physics.school, physics.distance_teaching), (1, 1))
        self.assertEqual(physics.raw, self.data["AbsencesPerSubject"][2])
        self.assertTrue(all(subject.percentage_threshold == 0.25 for subject in self.absence.subjects))

    def test_percentage_and_over_threshold(self):
        czech, maths, physics, nameless = self.absence.subjects
        self.assertEqual(czech.percentage, 0.25)
        self.assertTrue(czech.over_threshold)  # reaching the threshold counts
        self.assertAlmostEqual(maths.percentage, 2 / 21)
        self.assertFalse(maths.over_threshold)
        self.assertEqual(physics.percentage, 0.375)
        self.assertTrue(physics.over_threshold)
        self.assertEqual(nameless.percentage, 0.0)
        self.assertFalse(nameless.over_threshold)
        self.assertEqual(self.absence.subjects_over_threshold, [czech, physics])

    def test_percentage_without_lessons_and_unset_thresholds(self):
        self.assertIsNone(SubjectAbsence("Chemie").percentage)
        self.assertFalse(SubjectAbsence("Chemie", percentage_threshold=0.25).over_threshold)
        self.assertFalse(SubjectAbsence("Chemie", lessons_count=4, base=4).over_threshold)
        self.assertFalse(SubjectAbsence("Chemie", lessons_count=4, base=4, percentage_threshold=0.0).over_threshold)
        self.assertTrue(SubjectAbsence("Chemie", lessons_count=4, base=2, percentage_threshold=0.5).over_threshold)
        self.assertFalse(SubjectAbsence("Chemie", lessons_count=4, base=1, percentage_threshold=0.5).over_threshold)

    def test_totals_sum_every_counter_over_the_days(self):
        self.assertEqual(
            self.absence.totals(),
            {"unsolved": 2, "ok": 5, "missed": 1, "late": 1, "soon": 1, "school": 3, "distance_teaching": 1},
        )
        self.assertEqual(Absence(None).totals(), dict.fromkeys(DAY_COUNTERS, 0))

    def test_day_lookup(self):
        self.assertIs(self.absence.day("2026-09-22"), self.absence.days[1])
        self.assertIs(self.absence.day(dt.datetime(2026, 9, 22, 10, 30)), self.absence.days[1])
        self.assertIs(self.absence.day(dt.date(2026, 10, 6)), self.absence.days[2])
        self.assertIsNone(self.absence.day("2026-09-23"))
        with self.assertRaises(ValueError):
            self.absence.day("not-a-date")

    def test_subject_lookup_ignores_case_and_padding(self):
        self.assertIs(self.absence.subject("  matematika "), self.absence.subjects[1])
        self.assertIs(self.absence.subject("ČESKÝ JAZYK A LITERATURA"), self.absence.subjects[0])
        self.assertIs(self.absence.subject(""), self.absence.subjects[3])
        self.assertIsNone(self.absence.subject("Chemie"))

    def test_to_dict_is_json_serialisable_without_raw_or_the_copied_threshold(self):
        data = self.absence.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(set(data), {"percentage_threshold", "days", "subjects"})
        self.assertEqual(data["percentage_threshold"], 0.25)
        self.assertEqual(data["days"][0], {
            "date": "2026-09-14", "unsolved": 0, "ok": 5, "missed": 0, "late": 0, "soon": 0, "school": 0,
            "distance_teaching": 0,
        })
        self.assertEqual(data["subjects"][0], {
            "subject_name": "Český jazyk a literatura", "lessons_count": 20, "base": 5, "late": 1, "soon": 0,
            "school": 0, "distance_teaching": 0,
        })

    def test_repr_and_equality_leave_out_raw_and_the_copied_threshold(self):
        self.assertNotIn("raw", repr(self.absence))
        self.assertNotIn("percentage_threshold", repr(self.absence.subjects[0]))
        self.assertEqual(self.absence.subjects[1], SubjectAbsence("Matematika", 21, 2, 0, 1, 0, 0))
        self.assertEqual(Absence.from_json(copy.deepcopy(self.data)), self.absence)


class AbsenceLenientParsingTest(unittest.TestCase):
    def test_padding_nulls_numeric_strings_and_missing_fields(self):
        data = {
            "PercentageThreshold": "0,3",
            "Absences": [
                {"Date": "2026-09-14T00:00:00+02:00", "Ok": "3", "Missed": None, "Late": 1.0},
                {"Date": "0001-01-01T00:00:00+01:00", "Unsolved": "x"},
                {},
            ],
            "AbsencesPerSubject": [
                {"SubjectName": " Dějepis ", "LessonsCount": "10", "Base": 3},
                {"SubjectName": None, "LessonsCount": None},
            ],
        }
        absence = Absence.from_json(data)
        self.assertEqual(absence.percentage_threshold, 0.3)
        first, minimum, empty = absence.days
        self.assertEqual(first.date, dt.date(2026, 9, 14))
        self.assertEqual((first.ok, first.missed, first.late, first.total), (3, 0, 1, 4))
        self.assertEqual((minimum.date, minimum.unsolved), (None, 0))
        self.assertEqual(empty, AbsenceDay(None))
        history, unnamed = absence.subjects
        self.assertEqual((history.subject_name, history.lessons_count, history.base), ("Dějepis", 10, 3))
        self.assertTrue(history.over_threshold)
        self.assertEqual((unnamed.subject_name, unnamed.lessons_count, unnamed.percentage), ("", 0, None))

    def test_missing_threshold_disables_the_threshold_check(self):
        data = load_fixture(FIXTURE)
        del data["PercentageThreshold"]
        absence = Absence.from_json(data)
        self.assertIsNone(absence.percentage_threshold)
        self.assertEqual(absence.subjects[0].percentage, 0.25)
        self.assertEqual(absence.subjects_over_threshold, [])

    def test_without_validation_missing_lists_stay_empty_and_bad_entries_are_skipped(self):
        absence = Absence.from_json({"PercentageThreshold": 0.25, "Absences": None}, validate=False)
        self.assertEqual((absence.percentage_threshold, absence.days, absence.subjects), (0.25, (), ()))
        data = load_fixture(FIXTURE)
        data["Absences"].insert(0, "not an object")
        data["AbsencesPerSubject"].append(None)
        absence = Absence.from_json(data, validate=False)
        self.assertEqual((len(absence.days), len(absence.subjects)), (3, 4))


class AbsenceContractTest(unittest.TestCase):
    def test_valid_fixture_passes(self):
        self.assertEqual(len(Absence.from_json(load_fixture(FIXTURE)).days), 3)

    def test_empty_lists_pass(self):
        # Without the ShowAbsencePercentage right the server sends an empty AbsencesPerSubject list.
        data = load_fixture(FIXTURE)
        data["AbsencesPerSubject"] = []
        absence = Absence.from_json(data)
        self.assertEqual((len(absence.days), absence.subjects, absence.subjects_over_threshold), (3, (), []))
        empty = Absence.from_json({"PercentageThreshold": 0.25, "Absences": [], "AbsencesPerSubject": []})
        self.assertEqual(empty, Absence(0.25))
        self.assertEqual(empty.totals(), dict.fromkeys(DAY_COUNTERS, 0))

    def test_missing_lists_are_listed(self):
        with self.assertRaises(BakalariContractError) as raised:
            Absence.from_json({"PercentageThreshold": 0.25})
        self.assertEqual(raised.exception.problems, ["Missing list 'Absences'", "Missing list 'AbsencesPerSubject'"])
        self.assertIn("The Bakaláři absence violates its contract", str(raised.exception))

    def test_entries_must_be_objects(self):
        data = load_fixture(FIXTURE)
        data["Absences"].append(None)
        with self.assertRaises(BakalariContractError) as raised:
            Absence.from_json(data)
        self.assertEqual(raised.exception.problems, ["1 entry of 'Absences' is not a JSON object"])

    def test_non_object_payload_is_an_error_even_without_validation(self):
        for payload in ([], None, "absence", 3):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError):
                    Absence.from_json(payload, validate=validate)


class AbsenceEndpointTest(unittest.TestCase):
    def test_absence_gets_the_student_absence(self):
        client, transport = logged_in_client(json_response(200, load_fixture(FIXTURE)))
        absence = client.absence()
        login, call = transport.calls
        self.assertTrue(login.path.endswith("/api/login"))
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/absence/student", {}))
        self.assertIsNone(call.body)
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(absence, Absence.from_json(load_fixture(FIXTURE)))

    def test_validation_can_be_disabled(self):
        partial = {"PercentageThreshold": 0.25, "Absences": []}
        client, _ = logged_in_client(json_response(200, partial), json_response(200, partial))
        with self.assertRaises(BakalariContractError):
            client.absence()
        absence = client.absence(validate=False)
        self.assertEqual((absence.percentage_threshold, absence.subjects), (0.25, ()))

    def test_missing_module_raises_permission_error(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError) as raised:
            client.absence()
        self.assertEqual(raised.exception.path, "/api/3/absence/student")

    def test_server_error_and_non_json_answers_are_not_swallowed(self):
        client, _ = logged_in_client(
            json_response(500, {"Message": "An error has occurred."}), text_response(200, "<html>login</html>")
        )
        with self.assertRaises(BakalariHTTPError) as raised:
            client.absence()
        self.assertEqual(raised.exception.status, 500)
        with self.assertRaises(BakalariContractError):
            client.absence()


if __name__ == "__main__":
    unittest.main()
