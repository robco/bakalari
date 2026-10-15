import copy
import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError, Hour, Item
from bakalari.teacher import (
    ClassBook,
    ClassBookDay,
    ClassBookGroup,
    ClassBookRecord,
    LessonPast,
    LessonTag,
    MarkingAtom,
    MarkingSheet,
    MarkingStudent,
    classbook_problems,
    format_classbook_time,
)

from .support import NOT_TEACHER, json_response, load_fixture, logged_in_client

CLASSBOOK = load_fixture("teacher_classbook.json")
SAVED = load_fixture("teacher_classbook_saved.json")
LESSON = load_fixture("teacher_lesson.json")
MARKING = load_fixture("teacher_marking.json")
PRAGUE = dt.timezone(dt.timedelta(hours=2))


class ClassBookTimeTest(unittest.TestCase):
    def test_dates_cover_the_whole_day(self):
        self.assertEqual(format_classbook_time(dt.date(2026, 9, 22)), "2026-09-22T00:00:00.000")
        self.assertEqual(format_classbook_time(dt.date(2026, 9, 28), end_of_day=True), "2026-09-28T23:59:59.999")
        self.assertEqual(format_classbook_time(" 2026-09-28 ", end_of_day=True), "2026-09-28T23:59:59.999")

    def test_datetimes_keep_their_wall_clock_time_with_milliseconds_and_no_offset(self):
        self.assertEqual(format_classbook_time(dt.datetime(2026, 9, 22, 7, 5, 9, 123456)), "2026-09-22T07:05:09.123")
        aware = dt.datetime(2026, 9, 22, 13, 30, tzinfo=PRAGUE)
        self.assertEqual(format_classbook_time(aware, end_of_day=True), "2026-09-22T13:30:00.000")
        self.assertEqual(format_classbook_time("2026-09-22T13:30:00+02:00"), "2026-09-22T13:30:00.000")
        self.assertEqual(format_classbook_time("2026-09-22T13:30:00.5"), "2026-09-22T13:30:00.500")

    def test_other_strings_go_to_the_server_unchanged_and_other_types_fail(self):
        self.assertEqual(format_classbook_time("next week"), "next week")
        self.assertEqual(format_classbook_time("2026-13-45"), "2026-13-45")
        with self.assertRaises(TypeError):
            format_classbook_time(20260922)


