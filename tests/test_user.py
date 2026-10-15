import copy
import datetime as dt
import json
import unittest
import urllib.parse

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError, Item
from bakalari.user import ModuleRights, SchoolYear, Semester, StudentInfo, UserProfile, WebModule, WebModules

from .support import BASE_URL, FORBIDDEN, empty_response, json_response, load_fixture, logged_in_client

PARENT = load_fixture("user_parent.json")
STUDENT = load_fixture("user_student.json")
WEB = load_fixture("webmodule.json")
SETTING_MODULES = {"Komens", "Marking", "Timetable", "Homeworks", "ClassBook", "Common", "Emergency"}


def teacher_payload():
    return {
        "UserUID": "7310/UCITEL0007",
        "Class": None,
        "TeacherClasses": [
            {"Id": " 1A", "Abbrev": "1.A ", "Name": "1. A"},
            {"Id": "", "Abbrev": "", "Name": ""},
            None,
            "3.C",
        ],
        "FullName": "Mgr. Mlynářová Ivana",
        "UserType": "teacher",
        "UserTypeText": "učitel",
        "StudyYear": None,
        "EnabledModules": [{"Module": "Komens", "Rights": ["ShowReceivedMessages", "SendMessages"]}],
        "SettingModules": {"Common": {"$type": "CommonModuleSettings"}},
        "Students": None,
    }


class UserProfileParsingTest(unittest.TestCase):
    def setUp(self):
        self.profile = UserProfile.from_json(PARENT)

    def test_parent_profile_fields(self):
        profile = self.profile
        self.assertEqual(profile.uid, "7310/RODIC0042KOCOUR")
        self.assertEqual(profile.full_name, "Kocourek Vilém, 6.E")
        self.assertEqual(profile.full_user_name, "Kocourková Bára")
        self.assertEqual((profile.user_type, profile.user_type_text), ("parents", "rodič"))
        self.assertEqual(profile.school_name, "Základní škola Kocourkov, Mlýnská 7")  # padding removed
        self.assertEqual(profile.school_type, "")  # null
        self.assertEqual(profile.study_year, 6)
        self.assertEqual(profile.school_class, Item(id="2E", abbrev="6.E", name=""))
        self.assertEqual(profile.teacher_classes, ())  # null for parents
        self.assertEqual(profile.campaign_category_code, "eyJzaWQiOiI3MzEwIiwidXQiOjY5LCJzeSI6Nn0=")
        self.assertEqual(profile.raw, PARENT)

    def test_students_of_a_parent_account(self):
        student = self.profile.students[0]
        self.assertEqual(len(self.profile.students), 1)
        self.assertEqual(student, StudentInfo("Kocourek Vilém, 6.E", Item("2E", "6.E", ""), "", 6))
        self.assertEqual(student.raw, PARENT["Students"][0])

    def test_modules_and_rights(self):
        profile = self.profile
        self.assertEqual(len(profile.modules), 11)
        self.assertEqual(profile.module_names[:4], ["Komens", "Absence", "Events", "Marks"])
        self.assertEqual(profile.module_names[-1], "AccessSystem")
        self.assertEqual(profile.modules[2], ModuleRights("Events", ("ShowEvents",)))
        self.assertTrue(profile.has_module("Komens"))
        self.assertTrue(profile.has_module(" komens "))
        self.assertFalse(profile.has_module("Payments"))
        self.assertIn("CanConfirmClassification", profile.rights_of("Marks"))
        self.assertEqual(profile.rights_of("subjects"), ("ShowSubjects", "ShowSubjectThemes"))
        self.assertEqual(profile.rights_of("Payments"), ())
        self.assertTrue(profile.has_right("marks", "predictmarks"))
        self.assertTrue(profile.has_right("AccessSystem", "CanShowStudentPresentAtSchool"))
        self.assertFalse(profile.has_right("Marks", "ShowAbsence"))
        self.assertFalse(profile.has_right("Payments", "ShowClassFund"))

    def test_semester_and_school_year_come_from_the_common_settings(self):
        self.assertEqual(self.profile.semester, Semester("1", dt.date(2026, 9, 1), dt.date(2027, 1, 31)))
        self.assertEqual(
            self.profile.school_year, SchoolYear("2026/27", "2026/27", dt.date(2026, 9, 1), dt.date(2027, 8, 31))
        )

    def test_settings_keep_every_module_setting(self):
        settings = self.profile.settings
        self.assertEqual(set(settings), SETTING_MODULES)
        self.assertEqual(settings["Timetable"]["HoursDefinition"][1]["Start"], 480)
        self.assertEqual(settings["Marking"]["NumberOfDaysClassificationConfirmationNotifications"], 14)
        self.assertEqual(settings["ClassBook"]["AbsenceCalculationPeriod"][1]["SemesterId"], "2")
        self.assertEqual(settings["Emergency"]["$type"], "EmergencyModuleSettings")

    def test_user_type_helpers(self):
        kinds = {
            "parent": self.profile,
            "student": UserProfile.from_json(STUDENT),
            "teacher": UserProfile.from_json(teacher_payload()),
        }
        for kind, profile in kinds.items():
            self.assertEqual([profile.is_parent, profile.is_student, profile.is_teacher],
                             [kind == "parent", kind == "student", kind == "teacher"], kind)

    def test_to_dict_is_json_and_hides_settings_and_raw(self):
        data = self.profile.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertNotIn("settings", data)
        self.assertNotIn("raw", data)
        self.assertEqual(data["semester"], {"id": "1", "start": "2026-09-01", "end": "2027-01-31"})
        self.assertEqual(data["school_year"], {"id": "2026/27", "name": "2026/27", "start": "2026-09-01",
                                               "end": "2027-08-31"})
        self.assertEqual(data["school_class"], {"id": "2E", "abbrev": "6.E", "name": ""})
        self.assertEqual(data["students"][0]["full_name"], "Kocourek Vilém, 6.E")
        self.assertEqual(data["modules"][2], {"module": "Events", "rights": ["ShowEvents"]})
        self.assertNotIn("EmergencyModuleSettings", repr(self.profile))

    def test_profiles_compare_by_value_and_are_hashable(self):
        self.assertEqual(UserProfile.from_json(copy.deepcopy(PARENT)), self.profile)
        self.assertEqual(len({self.profile, UserProfile.from_json(PARENT)}), 1)


