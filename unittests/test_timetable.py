import copy
import dataclasses
import datetime as dt
import json
import unittest

from bakalari import (
    BakalariContractError,
    BakalariNotFoundError,
    BakalariPermissionError,
    Timetable,
    TimetableContractError,
    contract_problems,
    to_date,
    week_of,
)
from bakalari.models import Item, Model
from bakalari.timetable import (
    CHANGE_TYPES,
    DAY_TYPES,
    Change,
    ChangeLessonInfo,
    Hour,
    LessonHomework,
)

from .support import FORBIDDEN, empty_response, json_response, load_fixture, logged_in_client, text_response

ACTUAL = json_response(200, load_fixture("actual.json"))
PERMANENT = json_response(200, load_fixture("permanent.json"))
CLASS = json_response(200, load_fixture("timetable_class.json"))
NOT_FOUND = text_response(404, "<html><head><title>404 - Soubor nebo adresář nebyl nalezen.</title></head></html>")

LESSON_KEYS = [
    "date", "day_of_week", "hour", "begin", "end", "subject_abbrev", "subject", "teacher_abbrev", "teacher", "room",
    "room_name", "groups", "cycles", "theme", "changed", "change_type", "change_description",
]
NEW_LESSON_KEYS = ["notice", "week_theme", "homeworks"]


class DateHelpersTest(unittest.TestCase):
    def test_to_date_accepts_dates_datetimes_and_iso_strings(self):
        self.assertEqual(to_date(dt.date(2026, 10, 12)), dt.date(2026, 10, 12))
        self.assertEqual(to_date(dt.datetime(2026, 10, 12, 9, 30)), dt.date(2026, 10, 12))
        self.assertEqual(to_date("2026-10-12"), dt.date(2026, 10, 12))
        self.assertEqual(to_date("2026-10-12T00:00:00+02:00"), dt.date(2026, 10, 12))
        with self.assertRaises(ValueError):
            to_date("not-a-date")
        with self.assertRaises(TypeError):
            to_date(20261012)

    def test_week_of_returns_monday_and_sunday(self):
        self.assertEqual(week_of("2026-10-15"), (dt.date(2026, 10, 12), dt.date(2026, 10, 18)))
        self.assertEqual(week_of("2026-10-18"), (dt.date(2026, 10, 12), dt.date(2026, 10, 18)))
        self.assertEqual(week_of("2026-10-12"), (dt.date(2026, 10, 12), dt.date(2026, 10, 18)))


