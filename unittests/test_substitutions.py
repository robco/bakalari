import dataclasses
import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError, timetable
from bakalari.models import Model
from bakalari.substitutions import Change, ChangeLessonInfo, Substitutions
from bakalari.timetable import CHANGE_TYPES

from .support import FORBIDDEN, empty_response, json_response, load_fixture, logged_in_client, text_response

NEWER_KEYS = ("ChangeDisplayType", "AtomType", "ChangeLessonInfo", "BeginTime", "EndTime", "Start", "Duration")
FROM, TO = "2026-10-12T00:00:00+02:00", "2026-10-26T00:00:00+02:00"
ABSENCE_LINE = "1. hod (8:00 - 8:45) Absence: Třídnická hodina: Horáková Eva"
SUBSTITUTION_LINE = "2026-10-14 3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel"


class SubstitutionsModelTest(unittest.TestCase):
    def setUp(self):
        self.substitutions = Substitutions.from_json(load_fixture("substitutions.json"))

    def test_period_and_changes_in_server_order(self):
        self.assertEqual(self.substitutions.start, dt.date(2026, 10, 12))
        self.assertEqual(self.substitutions.end, dt.date(2026, 10, 26))
        self.assertEqual(
            [change.change_type for change in self.substitutions.changes],
            ["Absence", "Substitution", "RoomChanged", "Canceled", "Removed", "Added"],
        )
        self.assertEqual(set(CHANGE_TYPES), {change.change_type for change in self.substitutions.changes})
        self.assertIs(Change, timetable.Change)
        self.assertIsInstance(self.substitutions, Model)

    def test_event_without_lesson_info(self):
        absence = self.substitutions.changes[0]
        self.assertEqual(absence.day, dt.date(2026, 10, 12))
        self.assertEqual((absence.hours, absence.time, absence.begin_time, absence.end_time),
                         ("1. hod", "8:00 - 8:45", "8:00", "8:45"))
        self.assertEqual((absence.type_abbrev, absence.type_name), ("Tříd", "Třídnická hodina"))
        self.assertEqual((absence.display_type, absence.atom_type, absence.change_subject),
                         ("OriginalTeacher", "Hour", ""))
        self.assertIsNone(absence.lesson_info)
        self.assertEqual((absence.start, absence.duration), (None, None))  # the list sends 0 and 0 for "not set"
        self.assertEqual(absence.raw["Start"], 0)

    def test_substitution_names_the_lesson(self):
        substitution = self.substitutions.changes[1]
        self.assertEqual((substitution.description, substitution.display_type),
                         ("Suplování: Veselý Karel", "SubstituteTeacher"))
        self.assertEqual((substitution.type_abbrev, substitution.type_name), ("", ""))
        self.assertEqual(substitution.lesson_info, ChangeLessonInfo(
            class_abbrev="1.B", group_abbrev="1.B", is_class_group=True, subject_abbrev="F", room_abbrev="031"
        ))
        room_change = self.substitutions.changes[2].lesson_info
        self.assertEqual((room_change.group_abbrev, room_change.is_class_group, str(room_change)),
                         ("AjS2", False, "AjS2, Aj, 105"))

    def test_multi_hour_cancellation_and_empty_texts(self):
        canceled, removed = self.substitutions.changes[3:5]
        self.assertEqual((canceled.hours, canceled.time, canceled.description),
                         ("1. - 3. hod", "8:00 - 10:45", "Exkurze"))
        self.assertEqual((removed.description, removed.type_name, removed.type_abbrev), ("", "", ""))

    def test_dates_on_and_by_day(self):
        self.assertEqual(self.substitutions.dates, [
            dt.date(2026, 10, 12), dt.date(2026, 10, 14), dt.date(2026, 10, 16), dt.date(2026, 10, 20),
            dt.date(2026, 10, 21),
        ])
        for day in (dt.date(2026, 10, 14), dt.datetime(2026, 10, 14, 7, 30), "2026-10-14"):
            self.assertEqual([change.hours for change in self.substitutions.on(day)], ["3. hod", "4. hod"])
        self.assertEqual(self.substitutions.on("2026-10-13"), [])
        by_day = self.substitutions.by_day()
        self.assertEqual(list(by_day), self.substitutions.dates)
        self.assertEqual(len(by_day[dt.date(2026, 10, 14)]), 2)

    def test_format_has_one_line_per_change(self):
        lines = self.substitutions.format().splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "2026-10-12 " + ABSENCE_LINE)
        self.assertEqual(lines[1], SUBSTITUTION_LINE + " | 1.B, F, 031")
        self.assertEqual(lines[4], "2026-10-20 6. hod (12:45 - 13:30) Removed | Dív, Tv, 102")

    def test_to_dict_round_trips_through_json_without_raw(self):
        data = self.substitutions.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(list(data), ["start", "end", "changes"])
        self.assertEqual((data["start"], data["end"]), ("2026-10-12", "2026-10-26"))
        substitution = data["changes"][1]
        self.assertEqual((substitution["day"], substitution["begin_time"], substitution["start"]),
                         ("2026-10-14", "10:00", None))
        self.assertEqual(substitution["lesson_info"]["subject_abbrev"], "F")
        self.assertIsNone(data["changes"][0]["lesson_info"])
        self.assertNotIn("raw", substitution)

    def test_models_are_frozen_and_compare_without_raw(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.substitutions.start = None
        self.assertEqual(Substitutions.from_json(load_fixture("substitutions.json")), self.substitutions)
        change = self.substitutions.changes[1]
        self.assertEqual(dataclasses.replace(change, raw={}), change)
        self.assertEqual(len(set(self.substitutions.changes)), 6)


class OlderShapesTest(unittest.TestCase):
    def test_documented_entries_without_the_newer_keys(self):
        data = load_fixture("substitutions.json")
        for change in data["Changes"]:
            for key in NEWER_KEYS:
                del change[key]
        substitution = Substitutions.from_json(data).changes[1]
        self.assertEqual((substitution.change_type, substitution.day, substitution.time),
                         ("Substitution", dt.date(2026, 10, 14), "10:00 - 10:45"))
        self.assertEqual((substitution.display_type, substitution.atom_type, substitution.begin_time), ("", "", ""))
        self.assertEqual((substitution.lesson_info, substitution.start, substitution.duration), (None, None, None))
        self.assertEqual(substitution.format(), SUBSTITUTION_LINE)

    def test_padding_is_trimmed(self):
        data = load_fixture("substitutions.json")
        data["Changes"][1].update(Hours="3. hod ", Description="Suplování: Veselý Karel ", TypeAbbrev=" Sup")
        data["Changes"][1]["ChangeLessonInfo"].update(GroupAbbrev="1.B ", RoomAbbrev=" 031")
        change = Substitutions.from_json(data).changes[1]
        self.assertEqual((change.hours, change.description, change.type_abbrev),
                         ("3. hod", "Suplování: Veselý Karel", "Sup"))
        self.assertEqual((change.lesson_info.group_abbrev, change.lesson_info.room_abbrev), ("1.B", "031"))

    def test_without_a_time_range_the_begin_and_end_times_are_shown(self):
        data = load_fixture("substitutions.json")
        data["Changes"][0]["Time"] = None
        self.assertEqual(Substitutions.from_json(data).changes[0].format(with_date=False),
                         ABSENCE_LINE.replace("8:00 - 8:45", "8:00-8:45"))

    def test_no_changes(self):
        substitutions = Substitutions.from_json({"From": FROM, "To": TO, "Changes": []})
        self.assertEqual((substitutions.changes, substitutions.dates, substitutions.format()), ((), [], ""))
        self.assertEqual(substitutions.by_day(), {})


class ContractTest(unittest.TestCase):
    def test_payload_must_be_an_object_even_without_validation(self):
        for payload in ([], None, "Changes"):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError):
                    Substitutions.from_json(payload, validate=validate)

    def test_changes_must_be_a_list_of_objects(self):
        data = load_fixture("substitutions.json")
        del data["Changes"]
        with self.assertRaises(BakalariContractError) as raised:
            Substitutions.from_json(data)
        self.assertEqual(raised.exception.problems, ["Missing list 'Changes'"])
        self.assertIn("substitutions", str(raised.exception))
        lenient = Substitutions.from_json(data, validate=False)
        self.assertEqual((lenient.start, lenient.changes), (dt.date(2026, 10, 12), ()))

    def test_entries_that_are_not_objects(self):
        data = load_fixture("substitutions.json")
        data["Changes"][2:2] = [None, "Suplování"]
        with self.assertRaises(BakalariContractError) as raised:
            Substitutions.from_json(data)
        self.assertEqual(raised.exception.problems, ["2 entries of 'Changes' are not JSON objects"])
        self.assertEqual(len(Substitutions.from_json(data, validate=False).changes), 6)

    def test_unparseable_dates_become_none(self):
        data = load_fixture("substitutions.json")
        data.update(From="0001-01-01T00:00:00", To=None)
        data["Changes"][0]["Day"] = "12. 10. 2026"
        substitutions = Substitutions.from_json(data)
        self.assertEqual((substitutions.start, substitutions.end, substitutions.changes[0].day), (None, None, None))
        self.assertNotIn(None, substitutions.dates)
        self.assertEqual(substitutions.changes[0].format(), ABSENCE_LINE)