class OtherProfilesTest(unittest.TestCase):
    def test_student_profile_of_an_older_server(self):
        profile = UserProfile.from_json(STUDENT)
        self.assertEqual(profile.school_class, Item(id=" 4B", abbrev="4.B", name="4. B"))  # the id stays padded
        self.assertEqual(profile.school_type, "SecondarySchool")
        self.assertEqual((profile.full_user_name, profile.students, profile.teacher_classes), ("", (), ()))
        self.assertEqual(profile.semester, Semester("2", dt.date(2027, 2, 1), dt.date(2027, 8, 31)))
        self.assertIsNone(profile.school_year)
        self.assertEqual(profile.module_names, ["Komens", "Marks", "Timetable"])
        self.assertEqual(set(profile.settings), {"Common"})

    def test_teacher_profile_lists_the_teacher_classes(self):
        profile = UserProfile.from_json(teacher_payload())
        self.assertEqual(profile.teacher_classes, (Item(id=" 1A", abbrev="1.A", name="1. A"),))
        self.assertIsNone(profile.school_class)
        self.assertIsNone(profile.study_year)
        self.assertEqual(profile.students, ())
        self.assertIsNone(profile.semester)

    def test_summer_profile_without_semester_and_modules(self):
        data = copy.deepcopy(PARENT)
        del data["EnabledModules"]
        data["SettingModules"] = {"Komens": data["SettingModules"]["Komens"]}
        profile = UserProfile.from_json(data)
        self.assertEqual((profile.modules, profile.module_names), ((), []))
        self.assertFalse(profile.has_module("Komens"))
        self.assertIsNone(profile.semester)
        self.assertIsNone(profile.school_year)
        profile = UserProfile.from_json({**data, "SettingModules": None, "EnabledModules": None, "Students": None})
        self.assertEqual((profile.settings, profile.modules, profile.students), ({}, (), ()))

    def test_empty_semester_and_school_year_objects_are_none(self):
        data = copy.deepcopy(STUDENT)
        data["SettingModules"]["Common"]["ActualSemester"] = {"SemesterId": None, "From": "0001-01-01T00:00:00+01:00"}
        data["SettingModules"]["Common"]["ActualSchoolYear"] = {}
        profile = UserProfile.from_json(data)
        self.assertIsNone(profile.semester)
        self.assertIsNone(profile.school_year)
        self.assertIsNone(Semester.optional(None))
        self.assertIsNone(SchoolYear.optional("2026/27"))

    def test_lenient_values(self):
        data = {
            "UserType": " parents ",
            "StudyYear": "6",
            "EnabledModules": [
                {"Module": " Komens ", "Rights": [" SendMessages ", None, ""]},
                {"Module": "Events", "Rights": None},
                {"Module": "Marks"},
            ],
        }
        profile = UserProfile.from_json(data)
        self.assertEqual(profile.study_year, 6)
        self.assertTrue(profile.is_parent)
        self.assertEqual(
            profile.modules,
            (ModuleRights("Komens", ("SendMessages",)), ModuleRights("Events"), ModuleRights("Marks")),
        )
        self.assertEqual(profile.uid, "")
        self.assertIsNone(profile.school_class)
        self.assertTrue(profile.modules[0].allows(" sendmessages"))