class ActualTimetableTest(unittest.TestCase):
    def setUp(self):
        self.timetable = Timetable.from_json(load_fixture("actual.json"))

    def test_days_keep_type_description_and_order(self):
        self.assertEqual(self.timetable.dates, [dt.date(2026, 10, 12), dt.date(2026, 10, 13), dt.date(2026, 10, 14)])
        holiday = self.timetable.days[2]
        self.assertEqual(
            (holiday.day_type, holiday.description, holiday.lessons), ("Holiday", "podzimní prázdniny", ())
        )
        self.assertFalse(holiday.is_work_day)
        self.assertEqual(holiday.format_summary(), "2026-10-14 st Holiday (podzimní prázdniny): 0 lesson(s)")

    def test_lesson_ids_resolve_including_space_padded_ids(self):
        lesson = self.timetable.lessons_on("2026-10-12")[1]
        self.assertEqual(lesson.subject.name, "Český jazyk a literatura")
        self.assertEqual(lesson.subject.id, " 2")
        self.assertEqual(lesson.teacher.name, "Mgr. Jana Nováková")
        self.assertEqual(lesson.room.abbrev, "205")
        self.assertEqual([group.abbrev for group in lesson.groups], ["1.A Chl"])
        self.assertEqual([cycle.abbrev for cycle in lesson.cycles], ["S"])
        self.assertEqual((lesson.hour.caption, lesson.hour.begin, lesson.hour.end), ("2", "8:55", "9:40"))
        self.assertEqual(lesson.theme, "Vyjmenovaná slova")
        self.assertTrue(lesson.is_taught)
        self.assertFalse(lesson.changed)

    def test_event_replacing_a_lesson_has_only_its_change(self):
        event = self.timetable.lessons_on("2026-10-12")[0]
        self.assertFalse(event.is_taught)
        self.assertIsNone(event.teacher)
        self.assertEqual(event.change.change_type, "Absence")
        self.assertEqual(event.change.description, "Třídnická hodina: Nováková Jana")
        self.assertEqual(event.title, "Třídnická hodina")
        self.assertEqual(
            event.format(),
            "2026-10-12  1.  8:00-8:45  Třídnická hodina | 1.A [Absence: Třídnická hodina: Nováková Jana]",
        )

    def test_changed_lesson_keeps_subject_and_change(self):
        lesson = self.timetable.lessons_on(dt.date(2026, 10, 13))[0]
        self.assertEqual(lesson.subject.abbrev, "M")
        self.assertEqual(lesson.change.change_type, "RoomChanged")
        self.assertEqual(self.timetable.changed_lessons, [self.timetable.lessons[0], lesson])

    def test_lesson_collections(self):
        self.assertEqual(len(self.timetable.lessons), 3)
        self.assertEqual(len(self.timetable.taught_lessons), 2)
        self.assertEqual(self.timetable.lessons_on("2026-10-16"), [])
        self.assertIsNone(self.timetable.day("2026-10-16"))

    def test_covers_week_of(self):
        self.assertTrue(self.timetable.covers_week_of("2026-10-15"))
        self.assertTrue(self.timetable.covers_week_of("2026-10-18"))  # a weekend date belongs to its own week
        self.assertFalse(self.timetable.covers_week_of("2026-10-19"))

    def test_to_dict_is_flat_and_json_serialisable(self):
        data = self.timetable.to_dict()
        json.dumps(data, ensure_ascii=False)
        self.assertEqual(data["days"][0]["lessons"][1], {
            "date": "2026-10-12", "day_of_week": 1, "hour": "2", "begin": "8:55", "end": "9:40",
            "subject_abbrev": "Čj", "subject": "Český jazyk a literatura", "teacher_abbrev": "Nov",
            "teacher": "Mgr. Jana Nováková", "room": "205", "room_name": "Učebna 205", "groups": "1.A Chl",
            "cycles": "S", "theme": "Vyjmenovaná slova", "changed": False, "change_type": "", "change_description": "",
            "notice": "", "week_theme": "", "homeworks": "",
        })
        event = data["days"][0]["lessons"][0]
        self.assertEqual((event["subject"], event["teacher"], event["changed"]), ("", "", True))

    def test_format_groups_lessons_by_day(self):
        lines = self.timetable.format().splitlines()
        self.assertEqual(lines[0], "2026-10-12 po WorkDay: 2 lesson(s)")
        self.assertEqual(lines[2], "     2.  8:55-9:40  Český jazyk a literatura | Mgr. Jana Nováková | 205 | 1.A Chl")
        self.assertEqual(lines[-1], "2026-10-14 st Holiday (podzimní prázdniny): 0 lesson(s)")


