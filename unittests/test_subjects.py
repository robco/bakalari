import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariNotFoundError, BakalariPermissionError, Item
from bakalari.subjects import SubjectInfo, SubjectThemes, Theme, find_subject, parse_subjects

from .support import BASE_URL, FORBIDDEN, json_response, load_fixture, logged_in_client, make_client, text_response

SUBJECTS = "subjects.json"
THEMES = "subjects_themes.json"
IIS_404 = text_response(404, "<html><head><title>404 - File or directory not found.</title></head></html>")


class SubjectInfoTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture(SUBJECTS)
        self.subjects = parse_subjects(self.data)

    def test_subjects_keep_the_server_order_and_padded_ids(self):
        self.assertEqual([subject.id for subject in self.subjects], [" 2", "10", "TV"])
        czech = self.subjects[0]
        self.assertEqual((czech.name, czech.abbrev), ("Český jazyk a literatura", "Čj"))
        self.assertEqual(czech.teacher, Item("UTX1A", "Nv", "Mgr. Jana Nováková"))
        self.assertEqual(czech.raw, self.data["Subjects"][0])

    def test_null_contacts_become_empty_strings(self):
        czech = self.subjects[0]
        contacts = (czech.teacher_email, czech.teacher_web, czech.teacher_school_phone, czech.teacher_home_phone,
                    czech.teacher_mobile_phone)
        self.assertEqual(contacts, ("", "", "", "", ""))

    def test_published_contacts(self):
        sport = self.subjects[2]
        self.assertEqual(sport.teacher_email, "eva.dvorakova@school.example")
        self.assertEqual((sport.teacher_web, sport.teacher_home_phone), ("", ""))
        self.assertEqual(sport.teacher_school_phone, "+420 100 010 203")
        self.assertEqual(sport.teacher_mobile_phone, "+420 100 040 506")

    def test_padding_is_trimmed_except_in_ids(self):
        subject = SubjectInfo.from_json({
            "SubjectID": " 7", "SubjectName": " Dějepis ", "SubjectAbbrev": "D ", "TeacherID": " U1",
            "TeacherName": " Mgr. Karel Malý", "TeacherAbbrev": "Ma ", "TeacherEmail": " karel.maly@school.example ",
        })
        self.assertEqual((subject.id, subject.name, subject.abbrev), (" 7", "Dějepis", "D"))
        self.assertEqual(subject.teacher, Item(" U1", "Ma", "Mgr. Karel Malý"))
        self.assertEqual(subject.teacher_email, "karel.maly@school.example")

    def test_subject_without_teacher(self):
        subject = SubjectInfo.from_json({"SubjectID": "11", "SubjectName": "Seminář", "TeacherID": None,
                                         "TeacherName": None, "TeacherAbbrev": None})
        self.assertIsNone(subject.teacher)
        self.assertEqual(SubjectInfo.from_json({}), SubjectInfo("", ""))

    def test_to_dict_is_json_serialisable_without_raw(self):
        data = self.subjects[0].to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data, {
            "id": " 2", "name": "Český jazyk a literatura", "abbrev": "Čj",
            "teacher": {"id": "UTX1A", "abbrev": "Nv", "name": "Mgr. Jana Nováková"},
            "teacher_email": "", "teacher_web": "", "teacher_school_phone": "", "teacher_home_phone": "",
            "teacher_mobile_phone": "",
        })
        self.assertNotIn("raw", repr(self.subjects[0]))