class ClassBookParsingTest(unittest.TestCase):
    def setUp(self):
        self.book = ClassBook.from_json(CLASSBOOK)

    def test_days_keep_type_description_and_records(self):
        work_day, holiday = self.book.days
        self.assertEqual((work_day.date, work_day.day_of_week, work_day.day_type), (dt.date(2026, 9, 21), 1, "WorkDay"))
        self.assertEqual(len(work_day.records), 3)
        self.assertEqual((holiday.day_type, holiday.description, holiday.records),
                         ("Celebration", "Den české státnosti", ()))
        self.assertIsInstance(work_day, ClassBookDay)

    def test_hours_are_timetable_hour_slots(self):
        self.assertEqual([hour.id for hour in self.book.hours], [2, 3, 5])
        self.assertIsInstance(self.book.hours[1], Hour)
        slot = self.book.hours[1]
        self.assertEqual((slot.caption, slot.begin, slot.end), ("1", "8:00", "8:45"))

    def test_full_record(self):
        record = self.book.records[0]
        self.assertEqual((record.id, record.lesson_id, record.label), ("2026092103AB", "20260921030300012", "14"))
        self.assertEqual((record.theme, record.notice), ("Pythagorova věta", "Přinést kružítko"))  # trimmed
        self.assertEqual((record.private_notice, record.week_theme), ("Ověřit domácí úkoly", "Geometrie v rovině"))
        self.assertEqual(record.tags, ("T1", "T 2"))
        self.assertEqual((record.level, record.hour_id, record.date), ("SecondLevel", 3, dt.date(2026, 9, 21)))
        self.assertEqual((record.start, record.duration, record.hour_caption, record.hour_time),
                         (480, 45, "1", "8:00 - 8:45"))
        self.assertEqual(record.subject, Item(" 7", "M", "Matematika"))
        self.assertEqual(record.groups, (ClassBookGroup("AB", "2.B", "2.B", class_id="2B"),))
        self.assertEqual(str(record.groups[0]), "2.B")
        self.assertEqual((record.editable_groups, record.change_text, record.supervision), (("AB",), "", None))
        self.assertTrue(record.is_written)
        self.assertEqual(record.raw["Theme"], " Pythagorova věta")

    def test_record_with_the_documented_fields_only(self):
        record = self.book.records[1]
        self.assertEqual(record.id, "2026092105 C")  # ids are kept exactly
        self.assertEqual((record.notice, record.tags, record.date, record.start, record.hour_caption),
                         ("", (), None, None, ""))
        self.assertEqual([group.id for group in record.groups], [" C", " D"])
        self.assertEqual([group.class_id for group in record.groups], ["1A", "1B"])
        self.assertEqual(record.editable_groups, (" C",))

    def test_record_with_nulls_gets_defaults(self):
        record = self.book.records[2]
        self.assertEqual((record.label, record.theme, record.level, record.tags), ("", "", "", ()))
        self.assertEqual((record.hour_id, record.date, record.subject, record.groups), (None, None, None, ()))
        self.assertEqual((record.change_text, record.supervision), ("Suplování za: Fiktivní Oto", False))
        self.assertFalse(record.is_written)

    def test_tags_given_as_objects_become_their_ids(self):
        record = ClassBookRecord.from_json({"Id": "X", "Tags": [{"Id": "T1", "Title": "Projekt"}, "T2", None]})
        self.assertEqual(record.tags, ("T1", "T2"))

    def test_lookups(self):
        self.assertIs(self.book.record("2026092105 C"), self.book.records[1])
        self.assertIs(self.book.record("20260921030300012"), self.book.records[0])
        self.assertIsNone(self.book.record("2026092105C"))
        self.assertEqual(self.book.hour(5).caption, "3")
        self.assertIsNone(self.book.hour(None))
        self.assertIsNone(self.book.hour(9))

    def test_to_dict_is_json_serialisable_and_hides_raw(self):
        data = self.book.to_dict()
        json.dumps(data, ensure_ascii=False)
        record = data["days"][0]["records"][0]
        self.assertNotIn("raw", record)
        self.assertEqual(record["date"], "2026-09-21")
        self.assertEqual(record["groups"], [{"id": "AB", "abbrev": "2.B", "name": "2.B", "class_id": "2B"}])
        hour = data["hours"][0]
        self.assertEqual({key: hour[key] for key in ("id", "caption", "begin", "end")},
                         {"id": 2, "caption": "0", "begin": "7:05", "end": "7:50"})

    def test_saved_day_has_no_hour_slots(self):
        book = ClassBook.from_json(SAVED)
        self.assertEqual(book.hours, ())
        # The save answer sends DayOfWeek and DayType as 0: the weekday follows from the date, the type is unknown.
        self.assertEqual((book.days[0].day_of_week, book.days[0].day_type, book.days[0].description), (1, "", ""))
        self.assertEqual((book.days[0].raw["DayOfWeek"], book.days[0].raw["DayType"]), (0, 0))
        self.assertEqual((book.records[0].label, book.records[0].week_theme), ("15", ""))

    def test_day_without_a_weekday_or_a_named_type(self):
        day = ClassBookDay.from_json({"Date": "2026-09-27T00:00:00+02:00", "DayOfWeek": None, "DayType": 3})
        self.assertEqual((day.date, day.day_of_week, day.day_type), (dt.date(2026, 9, 27), 7, ""))
        undated = ClassBookDay.from_json({"Date": None, "DayOfWeek": 0, "DayType": "Holiday"})
        self.assertEqual((undated.date, undated.day_of_week, undated.day_type), (None, None, "Holiday"))