class PermanentTimetableTest(unittest.TestCase):
    def test_every_lesson_is_taught_with_teacher_room_and_cycles(self):
        timetable = Timetable.from_json(load_fixture("permanent.json"))
        self.assertEqual(len(timetable.taught_lessons), 3)
        self.assertTrue(all(lesson.teacher and lesson.room for lesson in timetable.taught_lessons))
        self.assertEqual([cycle.name for cycle in timetable.lessons[0].cycles], ["První", "Druhý"])

    def test_last_lesson_in_a_room_is_marked(self):
        timetable = Timetable.from_json(load_fixture("permanent.json"))
        self.assertEqual([lesson.is_last_room_lesson for lesson in timetable.lessons], [False, True, False])


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture("actual.json")

    def test_valid_fixtures_have_no_problems(self):
        self.assertEqual(contract_problems(self.data), [])
        self.assertEqual(contract_problems(load_fixture("permanent.json")), [])
        self.assertEqual(contract_problems(load_fixture("timetable_class.json")), [])
        self.assertEqual(contract_problems(load_fixture("timetable_holiday.json")), [])

    def test_non_object_and_missing_lists(self):
        self.assertEqual(contract_problems([]), ["The timetable must be a JSON object"])
        del self.data["Rooms"]
        self.assertEqual(contract_problems(self.data), ["Missing list 'Rooms'"])

    def test_hour_and_day_fields(self):
        del self.data["Hours"][0]["EndTime"]
        del self.data["Days"][2]["DayType"]
        problems = contract_problems(self.data)
        self.assertIn("Hour slot 2 lacks EndTime", problems)
        self.assertIn("Day '2026-10-14T00:00:00+02:00' lacks DayType", problems)

    def test_no_hour_slots(self):
        self.data["Hours"] = []
        self.data["Days"] = []
        self.assertEqual(contract_problems(self.data), ["No hour slots are defined"])

    def test_dangling_references_are_listed(self):
        atom = self.data["Days"][0]["Atoms"][1]
        atom.update(TeacherId="T9", HourId=99, GroupIds=["G1", "G9"], CycleIds=["7"])
        problems = contract_problems(self.data)
        self.assertEqual(sorted(problems), sorted([
            "2026-10-12: HourId 99 is not defined in Hours",
            "2026-10-12: TeacherId 'T9' is not defined in Teachers",
            "2026-10-12: GroupIds entry 'G9' is not defined in Groups",
            "2026-10-12: CycleIds entry '7' is not defined in Cycles",
        ]))
        with self.assertRaises(TimetableContractError) as raised:
            Timetable.from_json(self.data)
        self.assertEqual(len(raised.exception.problems), 4)

    def test_lenient_parse_resolves_unknown_references_to_none(self):
        data = copy.deepcopy(self.data)
        data["Days"][0]["Atoms"][1].update(TeacherId="T9", HourId=99, GroupIds=["G9"])
        lesson = Timetable.from_json(data, validate=False).lessons[1]
        self.assertIsNone(lesson.teacher)
        self.assertEqual(lesson.groups, ())
        self.assertEqual((lesson.hour.id, lesson.hour.caption), (99, ""))
        with self.assertRaises(TimetableContractError):
            Timetable.from_json([], validate=False)

    def test_a_day_without_a_valid_date(self):
        self.data["Days"][1]["Date"] = "13. 10. 2026"
        self.assertEqual(contract_problems(self.data), ["Day '13. 10. 2026' has no valid Date"])
        with self.assertRaises(TimetableContractError):
            Timetable.from_json(self.data)
        self.assertEqual(Timetable.from_json(self.data, validate=False).dates,
                         [dt.date(2026, 10, 12), dt.date(2026, 10, 14)])  # the day that cannot be placed is skipped
        self.data["Days"][1]["Date"] = None
        self.assertEqual(contract_problems(self.data), ["Day None has no valid Date"])
        self.assertEqual(len(Timetable.from_json(self.data, validate=False).days), 2)
        del self.data["Days"][1]["Date"]
        self.assertEqual(contract_problems(self.data), ["Day None lacks Date"])

    def test_reference_lists_must_be_lists(self):
        self.data["Days"][0]["Atoms"][1]["GroupIds"] = "G2"
        self.assertEqual(contract_problems(self.data), ["2026-10-12: GroupIds is not a list"])
        self.assertEqual(Timetable.from_json(self.data, validate=False).lessons[1].groups, ())

    def test_nested_values_that_lenient_parsing_would_drop_are_reported(self):
        first, second = self.data["Days"][0]["Atoms"]
        first.update(Change=[first["Change"]], Homeworks=["Úkol"])  # e.g. several changes per lesson
        second.update(Homeworks={"Id": "HW1", "Text": "Úkol"}, HomeworkIds="HW1")
        self.data["Days"][1]["Atoms"] = {"Atoms": self.data["Days"][1]["Atoms"]}
        problems = contract_problems(self.data)
        self.assertEqual(problems, [
            "2026-10-12: Change is not a JSON object",
            "2026-10-12: a homework of Homeworks is not a JSON object",
            "2026-10-12: HomeworkIds is not a list",
            "2026-10-12: Homeworks is not a list",
            "2026-10-13: Atoms is not a list",
        ])
        self.assertNotIn("Nováková", "".join(problems))  # values with names are not quoted
        with self.assertRaises(TimetableContractError):
            Timetable.from_json(self.data)
        lenient = Timetable.from_json(self.data, validate=False)
        event, lesson = lenient.lessons_on("2026-10-12")
        self.assertEqual((event.change, event.homeworks, lesson.homeworks, lesson.homework_ids), (None, (), (), ()))
        self.assertEqual(lenient.lessons_on("2026-10-13"), [])

    def test_null_nested_values_are_accepted(self):
        self.data["Days"][0]["Atoms"][1].update(Homeworks=None, HomeworkIds=None, Change=None)
        self.data["Days"][2]["Atoms"] = None
        self.assertEqual(contract_problems(self.data), [])
        timetable = Timetable.from_json(self.data)
        self.assertEqual((timetable.lessons[1].homeworks, timetable.days[2].lessons), ((), ()))

    def test_lists_and_objects_are_never_ids(self):
        atom = self.data["Days"][0]["Atoms"][1]
        atom.update(SubjectId=[" 2"], CycleIds=[{"Id": "5"}])
        self.data["Rooms"].append({"Id": ["R3"], "Abbrev": "306", "Name": "Učebna 306"})
        self.assertEqual(sorted(contract_problems(self.data)), [
            "2026-10-12: CycleIds entry {'Id': '5'} is not defined in Cycles",
            "2026-10-12: SubjectId [' 2'] is not defined in Subjects",
        ])
        timetable = Timetable.from_json(self.data, validate=False)
        self.assertEqual((timetable.lessons[1].subject, timetable.lessons[1].cycles), (None, ()))
        self.assertEqual(list(timetable.rooms), ["R1", "R2"])