class FindSubjectTest(unittest.TestCase):
    def setUp(self):
        self.subjects = parse_subjects(load_fixture(SUBJECTS))

    def test_by_id_abbreviation_or_name(self):
        czech, maths, sport = self.subjects
        self.assertIs(find_subject(self.subjects, " 2"), czech)
        self.assertIs(find_subject(self.subjects, "2"), czech)  # the padding need not be typed
        self.assertIs(find_subject(self.subjects, "m"), maths)
        self.assertIs(find_subject(self.subjects, " tělesná VÝCHOVA "), sport)
        self.assertIs(find_subject(iter(self.subjects), "tv"), sport)
        self.assertIsNone(find_subject(self.subjects, "Chemie"))
        self.assertIsNone(find_subject(self.subjects, ""))
        self.assertIsNone(find_subject([], "M"))

    def test_exact_id_wins_over_other_matches(self):
        clash = [SubjectInfo("M", "Mechanika", "Me"), SubjectInfo(" 5", "Matematika", "M")]
        self.assertIs(find_subject(clash, "M"), clash[0])
        self.assertIs(find_subject(clash, "m"), clash[0])  # the id without padding comes before the abbreviation
        self.assertIs(find_subject(clash, "5"), clash[1])
        self.assertIsNone(find_subject([SubjectInfo("", "Bez id")], ""))
        self.assertIsNone(find_subject([SubjectInfo(" ", "Mezera")], " "))


class SubjectListContractTest(unittest.TestCase):
    def test_missing_list_and_bad_entries(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_subjects({})
        self.assertEqual(raised.exception.problems, ["Missing list 'Subjects'"])
        with self.assertRaises(BakalariContractError) as raised:
            parse_subjects({"Subjects": [{"SubjectID": "1"}, "x"]})
        self.assertEqual(raised.exception.problems, ["1 entry of 'Subjects' is not a JSON object"])

    def test_without_validation_missing_parts_are_skipped(self):
        self.assertEqual(parse_subjects({}, validate=False), [])
        subjects = parse_subjects({"Subjects": [None, {"SubjectID": "1", "SubjectName": "Hudební výchova"}]},
                                  validate=False)
        self.assertEqual([(subject.id, subject.name) for subject in subjects], [("1", "Hudební výchova")])

    def test_non_object_payload_is_an_error_even_without_validation(self):
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                parse_subjects([], validate=validate)


class ThemeTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture(THEMES)
        self.themes = SubjectThemes.from_json(self.data)

    def test_subject_keeps_its_padded_id(self):
        self.assertEqual(self.themes.subject, Item(" 2", "Čj", "Český jazyk a literatura"))
        self.assertEqual(self.themes.raw, self.data)

    def test_themes_in_the_server_order(self):
        self.assertEqual([theme.lesson_label for theme in self.themes.themes], ["1", "2", "12"])
        last = self.themes.themes[-1]
        self.assertEqual(last.date, dt.date(2026, 10, 13))
        self.assertEqual((last.theme, last.note, last.hour_caption), ("Diktát: vyjmenovaná slova po B", "", "2. hod"))
        self.assertEqual((last.start, last.duration), (535, 45))
        self.assertEqual(last.raw, self.data["Themes"][-1])

    def test_start_and_end_times(self):
        first, second, last = self.themes.themes
        self.assertEqual((first.start_time, first.end_time), (dt.time(8, 0), dt.time(8, 45)))
        self.assertEqual((second.start_time, second.end_time), (dt.time(10, 0), dt.time(10, 45)))
        self.assertEqual((last.start_time, last.end_time), (dt.time(8, 55), dt.time(9, 40)))

    def test_documented_shape_without_start_and_duration(self):
        theme = Theme.from_json({"Date": "2019-09-03T00:00:00+02:00", "Theme": "Světový realismus", "Note": "",
                                 "HourCaption": "1. hod", "LessonLabel": "1"})
        self.assertEqual((theme.date, theme.theme, theme.start, theme.duration), (dt.date(2019, 9, 3),
                                                                                 "Světový realismus", None, None))
        self.assertIsNone(theme.start_time)
        self.assertIsNone(theme.end_time)

    def test_clock_times_outside_a_day_are_unknown(self):
        self.assertIsNone(Theme(None, start=-5).start_time)
        self.assertIsNone(Theme(None, start=24 * 60).start_time)
        self.assertEqual(Theme(None, start=1400, duration=45).start_time, dt.time(23, 20))
        self.assertIsNone(Theme(None, start=1400, duration=45).end_time)
        self.assertIsNone(Theme(None, duration=45).end_time)

    def test_zero_start_and_duration_mean_no_time(self):
        # The server sends Start and Duration 0 for an entry without a time (as in /substitutions), not midnight.
        unset = Theme.from_json({"Date": "2026-10-14T00:00:00+02:00", "Theme": "Exkurze", "Start": 0, "Duration": 0})
        self.assertEqual((unset.start, unset.duration), (0, 0))
        self.assertEqual((unset.start_time, unset.end_time), (None, None))
        self.assertIsNone(Theme(None, start=0).start_time)
        self.assertEqual(Theme(None, start=0, duration=45).start_time, dt.time(0, 0))
        self.assertIsNone(Theme(None, start=480, duration=0).end_time)
        self.assertIsNone(Theme(None, start=480, duration=-45).end_time)
        self.assertEqual(Theme(None, start=480, duration=0).start_time, dt.time(8, 0))

    def test_lenient_values(self):
        theme = Theme.from_json({"Date": None, "Theme": " Zlomky ", "Note": None, "HourCaption": " 4. hod ",
                                 "LessonLabel": 7, "Start": "655", "Duration": None})
        self.assertEqual((theme.date, theme.theme, theme.note, theme.hour_caption, theme.lesson_label),
                         (None, "Zlomky", "", "4. hod", "7"))
        self.assertEqual((theme.start, theme.duration, theme.start_time), (655, None, dt.time(10, 55)))

    def test_to_dict_is_json_serialisable_without_raw(self):
        data = self.themes.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data["subject"], {"id": " 2", "abbrev": "Čj", "name": "Český jazyk a literatura"})
        self.assertEqual(data["themes"][0], {
            "date": "2026-09-01", "theme": "Opakování učiva 6. ročníku", "note": "", "hour_caption": "1. hod",
            "lesson_label": "1", "start": 480, "duration": 45,
        })
        self.assertNotIn("raw", repr(self.themes))