class ClassBookContractTest(unittest.TestCase):
    def test_valid_payloads_have_no_problems(self):
        self.assertEqual(classbook_problems(CLASSBOOK), [])
        self.assertEqual(classbook_problems(SAVED), [])

    def test_problems_are_listed(self):
        self.assertEqual(classbook_problems([]), ["The class book must be a JSON object"])
        self.assertEqual(classbook_problems({"Hours": []}), ["Missing list 'Days'"])
        broken = copy.deepcopy(CLASSBOOK)
        broken["Hours"] = {"Id": 1}
        broken["Days"][0]["Hours"] = "none"
        broken["Days"].append("not a day")
        self.assertEqual(sorted(classbook_problems(broken)), sorted([
            "'Hours' must be a JSON array or null",
            "Day 2026-09-21: 'Hours' must be a JSON array or null",
            "1 entry of 'Days' is not a JSON object",
        ]))
        with self.assertRaises(BakalariContractError) as raised:
            ClassBook.from_json(broken)
        self.assertEqual(len(raised.exception.problems), 3)

    def test_records_and_hour_slots_must_be_objects(self):
        broken = copy.deepcopy(CLASSBOOK)
        broken["Hours"].append(7)
        broken["Days"][0]["Hours"] += ["record", None]
        self.assertEqual(classbook_problems(broken), [
            "'Hours' contains 1 entry other than JSON objects",
            "Day 2026-09-21: 'Hours' contains 2 entries other than JSON objects",
        ])
        with self.assertRaises(BakalariContractError):
            ClassBook.from_json(broken)
        lenient = ClassBook.from_json(broken, validate=False)
        self.assertEqual((len(lenient.hours), len(lenient.records)), (3, 3))

    def test_lenient_parse_and_non_objects(self):
        self.assertEqual(ClassBook.from_json({"Hours": None}, validate=False).days, ())
        broken = copy.deepcopy(CLASSBOOK)
        broken["Days"][0]["Hours"] = "none"
        self.assertEqual(ClassBook.from_json(broken, validate=False).days[0].records, ())
        with self.assertRaises(BakalariContractError):
            ClassBook.from_json([], validate=False)