class HourTest(unittest.TestCase):
    def test_live_hours_carry_start_and_duration(self):
        hour = Timetable.from_json(load_fixture("actual.json")).hours[0]
        self.assertEqual(hour, Hour(id=2, caption="0", begin="7:10", end="7:55", start=430, duration=45))
        self.assertIsInstance(hour, Model)
        self.assertEqual(
            hour.to_dict(), {"id": 2, "caption": "0", "begin": "7:10", "end": "7:55", "start": 430, "duration": 45}
        )

    def test_documented_hours_without_start_and_duration(self):
        hour = Hour.from_json({"Id": 12, "Caption": "10", "BeginTime": "16:10", "EndTime": "16:55"})
        self.assertEqual((hour.id, hour.caption, hour.begin, hour.end), (12, "10", "16:10", "16:55"))
        self.assertEqual((hour.start, hour.duration), (None, None))

    def test_lenient_hour_values(self):
        hour = Hour.from_json({"Id": "5", "Caption": 0, "BeginTime": " 8:00 ", "EndTime": None, "Start": "480"})
        self.assertEqual(hour, Hour(id=5, caption="0", begin="8:00", end="", start=480))
        self.assertEqual(Hour.from_json({}), Hour(id=0, caption="", begin="", end=""))


class ChangeTest(unittest.TestCase):
    def setUp(self):
        self.timetable = Timetable.from_json(load_fixture("actual.json"))

    def test_live_timetable_change(self):
        change = self.timetable.lessons[0].change
        self.assertEqual(change.day, dt.date(2026, 10, 12))
        self.assertEqual((change.hours, change.time), ("1. hod", "8:00 - 8:45"))
        self.assertEqual((change.display_type, change.atom_type), ("OriginalTeacher", "Hour"))
        self.assertEqual((change.type_abbrev, change.type_name), ("Tříd", "Třídnická hodina"))
        self.assertEqual((change.change_subject, change.begin_time, change.end_time), ("", "", ""))
        self.assertIsNone(change.lesson_info)
        self.assertEqual((change.start, change.duration), (480, 45))
        self.assertEqual(change.raw["ChangeType"], "Absence")
        self.assertIn(change.change_type, CHANGE_TYPES)

    def test_change_without_the_newer_fields_gets_defaults(self):
        change = self.timetable.lessons_on("2026-10-13")[0].change
        self.assertEqual((change.change_type, change.description), ("RoomChanged", "Změna učebny: 105"))
        self.assertEqual((change.type_name, change.type_abbrev, change.begin_time, change.end_time), ("", "", "", ""))
        self.assertEqual((change.lesson_info, change.start, change.duration), (None, None, None))
        documented = Change.from_json({"ChangeType": "Canceled", "Description": "Obecná absence třídy"})
        self.assertEqual(documented, Change("Canceled", "Obecná absence třídy"))

    def test_substitution_list_entry(self):
        change = Change.from_json({
            "ChangeSubject": None, "Day": "2026-10-14T00:00:00+02:00", "Hours": "3. hod", "ChangeType": "Substitution",
            "ChangeDisplayType": "SubstituteTeacher", "Description": "Suplování: Veselý Karel", "Time": "10:00 - 10:45",
            "TypeAbbrev": None, "TypeName": None, "AtomType": "Hour",
            "ChangeLessonInfo": {"ClassAbbrev": "1.B", "GroupAbbrev": "Chl", "IsClassGroup": False,
                                 "SubjectAbbrev": "F", "RoomAbbrev": "031"},
            "BeginTime": "10:00", "EndTime": "10:45", "Start": 0, "Duration": 0,
        })
        self.assertEqual(change.lesson_info, ChangeLessonInfo("1.B", "Chl", False, "F", "031"))
        self.assertEqual((change.begin_time, change.end_time), ("10:00", "10:45"))
        self.assertEqual((change.start, change.duration), (None, None))  # 0 and 0 mean "not set"
        self.assertEqual(
            change.format(), "2026-10-14 3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel | Chl, F, 031"
        )

    def test_padding_is_trimmed_and_unknown_shapes_are_ignored(self):
        change = Change.from_json({
            "ChangeType": "Canceled ", "Description": " Odpadá ", "Hours": "2. hod ", "TypeAbbrev": "Exk ",
            "ChangeSubject": {"Id": "12"}, "Day": "not a date", "ChangeLessonInfo": "1.B", "Duration": "x",
        })
        self.assertEqual((change.change_type, change.description, change.hours, change.type_abbrev),
                         ("Canceled", "Odpadá", "2. hod", "Exk"))
        self.assertEqual((change.change_subject, change.day, change.lesson_info), ("", None, None))
        self.assertIsNone(change.duration)
        self.assertEqual(Change.from_json({"ChangeSubject": "F "}).change_subject, "F")

    def test_start_and_duration_are_unset_independently(self):
        without_duration = Change.from_json({"ChangeType": "Canceled", "Start": 480})
        self.assertEqual((without_duration.start, without_duration.duration), (480, None))
        midnight = Change.from_json({"ChangeType": "Canceled", "Start": 0, "Duration": 45})
        self.assertEqual((midnight.start, midnight.duration), (None, 45))

    def test_to_dict_is_json_serialisable_without_raw(self):
        data = self.timetable.lessons[0].change.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(list(data)[:5], ["change_type", "description", "type_name", "type_abbrev", "time"])
        self.assertEqual((data["day"], data["hours"], data["lesson_info"], data["start"]), ("2026-10-12", "1. hod",
                                                                                          None, 480))
        self.assertNotIn("raw", data)
        info = ChangeLessonInfo("1.B", "1.B", True, "M", "031").to_dict()
        self.assertEqual(info, {"class_abbrev": "1.B", "group_abbrev": "1.B", "is_class_group": True,
                                "subject_abbrev": "M", "room_abbrev": "031"})

    def test_format(self):
        change = self.timetable.lessons[0].change
        self.assertEqual(change.format(), "2026-10-12 1. hod (8:00 - 8:45) Absence: Třídnická hodina: Nováková Jana")
        self.assertEqual(change.format(with_date=False), change.format().replace("2026-10-12 ", ""))
        self.assertEqual(Change("Removed", "", begin_time="12:45", end_time="13:30").format(), "(12:45-13:30) Removed")
        self.assertEqual(Change("", "Odpadá", hours="2. hod").format(), "2. hod Odpadá")  # no dangling ": "
        self.assertEqual(Change("", "").format(), "")

    def test_lesson_info_text(self):
        self.assertEqual(str(ChangeLessonInfo("1.B", "Chl", False, "Tv", "102")), "Chl, Tv, 102")
        self.assertEqual(str(ChangeLessonInfo(class_abbrev="1.B", subject_abbrev="M")), "1.B, M")
        self.assertEqual(str(ChangeLessonInfo()), "")
        self.assertIsNone(ChangeLessonInfo.optional(None))