class SubstitutionsEndpointTest(unittest.TestCase):
    def test_default_period_sends_no_from_parameter(self):
        client, transport = logged_in_client(json_response(200, load_fixture("substitutions.json")))
        substitutions = client.substitutions()
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/substitutions", {}))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertIsNone(call.body)
        self.assertEqual(len(substitutions.changes), 6)

    def test_since_accepts_dates_datetimes_and_iso_strings(self):
        payload = json_response(200, load_fixture("substitutions.json"))
        client, transport = logged_in_client(payload, payload, payload)
        client.substitutions(dt.date(2026, 10, 15))
        client.substitutions(dt.datetime(2026, 10, 15, 18, 0))
        client.substitutions(since="2026-10-15")
        self.assertEqual([call.query for call in transport.api_calls], [{"from": "2026-10-15"}] * 3)

    def test_validation_can_be_disabled(self):
        broken = {"From": FROM, "To": TO, "Changes": None}
        client, _ = logged_in_client(json_response(200, broken), json_response(200, broken))
        with self.assertRaises(BakalariContractError):
            client.substitutions()
        self.assertEqual(client.substitutions(validate=False).changes, ())

    def test_disabled_module_and_invalid_date(self):
        model_state = {"$type": "HttpError",
                       "from": {"$type": "String[]", "$values": ["The value 'x' is not valid for Nullable`1."]}}
        invalid = json_response(400, {"Message": "The request is invalid.", "ModelState": model_state})
        client, _ = logged_in_client(FORBIDDEN, invalid)
        with self.assertRaises(BakalariPermissionError):
            client.substitutions()
        with self.assertRaises(BakalariHTTPError) as raised:
            client.substitutions("x")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("from", raised.exception.body["ModelState"])

    def test_bodies_that_are_not_a_json_object(self):
        client, _ = logged_in_client(text_response(200, "<html>Přihlášení</html>"), empty_response(200),
                                     json_response(200, []))
        for _ in range(3):
            with self.assertRaises(BakalariContractError):
                client.substitutions(validate=False)


if __name__ == "__main__":
    unittest.main()