class RequestBodyTest(unittest.TestCase):
    def setUp(self):
        self.record = ClassBook.from_json(CLASSBOOK).records[0]

    def test_documented_keys_with_the_servers_values(self):
        self.assertEqual(self.record.request_body(), {
            "Id": "2026092103AB",
            "LessonId": "20260921030300012",
            "ClassBookLevel": "SecondLevel",
            "Label": "14",
            "Notice": "Přinést kružítko ",
            "PrivateNotice": "Ověřit domácí úkoly",
            "Tags": ["T1", "T 2"],
            "Theme": " Pythagorova věta",
            "WeekTheme": "Geometrie v rovině",
            "Groups": [{"Id": "AB", "ClassId": "2B"}],
        })

    def test_changes_replace_values(self):
        body = self.record.request_body(theme="Pythagorova věta - procvičování", notice="", label="15", tags=["T3"])
        self.assertEqual((body["Theme"], body["Notice"], body["Label"], body["Tags"]),
                         ("Pythagorova věta - procvičování", "", "15", ["T3"]))
        self.assertEqual(body["PrivateNotice"], "Ověřit domácí úkoly")
        body = self.record.request_body(private_notice="Jen pro mě", week_theme="Opakování")
        self.assertEqual((body["PrivateNotice"], body["WeekTheme"]), ("Jen pro mě", "Opakování"))

    def test_null_texts_are_sent_as_empty_strings_and_a_record_without_raw_uses_its_fields(self):
        # As the official app does: it saves a record whose class book "WeekTheme" is null with "WeekTheme": "".
        body = ClassBook.from_json(CLASSBOOK).records[2].request_body()
        self.assertEqual([body[key] for key in ("Label", "Notice", "PrivateNotice", "Theme", "WeekTheme")], [""] * 5)
        self.assertEqual((body["ClassBookLevel"], body["Tags"], body["Groups"]), (None, [], []))
        self.assertEqual(ClassBook.from_json(CLASSBOOK).records[2].request_body(theme="Téma")["Theme"], "Téma")
        built = ClassBookRecord(id="R1", lesson_id="L1", label="3", theme="Téma", tags=("T1",),
                                groups=(ClassBookGroup("G1", "1.A", "1.A", class_id="1A"),))
        self.assertEqual(built.request_body(), {
            "Id": "R1", "LessonId": "L1", "ClassBookLevel": "", "Label": "3", "Notice": "", "PrivateNotice": "",
            "Tags": ["T1"], "Theme": "Téma", "WeekTheme": "", "Groups": [{"Id": "G1", "ClassId": "1A"}],
        })

    def test_groups_are_the_editable_ones_with_their_class_ids(self):
        # Record " C" covers two groups, of which the teacher may write for " C" only (EditableGroups).
        record = ClassBook.from_json(CLASSBOOK).records[1]
        self.assertEqual(record.request_body()["Groups"], [{"Id": " C", "ClassId": "1A"}])
        every_group = [{"Id": " C", "ClassId": "1A"}, {"Id": " D", "ClassId": "1B"}]  # when none is editable
        for editable in (["X"], [], None):
            unknown = ClassBookRecord.from_json({**record.raw, "EditableGroups": editable})
            self.assertEqual(unknown.request_body()["Groups"], every_group)
        built = ClassBookRecord(
            id="R1", groups=(ClassBookGroup("G1", "1.A", "1.A", class_id="1A"), ClassBookGroup("G2", "", "", "1B")),
            editable_groups=("G2",),
        )
        self.assertEqual(built.request_body()["Groups"], [{"Id": "G2", "ClassId": "1B"}])

    def test_tags_can_be_one_id_or_lesson_tags(self):
        tag = LessonTag.from_json(LESSON["lessonTags"][1])
        self.assertEqual(self.record.request_body(tags="T3")["Tags"], ["T3"])
        self.assertEqual(self.record.request_body(tags=[tag, "T1"])["Tags"], ["T 2", "T1"])
        self.assertEqual(self.record.request_body(tags=())["Tags"], [])
        json.dumps(self.record.request_body(tags=(tag,)))


class LessonAndTagModelTest(unittest.TestCase):
    def test_lesson_tags(self):
        tags = [LessonTag.from_json(tag) for tag in LESSON["lessonTags"]]
        self.assertEqual([(tag.id, tag.abbreviation, tag.title) for tag in tags],
                         [("T1", "EC1", "Projekt"), ("T 2", "EXK", "Exkurze"), ("T3", "", "")])
        self.assertEqual(tags[0].to_dict(), {"id": "T1", "abbreviation": "EC1", "title": "Projekt"})

    def test_lesson_past(self):
        past = LessonPast.from_json(LESSON["past"])
        self.assertEqual((past.lesson_id, past.last_theme, past.next_label),
                         ("20260921030300012", "Pythagorova věta", "15"))
        self.assertEqual(past.raw, LESSON["past"])
        with self.assertRaises(BakalariContractError):
            LessonPast.from_json(["not", "an", "object"])