class ClassTimetableTest(unittest.TestCase):
    def setUp(self):
        self.timetable = Timetable.from_json(load_fixture("timetable_class.json"))

    def test_groups_of_the_class_have_parallel_lessons(self):
        first = [lesson for lesson in self.timetable.lessons_on("2026-10-19") if lesson.hour.caption == "1"]
        self.assertEqual(
            [(lesson.groups[0].abbrev, lesson.teacher.abbrev, lesson.room.abbrev) for lesson in first],
            [("1.B Chl", "Ma", "TV1"), ("1.B Dív", "Bí", "TV2")],
        )
        self.assertEqual(list(self.timetable.classes), ["1B"])
        self.assertEqual(self.timetable.subjects[" 7"].name, "Matematika")

    def test_homeworks_notice_and_atom_details(self):
        lesson = self.timetable.lessons_on("2026-10-19")[2]
        homework = LessonHomework(id="HWQ7K2M9PA", text="Pracovní sešit str. 12, cvičení 3 a 4")  # trimmed
        self.assertEqual(lesson.homeworks, (homework,))
        self.assertEqual(lesson.homework_ids, ("HWQ7K2M9PA",))
        self.assertTrue(lesson.has_homework)
        self.assertEqual((lesson.theme, lesson.notice, lesson.week_theme),
                         ("Lineární rovnice", "Přineste si kalkulačku.", ""))
        self.assertEqual((lesson.start, lesson.duration, lesson.is_last_room_lesson), (535, 45, False))
        self.assertEqual(lesson.raw["LessonRelease"], "NoChange")
        self.assertEqual(lesson.hour, Hour(id=4, caption="2", begin="8:55", end="9:40", start=535, duration=45))
        self.assertNotIn("LessonRelease", repr(lesson))

    def test_substituted_lesson_with_null_texts(self):
        lesson = self.timetable.lessons_on("2026-10-19")[3]
        self.assertEqual((lesson.theme, lesson.notice), ("", ""))
        self.assertTrue(lesson.is_last_room_lesson)
        self.assertFalse(lesson.has_homework)
        self.assertEqual((lesson.teacher.name, lesson.change.change_type), ("Mgr. Karel Veselý", "Substitution"))
        self.assertEqual(lesson.format(), "2026-10-19  3. 10:00-10:45 Fyzika | Mgr. Karel Veselý | 031 | 1.B "
                                          "[Substitution: Suplování: Veselý Karel]")

    def test_multi_hour_event_repeats_its_change_on_every_atom(self):
        events = [lesson for lesson in self.timetable.lessons_on("2026-10-20") if not lesson.is_taught]
        self.assertEqual([lesson.hour.caption for lesson in events], ["1", "2"])
        self.assertEqual(events[0].change, events[1].change)
        change = events[0].change
        self.assertEqual((change.hours, change.time, change.start, change.duration), ("1. - 2. hod", "8:00 - 9:40",
                                                                                      480, 100))
        self.assertEqual((events[0].title, change.type_abbrev), ("Exkurze", "Exk"))
        untitled = dataclasses.replace(events[0], change=dataclasses.replace(change, type_name=""))
        self.assertEqual(untitled.title, "-")

    def test_added_lesson_keeps_its_subject(self):
        added = self.timetable.lessons_on("2026-10-20")[0]
        self.assertEqual((added.hour.caption, added.subject.abbrev, added.change.change_type), ("0", "M", "Added"))

    def test_director_day_has_no_lessons(self):
        day = self.timetable.day("2026-10-21")
        self.assertEqual((day.day_type, day.description, day.lessons), ("DirectorDay", "Ředitelské volno", ()))
        self.assertFalse(day.is_work_day)
        self.assertIn(day.day_type, DAY_TYPES)
        self.assertEqual(day.raw["AssistanceAtoms"], [])

    def test_every_change_type_is_known(self):
        types = [lesson.change.change_type for lesson in self.timetable.changed_lessons]
        self.assertEqual(types, ["Substitution", "Added", "Canceled", "Canceled"])
        self.assertTrue(set(types) <= set(CHANGE_TYPES))

    def test_lesson_to_dict_appends_the_new_keys(self):
        row = self.timetable.lessons_on("2026-10-19")[2].to_dict()
        self.assertEqual(list(row), LESSON_KEYS + NEW_LESSON_KEYS)
        self.assertEqual((row["notice"], row["week_theme"], row["homeworks"]),
                         ("Přineste si kalkulačku.", "", "Pracovní sešit str. 12, cvičení 3 a 4"))

    def test_models_and_their_dicts(self):
        day = self.timetable.days[0]
        for model in (self.timetable, day, day.lessons[0], day.lessons[0].hour, day.lessons[3].change,
                      day.lessons[2].homeworks[0]):
            self.assertIsInstance(model, Model)
        data = self.timetable.to_dict()
        self.assertEqual(day.to_dict(), data["days"][0])
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(list(data["days"][2]), ["date", "day_of_week", "day_type", "description", "lessons"])
        self.assertEqual(day.lessons[2].homeworks[0].to_dict(), {"id": "HWQ7K2M9PA",
                                                                  "text": "Pracovní sešit str. 12, cvičení 3 a 4"})

    def test_models_are_frozen_hashable_and_compare_without_raw(self):
        lesson = self.timetable.lessons[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            lesson.notice = "changed"
        self.assertEqual(dataclasses.replace(lesson, raw={}), lesson)
        self.assertEqual(len({lesson, dataclasses.replace(lesson, raw={}), self.timetable.lessons[3]}), 2)
        self.assertEqual(hash(self.timetable.days[0]), hash(dataclasses.replace(self.timetable.days[0], raw={})))


class HolidayWeekTest(unittest.TestCase):
    def test_a_week_of_holidays_has_days_without_lessons_and_empty_lookups(self):
        timetable = Timetable.from_json(load_fixture("timetable_holiday.json"))
        self.assertEqual([day.day_type for day in timetable.days], ["Holiday"] * 4 + ["Celebration"])
        self.assertEqual((timetable.lessons, timetable.subjects, timetable.teachers), ([], {}, {}))
        self.assertTrue(timetable.covers_week_of("2027-01-03"))
        self.assertEqual(timetable.days[-1].format_summary(), "2027-01-01 pá Celebration (Nový rok): 0 lesson(s)")
        self.assertEqual(timetable.to_dict()["days"][0]["lessons"], [])


class LenientParsingTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture("timetable_class.json")

    def test_entries_that_are_not_objects_are_reported_or_skipped(self):
        self.data["Hours"].append("11:00")
        self.data["Subjects"].append(None)
        self.data["Days"].append(["not", "a", "day"])
        self.data["Days"][0]["Atoms"].insert(0, 42)
        self.data["Days"][0]["Atoms"][1]["Homeworks"].append("Úkol")
        problems = contract_problems(self.data)
        self.assertIn("Hour slot '11:00' lacks Id, Caption, BeginTime, EndTime", problems)
        self.assertIn("Day ['not', 'a', 'day'] lacks DayOfWeek, Date, DayType, Atoms", problems)
        self.assertIn("2026-10-19: a lesson is not a JSON object", problems)
        timetable = Timetable.from_json(self.data, validate=False)
        self.assertEqual((len(timetable.hours), len(timetable.days), len(timetable.subjects)), (4, 3, 3))
        self.assertEqual(len(timetable.days[0].lessons), 4)
        self.assertEqual(timetable.days[0].lessons[0].homeworks, ())

    def test_odd_values_fall_back_to_defaults(self):
        day = self.data["Days"][0]
        day.update(DayOfWeek="pondělí", DayType=None, DayDescription=None)
        day["Atoms"][2].update(CycleIds=None, Change={}, IsLastRoomLesson="true", Start="535", HomeworkIds=None,
                               Homeworks=None, Notice=7)
        day["Atoms"][3]["Change"] = "Suplování"
        lesson = Timetable.from_json(self.data, validate=False).days[0].lessons[2]
        parsed_day = Timetable.from_json(self.data, validate=False).days[0]
        self.assertEqual((parsed_day.day_of_week, parsed_day.day_type, parsed_day.description), (1, "", ""))
        self.assertEqual((lesson.cycles, lesson.change, lesson.homeworks, lesson.homework_ids), ((), None, (), ()))
        self.assertEqual((lesson.is_last_room_lesson, lesson.start, lesson.notice), (True, 535, "7"))
        self.assertIsNone(parsed_day.lessons[3].change)

    def test_a_lesson_without_hour_id(self):
        del self.data["Days"][0]["Atoms"][0]["HourId"]
        self.assertEqual(contract_problems(self.data), ["2026-10-19: a lesson has no HourId"])
        lesson = Timetable.from_json(self.data, validate=False).lessons[0]
        self.assertEqual(lesson.hour, Hour(id=0, caption="", begin="", end=""))
        self.assertEqual(lesson.subject.name, "Tělesná výchova")


class TimetableEndpointTest(unittest.TestCase):
    def test_actual_timetable_date_parameter(self):
        client, transport = logged_in_client(ACTUAL, ACTUAL, ACTUAL, ACTUAL)
        client.actual_timetable(dt.date(2026, 10, 22))
        client.actual_timetable(dt.datetime(2026, 10, 22, 12, 0))
        client.actual_timetable("2026-10-22")
        client.actual_timetable()
        self.assertEqual([call.query for call in transport.calls[1:]], [{"date": "2026-10-22"}] * 3 + [{}])
        self.assertEqual(transport.calls[1].api_path, "/api/3/timetable/actual")

    def test_permanent_timetable_sends_no_date(self):
        client, transport = logged_in_client(PERMANENT)
        timetable = client.permanent_timetable()
        self.assertEqual((transport.calls[1].api_path, transport.calls[1].query), ("/api/3/timetable/permanent", {}))
        self.assertEqual(len(timetable.taught_lessons), 3)

    def test_timetable_contract_is_validated_unless_disabled(self):
        broken = load_fixture("actual.json")
        broken["Days"][0]["Atoms"][1]["TeacherId"] = "T9"
        client, _ = logged_in_client(json_response(200, broken), json_response(200, broken))
        with self.assertRaises(TimetableContractError):
            client.actual_timetable()
        self.assertIsNone(client.actual_timetable(validate=False).lessons[1].teacher)

    def test_non_object_payload_is_a_contract_error(self):
        client, _ = logged_in_client(json_response(200, []))
        with self.assertRaises(TimetableContractError):
            client.timetable_json("permanent")

    def test_unknown_timetable_kind(self):
        client, _ = logged_in_client()
        with self.assertRaises(ValueError):
            client.timetable_json("weekly")


class ClassTimetableEndpointTest(unittest.TestCase):
    def test_actual_class_timetable_with_and_without_date(self):
        client, transport = logged_in_client(CLASS, CLASS)
        timetable = client.class_timetable("1B", dt.date(2026, 10, 21))
        client.class_timetable("1B")
        first, second = transport.api_calls
        self.assertEqual((first.method, first.api_path), ("GET", "/api/3/timetable/actual/class/1B"))
        self.assertEqual((first.query, second.query), ({"date": "2026-10-21"}, {}))
        self.assertEqual(first.headers["Authorization"], "Bearer access-1")
        self.assertEqual((len(timetable.lessons), len(timetable.groups)), (7, 3))

    def test_permanent_class_timetable_sends_no_date(self):
        client, transport = logged_in_client(PERMANENT)
        timetable = client.class_timetable("1B", "2026-10-21", permanent=True)
        call = transport.api_calls[0]
        self.assertEqual((call.api_path, call.query), ("/api/3/timetable/permanent/class/1B", {}))
        self.assertEqual(len(timetable.taught_lessons), 3)

    def test_class_ids_are_percent_encoded_and_items_are_accepted(self):
        client, transport = logged_in_client(CLASS, CLASS)
        client.class_timetable("Z[1] B/2")
        client.class_timetable(Item(id=" 1B", abbrev="1.B", name="Prima B"))
        self.assertEqual([call.api_path for call in transport.api_calls], [
            "/api/3/timetable/actual/class/Z%5B1%5D%20B%2F2",
            "/api/3/timetable/actual/class/%201B",
        ])

    def test_an_empty_class_id_is_rejected_before_any_request(self):
        client, transport = logged_in_client()
        for class_id in ("", "  ", None, Item(id="", abbrev="", name="")):
            with self.assertRaises(ValueError):
                client.class_timetable(class_id)
        self.assertEqual(transport.calls, [])

    def test_other_types_are_refused_instead_of_sent_as_their_repr(self):
        @dataclasses.dataclass
        class Profile:  # passing the whole profile instead of its school_class
            full_name: str
            school_class: Item

        profile = Profile("Jan Novák", Item(id="1B", abbrev="1.B", name="Prima B"))
        client, transport = logged_in_client(CLASS, CLASS)
        for value in (profile, {"Id": "1B"}, 12):
            with self.assertRaises(TypeError) as raised:
                client.class_timetable(value)
            self.assertNotIn("Novák", str(raised.exception))
            with self.assertRaises(TypeError):
                client.timetable_json("actual", class_id=value)
        self.assertEqual(transport.calls, [])
        client.class_timetable(profile.school_class)
        client.class_timetable(Item(id=12, abbrev="1.B", name="Prima B"), permanent=True)  # an id built by hand
        self.assertEqual([call.api_path for call in transport.api_calls],
                         ["/api/3/timetable/actual/class/1B", "/api/3/timetable/permanent/class/12"])

    def test_contract_validation_and_http_errors(self):
        broken = load_fixture("timetable_class.json")
        broken["Days"][0]["Atoms"][0]["RoomId"] = "R404"
        client, _ = logged_in_client(json_response(200, broken), json_response(200, broken), FORBIDDEN, NOT_FOUND)
        with self.assertRaises(TimetableContractError) as raised:
            client.class_timetable("1B")
        self.assertEqual(raised.exception.problems, ["2026-10-19: RoomId 'R404' is not defined in Rooms"])
        self.assertIsNone(client.class_timetable("1B", validate=False).lessons[0].room)
        with self.assertRaises(BakalariPermissionError):
            client.class_timetable("2C")
        with self.assertRaises(BakalariNotFoundError):
            client.class_timetable("9Z", permanent=True)

    def test_raw_class_timetable(self):
        client, transport = logged_in_client(CLASS, json_response(200, ["not", "a", "timetable"]))
        data = client.timetable_json("actual", "2026-10-19", class_id="1B")
        self.assertEqual(data["Classes"][0]["Id"], "1B")
        self.assertEqual(transport.api_calls[0].query, {"date": "2026-10-19"})
        with self.assertRaises(TimetableContractError):
            client.timetable_json("permanent", class_id="1B")
        with self.assertRaises(ValueError):
            client.timetable_json("weekly", class_id="1B")
        self.assertEqual(len(transport.api_calls), 2)

    def test_bodies_that_are_not_a_json_object(self):
        client, _ = logged_in_client(text_response(200, "<html>Přihlášení</html>"), empty_response(200))
        for _ in range(2):
            with self.assertRaises(BakalariContractError):
                client.class_timetable("1B", validate=False)


if __name__ == "__main__":
    unittest.main()