class UserProfileContractTest(unittest.TestCase):
    def test_a_non_object_payload_is_rejected_even_without_validation(self):
        for payload in ([], None, "parents", 1):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError, msg=repr(payload)):
                    UserProfile.from_json(payload, validate=validate)

    def test_validation_reports_every_problem(self):
        data = {"UserUID": "x", "EnabledModules": {"Module": "Komens"}, "Students": [1], "Class": "6.E",
                "SettingModules": []}
        with self.assertRaises(BakalariContractError) as raised:
            UserProfile.from_json(data)
        problems = raised.exception.problems
        self.assertEqual(len(problems), 5, problems)
        self.assertIn("Missing string 'UserType'", problems)
        self.assertIn("Missing list 'EnabledModules'", problems)
        self.assertIn("Missing object 'Class'", problems)
        self.assertIn("Missing object 'SettingModules'", problems)
        self.assertTrue(any("'Students'" in problem for problem in problems))
        self.assertIn("user profile", str(raised.exception))

    def test_lenient_parsing_ignores_values_of_the_wrong_type(self):
        data = {"UserUID": "x", "EnabledModules": {"Module": "Komens"}, "Students": [1], "Class": "6.E",
                "SettingModules": []}
        profile = UserProfile.from_json(data, validate=False)
        self.assertEqual((profile.uid, profile.user_type), ("x", ""))
        self.assertEqual((profile.modules, profile.students, profile.school_class), ((), (), None))
        self.assertEqual(profile.settings, {})