class MarkingModelTest(unittest.TestCase):
    def test_atoms(self):
        atoms = [MarkingAtom.from_json(atom) for atom in MARKING["atoms"]["Atoms"]]
        self.assertEqual([atom.id for atom in atoms], ["A1B2C3", "A1B2C4", "A[9]"])
        self.assertEqual((atoms[0].name, atoms[0].subject, atoms[0].disabled),
                         ("2.B Matematika", Item(" 7", "M", "Matematika"), False))
        self.assertEqual((atoms[1].disabled, atoms[1].disabled_text), (True, "Klasifikace je uzavřena"))
        self.assertIsNone(atoms[2].subject)

    def test_sheet(self):
        sheet = MarkingSheet.from_json(MARKING["marks"])
        self.assertEqual([option.id for option in sheet.mark_options], ["1", "2-", "N"])
        first, second, minimal = sheet.marks
        self.assertEqual(first.mark_date, dt.datetime(2026, 10, 5, tzinfo=PRAGUE))
        self.assertEqual(first.edit_date, dt.datetime(2026, 10, 5, 10, 15, 42, 123456, tzinfo=PRAGUE))
        self.assertEqual((first.teacher_id, first.header_id, first.mark_value, first.theme),
                         ("UQX01", "H01", "1", "Zlomky"))
        self.assertEqual((first.confirmed_by, first.confirmation_state, first.is_confirmed),
                         ("ZQ1A2B3C4D5", "Confirmed", True))
        self.assertEqual(first.confirmed_at, dt.datetime(2026, 10, 6, 19, 2, 11, tzinfo=PRAGUE))
        self.assertEqual((second.read_only, second.read_only_description), (True, "Známku zapsal jiný učitel"))
        self.assertEqual((second.publish_date, second.confirmed_at, second.is_confirmed), (None, None, False))
        self.assertEqual((minimal.mark_date, minimal.edit_date, minimal.teacher_id, minimal.read_only),
                         (None, None, "", False))
        self.assertEqual([teacher.abbrev for teacher in sheet.teachers], ["Te", "Fi"])

    def test_students(self):
        sheet = MarkingSheet.from_json(MARKING["marks"])
        adam, bara = sheet.students
        self.assertEqual((adam.name, adam.class_id, adam.registration_number, adam.average_text1),
                         ("Pokusný Adam", "2B", "1", "1,00"))
        self.assertEqual((bara.name, bara.middle_name, bara.registration_number, bara.average_text2),
                         ("Zkušební Bára Marie", "Marie", "2", ""))
        self.assertTrue(bara.released)
        self.assertEqual(str(bara), "Zkušební Bára Marie")
        self.assertEqual(str(MarkingStudent(id="S9")), "S9")
        self.assertIs(sheet.student("S002"), bara)
        self.assertIsNone(sheet.student("S9"))
        self.assertEqual([mark.id for mark in sheet.marks_of("S001")], ["M0001", "M0003"])
        self.assertEqual([mark.id for mark in sheet.marks_of(bara)], ["M0002"])

    def test_sheet_contract(self):
        with self.assertRaises(BakalariContractError):
            MarkingSheet.from_json({"Students": []})
        self.assertEqual(MarkingSheet.from_json({"Students": None}, validate=False).marks, ())
        with self.assertRaises(BakalariContractError):
            MarkingSheet.from_json("marks", validate=False)

    def test_to_dict_round_trip(self):
        data = MarkingSheet.from_json(MARKING["marks"]).to_dict()
        text = json.dumps(data, ensure_ascii=False)
        self.assertEqual(json.loads(text)["marks"][0]["edit_date"], "2026-10-05T10:15:42.123456+02:00")
        self.assertNotIn("raw", data["students"][0])