class ThemeContractTest(unittest.TestCase):
    def test_subject_and_themes_are_required(self):
        with self.assertRaises(BakalariContractError) as raised:
            SubjectThemes.from_json({"Subject": None})
        self.assertEqual(raised.exception.problems, ["Missing list 'Themes'", "Missing object 'Subject'"])
        with self.assertRaises(BakalariContractError) as raised:
            SubjectThemes.from_json({"Subject": {"Id": "1"}, "Themes": [1]})
        self.assertEqual(raised.exception.problems, ["1 entry of 'Themes' is not a JSON object"])

    def test_without_validation_missing_parts_become_empty(self):
        themes = SubjectThemes.from_json({"Subject": None, "Themes": [None, {"Theme": "Opakování"}]}, validate=False)
        self.assertEqual(themes.subject, Item("", "", ""))
        self.assertEqual([theme.theme for theme in themes.themes], ["Opakování"])

    def test_non_object_payload_is_an_error_even_without_validation(self):
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                SubjectThemes.from_json(None, validate=validate)


class SubjectsEndpointTest(unittest.TestCase):
    def test_subjects(self):
        client, transport = logged_in_client(json_response(200, load_fixture(SUBJECTS)))
        subjects = client.subjects()
        call = transport.calls[1]
        self.assertEqual((call.method, call.api_path, call.query, call.body), ("GET", "/api/3/subjects", {}, None))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(subjects, parse_subjects(load_fixture(SUBJECTS)))

    def test_subjects_validation_can_be_disabled(self):
        client, _ = logged_in_client(json_response(200, {"Subjects": None}), json_response(200, {"Subjects": None}))
        with self.assertRaises(BakalariContractError):
            client.subjects()
        self.assertEqual(client.subjects(validate=False), [])

    def test_missing_module_raises_permission_error(self):
        client, _ = logged_in_client(FORBIDDEN, FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.subjects()
        with self.assertRaises(BakalariPermissionError):
            client.subject_themes("10")


class SubjectThemesEndpointTest(unittest.TestCase):
    def themes_client(self, count=1):
        return logged_in_client(*[json_response(200, load_fixture(THEMES))] * count)

    def test_space_padded_id_is_percent_encoded(self):
        client, transport = self.themes_client()
        themes = client.subject_themes(" 2")
        call = transport.calls[1]
        self.assertEqual((call.method, call.url), ("GET", BASE_URL + "/api/3/subjects/themes/%202"))
        self.assertEqual(call.api_path, "/api/3/subjects/themes/%202")
        self.assertEqual(themes, SubjectThemes.from_json(load_fixture(THEMES)))

    def test_special_characters_are_percent_encoded_in_the_path(self):
        client, transport = self.themes_client(3)
        client.subject_themes("QWRTZB[KLM")
        client.subject_themes("a {b}-_(c)")
        client.subject_themes("Čj")
        self.assertEqual([call.api_path for call in transport.api_calls], [
            "/api/3/subjects/themes/QWRTZB%5BKLM", "/api/3/subjects/themes/a%20%7Bb%7D-_%28c%29",
            "/api/3/subjects/themes/%C4%8Cj",
        ])

    def test_ids_a_path_segment_would_alter_use_the_query_string_form(self):
        # %2F is decoded before routing, a dot makes the segment a file name ("." and ".." even another endpoint, as
        # quote() leaves dots alone) and Windows path rules drop a trailing space.
        ids = ["a/b", "Př.", "1.5", ".", "..", "2 ", 'a"b', "a|b"]
        client, transport = self.themes_client(len(ids))
        for subject_id in ids:
            client.subject_themes(subject_id)
        calls = transport.api_calls
        self.assertEqual([call.api_path for call in calls], ["/api/3/subjects/themes/get"] * len(ids))
        self.assertEqual([call.query["subjectid"] for call in calls], ids)
        self.assertEqual(calls[3].url, BASE_URL + "/api/3/subjects/themes/get?subjectid=.")
        self.assertEqual(calls[5].url, BASE_URL + "/api/3/subjects/themes/get?subjectid=2+")

    def test_id_with_a_backslash_uses_the_query_string_form(self):
        client, transport = self.themes_client()
        client.subject_themes("Z\\1")
        call = transport.calls[1]
        self.assertEqual(call.url, BASE_URL + "/api/3/subjects/themes/get?subjectid=Z%5C1")
        self.assertEqual((call.api_path, call.query), ("/api/3/subjects/themes/get", {"subjectid": "Z\\1"}))

    def test_ids_with_other_characters_iis_refuses_use_the_query_string_form(self):
        ids = ["A:1", "50%", "a+b", "x&y", "q?", "s*", "<b>", " \\2"]
        client, transport = self.themes_client(len(ids))
        for subject_id in ids:
            client.subject_themes(subject_id)
        calls = transport.api_calls
        self.assertEqual({call.api_path for call in calls}, {"/api/3/subjects/themes/get"})
        self.assertEqual([call.query["subjectid"] for call in calls], ids)

    def test_accepts_a_subject_info_or_an_item(self):
        client, transport = logged_in_client(
            json_response(200, load_fixture(SUBJECTS)), *[json_response(200, load_fixture(THEMES))] * 2
        )
        subject = client.subjects()[0]
        client.subject_themes(subject)
        client.subject_themes(Item("10", "M", "Matematika"))
        self.assertEqual([call.api_path for call in transport.api_calls[1:]],
                         ["/api/3/subjects/themes/%202", "/api/3/subjects/themes/10"])

    def test_empty_id_is_rejected_without_a_request(self):
        client, transport = make_client()
        for empty in ("", None, SubjectInfo("", "Bez id"), Item("", "X", "Bez id")):
            with self.assertRaises(ValueError):
                client.subject_themes(empty)
        self.assertEqual(transport.calls, [])

    def test_unknown_subject_and_contract_errors_propagate(self):
        client, _ = logged_in_client(IIS_404, json_response(200, {"Subject": None, "Themes": []}),
                                     json_response(200, {"Subject": None, "Themes": []}))
        with self.assertRaises(BakalariNotFoundError) as raised:
            client.subject_themes("99")
        self.assertEqual(raised.exception.body, "404 - File or directory not found.")
        with self.assertRaises(BakalariContractError):
            client.subject_themes("99")
        self.assertEqual(client.subject_themes("99", validate=False).themes, ())


if __name__ == "__main__":
    unittest.main()