class UserEndpointTest(unittest.TestCase):
    def test_user_profile_requests_the_user_endpoint(self):
        client, transport = logged_in_client(json_response(200, PARENT))
        profile = client.user_profile()
        self.assertIsInstance(profile, UserProfile)
        self.assertEqual(profile.full_user_name, "Kocourková Bára")
        call = transport.calls[1]
        self.assertEqual((call.method, call.api_path, call.body), ("GET", "/api/3/user", None))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")

    def test_user_profile_validates_unless_told_not_to(self):
        broken = {"UserUID": "x", "EnabledModules": "Komens"}
        client, _ = logged_in_client(json_response(200, broken), json_response(200, broken))
        with self.assertRaises(BakalariContractError):
            client.user_profile()
        self.assertEqual(client.user_profile(validate=False).modules, ())

    def test_enabled_modules_come_from_the_profile(self):
        profile = {"UserType": "parents", "EnabledModules": [{"Module": "Komens"}, {"Module": "Timetable"}]}
        client, transport = logged_in_client(json_response(200, profile), json_response(200, profile))
        self.assertEqual(client.enabled_modules(), ["Komens", "Timetable"])
        self.assertEqual(client.user_profile().user_type, "parents")
        self.assertEqual([call.api_path for call in transport.api_calls], ["/api/3/user", "/api/3/user"])

    def test_enabled_modules_tolerate_an_incomplete_profile(self):
        client, _ = logged_in_client(json_response(200, {"EnabledModules": [{"Module": "Komens", "Rights": []}]}))
        self.assertEqual(client.enabled_modules(), ["Komens"])

    def test_student_at_school(self):
        client, transport = logged_in_client(json_response(200, True), json_response(200, False))
        self.assertIs(client.student_at_school(), True)
        self.assertIs(client.student_at_school(), False)
        self.assertEqual([(call.method, call.api_path) for call in transport.api_calls],
                         [("GET", "/api/3/user/student-at-school")] * 2)

    def test_student_at_school_needs_the_access_system_module(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.student_at_school()

    def test_student_at_school_accepts_only_a_boolean(self):
        client, _ = logged_in_client(json_response(200, "true"), json_response(200, " False "))
        self.assertIs(client.student_at_school(), True)
        self.assertIs(client.student_at_school(), False)
        for payload in ({"AtSchool": True}, 1, None, "yes", []):
            client, _ = logged_in_client(json_response(200, payload))
            with self.assertRaises(BakalariContractError, msg=repr(payload)):
                client.student_at_school()

    def test_web_modules(self):
        client, transport = logged_in_client(json_response(200, WEB))
        modules = client.web_modules()
        self.assertEqual([module.name for module in modules.modules], ["Ankety", "Dokumenty"])
        self.assertEqual(modules.dashboard.url, "next/dash.aspx")
        self.assertEqual((transport.calls[1].method, transport.calls[1].api_path), ("GET", "/api/3/webmodule"))

    def test_web_modules_validate_unless_told_not_to(self):
        client, _ = logged_in_client(json_response(200, {"Dashboard": None}), json_response(200, {"Dashboard": None}))
        with self.assertRaises(BakalariContractError):
            client.web_modules()
        self.assertEqual(client.web_modules(validate=False), WebModules())

    def test_login_token_is_returned_exactly(self):
        client, transport = logged_in_client(json_response(200, " Zk9+a/b=c "))
        self.assertEqual(client.login_token(), " Zk9+a/b=c ")
        self.assertEqual((transport.calls[1].method, transport.calls[1].api_path), ("GET", "/api/3/logintoken"))

    def test_login_token_must_be_a_non_empty_string(self):
        for payload in ({"Token": "secret-token"}, ["secret-token"], None, "", "   "):
            client, _ = logged_in_client(json_response(200, payload))
            with self.assertRaises(BakalariContractError) as raised:
                client.login_token()
            self.assertNotIn("secret-token", str(raised.exception))

    def test_web_login_url_quotes_the_token_as_one_path_segment(self):
        client, transport = logged_in_client(json_response(200, "Ab/c+d=e f?g#h"))
        url = client.web_login_url()
        self.assertEqual(url, BASE_URL + "/api/3/login/Ab%2Fc%2Bd%3De%20f%3Fg%23h?returnUrl=next/dash.aspx")
        parts = urllib.parse.urlsplit(url)
        self.assertEqual(urllib.parse.unquote(parts.path.rsplit("/", 1)[1]), "Ab/c+d=e f?g#h")
        self.assertEqual(transport.calls[1].api_path, "/api/3/logintoken")

    def test_web_login_url_quotes_the_return_url_as_a_query_value(self):
        target = "/HomeWorks/Review?hwId=K1 2&mode=a+b#top"
        client, transport = logged_in_client(json_response(200, "T0KEN"), json_response(200, "T0KEN2"))
        url = client.web_login_url(target)
        self.assertEqual(url, BASE_URL + "/api/3/login/T0KEN?returnUrl=/HomeWorks/Review%3FhwId%3DK1%202%26mode%3Da"
                                         "%2Bb%23top")
        parts = urllib.parse.urlsplit(url)
        self.assertEqual(urllib.parse.parse_qs(parts.query), {"returnUrl": [target]})
        self.assertEqual(parts.fragment, "")
        self.assertEqual(client.web_login_url(""), BASE_URL + "/api/3/login/T0KEN2")
        self.assertEqual(len(transport.api_calls), 2)  # a fresh one-time token for every link

    def test_register_notification_posts_a_null_json_body(self):
        client, transport = logged_in_client(empty_response(204), json_response(200, None))
        self.assertIsNone(client.register_notification("fcm:Ab-1/2+3="))
        client.register_notification("second")
        call = transport.calls[1]
        self.assertEqual((call.method, call.api_path), ("POST", "/api/3/register-notification"))
        self.assertEqual(call.query, {"token": "fcm:Ab-1/2+3="})
        self.assertEqual(call.body, b"null")
        self.assertIsNone(call.json)
        self.assertEqual(call.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(transport.calls[2].query, {"token": "second"})

    def test_register_notification_errors(self):
        client, transport = logged_in_client(json_response(400, {"Message": "The request is invalid."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.register_notification("unknown-token")
        self.assertEqual(raised.exception.status, 400)
        self.assertNotIn("unknown-token", str(raised.exception))  # the query with the push token stays out
        with self.assertRaises(ValueError):
            client.register_notification("")
        self.assertEqual(len(transport.api_calls), 1)


class WebModulesParsingTest(unittest.TestCase):
    def test_modules_and_dashboard(self):
        modules = WebModules.from_json(WEB)
        self.assertEqual(modules.modules, (
            WebModule(name="Ankety", url="next/ankety.aspx", icon_id="ankety"),
            WebModule(name="Dokumenty", url="next/dokumentyPrehled.aspx", icon_id="dokumenty"),
        ))
        self.assertEqual(modules.dashboard, WebModule(name="", url="next/dash.aspx", icon_id=""))
        self.assertIsNone(modules.modules[0].submenu)
        self.assertEqual(modules.modules[1].raw, WEB["WebModules"][1])
        self.assertEqual(modules.raw, WEB)

    def test_submenu_is_kept_as_sent(self):
        entry = {"IconId": "x", "SubMenu": [{"Name": "Přehled", "Url": "next/x.aspx"}], "Url": " next/y.aspx ",
                 "Name": " Výukové zdroje "}
        module = WebModule.from_json(entry)
        self.assertEqual(module.submenu, ({"Name": "Přehled", "Url": "next/x.aspx"},))
        self.assertEqual((module.name, module.url), ("Výukové zdroje", "next/y.aspx"))
        self.assertEqual(module.to_dict()["submenu"], [{"Name": "Přehled", "Url": "next/x.aspx"}])
        self.assertEqual(len({module, WebModule.from_json(entry)}), 1)  # hashable despite the raw list
        self.assertEqual(WebModule.from_json({**entry, "SubMenu": []}).submenu, ())

    def test_contract_and_lenient_parsing(self):
        with self.assertRaises(BakalariContractError):
            WebModules.from_json({})
        with self.assertRaises(BakalariContractError):
            WebModules.from_json({"WebModules": [None, WEB["WebModules"][0]]})
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                WebModules.from_json([], validate=validate)
        lenient = WebModules.from_json({"WebModules": [None, WEB["WebModules"][0]], "Dashboard": "x"}, validate=False)
        self.assertEqual([module.name for module in lenient.modules], ["Ankety"])
        self.assertIsNone(lenient.dashboard)
        self.assertEqual(WebModules.from_json({"WebModules": []}), WebModules())

    def test_to_dict_is_json(self):
        data = WebModules.from_json(WEB).to_dict()
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(data["dashboard"], {"name": "", "url": "next/dash.aspx", "icon_id": "", "submenu": None})
        self.assertNotIn("raw", data)
        self.assertEqual(len(data["modules"]), 2)


if __name__ == "__main__":
    unittest.main()