class TeacherEndpointTest(unittest.TestCase):
    def test_classbook_sends_the_interval_with_milliseconds(self):
        client, transport = logged_in_client(json_response(200, CLASSBOOK), json_response(200, CLASSBOOK))
        book = client.classbook(dt.date(2026, 9, 21), "2026-09-27")
        client.classbook(dt.datetime(2026, 9, 21, 8, 0), dt.datetime(2026, 9, 21, 12, 30, 15, 250000))
        first, second = transport.api_calls
        self.assertEqual((first.method, first.api_path), ("GET", "/api/3/classbook"))
        self.assertEqual(first.query, {"from": "2026-09-21T00:00:00.000", "to": "2026-09-27T23:59:59.999"})
        self.assertEqual(second.query, {"from": "2026-09-21T08:00:00.000", "to": "2026-09-21T12:30:15.250"})
        self.assertEqual(len(book.records), 3)

    def test_classbook_validation(self):
        client, _ = logged_in_client(json_response(200, {"Hours": []}), json_response(200, {"Hours": []}))
        with self.assertRaises(BakalariContractError):
            client.classbook("2026-09-21", "2026-09-27")
        self.assertEqual(client.classbook("2026-09-21", "2026-09-27", validate=False).days, ())

    def test_save_classbook_record_posts_the_body_to_the_quoted_id(self):
        client, transport = logged_in_client(json_response(200, SAVED), json_response(200, SAVED))
        body = {"Id": "2026092105 C", "LessonId": "20260921050500031", "Theme": "Nové téma", "Groups": []}
        saved = client.save_classbook_record(body)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("POST", "/api/3/classbook/2026092105%20C"))
        self.assertEqual(call.json, body)
        self.assertEqual(call.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual((saved.hours, saved.records[0].theme), ((), "Pythagorova věta - procvičování"))
        record = ClassBook.from_json(CLASSBOOK).records[0]
        client.save_classbook_record(record)
        call = transport.api_calls[1]
        self.assertEqual(call.api_path, "/api/3/classbook/2026092103AB")
        self.assertEqual(call.json, record.request_body())

    def test_save_of_a_merged_lesson_record_and_a_refused_save(self):
        invalid = json_response(400, {"Message": "The request is invalid.", "ModelState": {"Label": ["Chybí"]}})
        client, transport = logged_in_client(json_response(200, SAVED), invalid)
        record = ClassBook.from_json(CLASSBOOK).records[1]
        client.save_classbook_record(record)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("POST", "/api/3/classbook/2026092105%20C"))
        self.assertEqual((call.json["Groups"], call.json["Notice"]), ([{"Id": " C", "ClassId": "1A"}], ""))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.save_classbook_record(record.request_body(label=""))
        self.assertEqual((raised.exception.status, raised.exception.message), (400, "The request is invalid."))

    def test_save_without_an_id_sends_nothing(self):
        client, transport = logged_in_client()
        for body in ({"Theme": "x"}, {"Id": "  "}, {"Id": None}):
            with self.assertRaises(ValueError):
                client.save_classbook_record(body)
        self.assertEqual(transport.calls, [])

    def test_lesson_tags(self):
        client, transport = logged_in_client(json_response(200, LESSON["lessonTags"]), json_response(200, {"Id": 1}))
        tags = client.lesson_tags()
        self.assertEqual((transport.api_calls[0].method, transport.api_calls[0].api_path),
                         ("GET", "/api/3/classbook/lessonTags"))
        self.assertEqual([tag.abbreviation for tag in tags], ["EC1", "EXK", ""])
        with self.assertRaises(BakalariContractError):
            client.lesson_tags()

    def test_lesson_endpoints_use_the_quoted_lesson_id(self):
        client, transport = logged_in_client(
            json_response(200, LESSON["absence"]), json_response(200, LESSON["past"]),
            json_response(200, LESSON["studentsTimetable"]),
        )
        absence = client.lesson_absence("20260921 03/1")
        past = client.lesson_past("20260921 03/1")
        students = client.lesson_students_timetable("20260921 03/1")
        self.assertEqual([call.method for call in transport.api_calls], ["GET"] * 3)
        self.assertEqual([call.api_path for call in transport.api_calls], [
            "/api/3/lesson/20260921%2003%2F1/absence",
            "/api/3/lesson/20260921%2003%2F1/past",
            "/api/3/lesson/20260921%2003%2F1/studentsTimetable",
        ])
        self.assertEqual(absence, LESSON["absence"])
        self.assertEqual(absence["AbsencesGroups"][0]["StudentsAbsences"][1]["StudentReleased"], True)
        # Raw as sent: an absence's HourId is a string while the lesson's HourId is a number.
        self.assertEqual((absence["AbsencesGroups"][0]["StudentsAbsences"][0]["Absences"][0]["HourId"],
                          absence["HourId"]), ("3", 3))
        self.assertEqual((past.last_theme, past.next_label), ("Pythagorova věta", "15"))
        self.assertEqual(students["StudentTimetables"][0]["Hours"][1]["Start"], 600)
        # One entry per student (captured traffic), with the student ids of the lesson's absence list.
        self.assertEqual([entry["Id"] for entry in students["StudentTimetables"]],
                         [entry["Student"]["Id"] for entry in absence["AbsencesGroups"][0]["StudentsAbsences"]])

    def test_raw_lesson_endpoints_require_objects(self):
        client, _ = logged_in_client(json_response(200, []), json_response(200, None), json_response(200, "x"))
        with self.assertRaises(BakalariContractError):
            client.lesson_absence("L1")
        with self.assertRaises(BakalariContractError):
            client.lesson_students_timetable("L1")
        with self.assertRaises(BakalariContractError):
            client.lesson_past("L1")

    def test_marking_endpoints(self):
        client, transport = logged_in_client(json_response(200, MARKING["atoms"]), json_response(200, MARKING["marks"]))
        atoms = client.marking_atoms()
        sheet = client.marking_marks(atoms[2].id)
        self.assertEqual([(call.method, call.api_path) for call in transport.api_calls],
                         [("GET", "/api/3/marking/atoms"), ("GET", "/api/3/marking/marks/A%5B9%5D")])
        self.assertEqual(len(atoms), 3)
        self.assertEqual(len(sheet.marks), 3)

    def test_marking_validation(self):
        client, _ = logged_in_client(
            json_response(200, {"Atoms": None}), json_response(200, {"Atoms": None}), json_response(200, []),
            json_response(200, {"Students": []}), json_response(200, {"Students": []}),
        )
        with self.assertRaises(BakalariContractError):
            client.marking_atoms()
        self.assertEqual(client.marking_atoms(validate=False), [])
        with self.assertRaises(BakalariContractError):
            client.marking_atoms(validate=False)
        with self.assertRaises(BakalariContractError):
            client.marking_marks("A1")
        self.assertEqual(client.marking_marks("A1", validate=False).students, ())

    def test_emergency_configuration_is_raw(self):
        payload = {"Scenarios": [{"Id": 1, "Name": "Požární poplach"}], "Enabled": True}
        client, transport = logged_in_client(json_response(200, payload))
        self.assertEqual(client.emergency_configuration(), payload)
        self.assertEqual((transport.api_calls[0].method, transport.api_calls[0].api_path),
                         ("GET", "/api/3/emergency/configuration"))

    def test_non_teacher_accounts_get_permission_errors(self):
        calls = [
            lambda client: client.classbook("2026-09-21", "2026-09-27"),
            lambda client: client.save_classbook_record({"Id": "R1"}),
            lambda client: client.lesson_tags(),
            lambda client: client.lesson_absence("L1"),
            lambda client: client.lesson_past("L1"),
            lambda client: client.lesson_students_timetable("L1"),
            lambda client: client.marking_atoms(),
            lambda client: client.marking_marks("A1"),
            lambda client: client.emergency_configuration(),
        ]
        for call in calls:
            client, _ = logged_in_client(NOT_TEACHER)
            with self.assertRaises(BakalariPermissionError) as raised:
                call(client)
            self.assertEqual(raised.exception.message, "Some privilege is missing (IsTeacher).")


if __name__ == "__main__":
    unittest.main()
