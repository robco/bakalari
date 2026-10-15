import datetime as dt
import json
import unittest

from bakalari import (
    AttachmentInfo,
    BakalariContractError,
    BakalariError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    Item,
)
from bakalari.homeworks import Homework, parse_homeworks

from .support import (
    BASE_URL,
    FORBIDDEN,
    empty_response,
    json_response,
    load_fixture,
    logged_in_client,
    make_client,
    text_response,
)

FIXTURE = "homeworks.json"
HOMEWORKS = json_response(200, load_fixture(FIXTURE))
PLAIN = "text/plain; charset=utf-8"
DONE = text_response(200, "true", PLAIN)


class HomeworkModelTest(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture(FIXTURE)
        self.homeworks = parse_homeworks(self.data)

    def test_homeworks_keep_the_server_order(self):
        self.assertEqual([homework.id for homework in self.homeworks], ["HW0A1B2C3D", "HW0A1B2C4E", "HW0A1B2B9F"])

    def test_fields(self):
        homework = self.homeworks[0]
        self.assertEqual((homework.start, homework.end), (dt.date(2026, 10, 5), dt.date(2026, 10, 7)))
        self.assertEqual((homework.content, homework.notice), ("Pracovní sešit str. 12, cvičení 3 a 4.", ""))
        self.assertEqual((homework.done, homework.closed, homework.finished, homework.electronic),
                         (False, False, True, False))
        self.assertEqual(homework.hour, 3)
        self.assertEqual(homework.school_class, Item("2F", "6.A", "6. A"))
        self.assertEqual(homework.group, Item("G1", "6.A", "celá třída"))
        self.assertEqual(homework.subject, Item(" 2", "Čj", "Český jazyk a literatura"))
        self.assertEqual(homework.teacher, Item("UTX1A", "Nv", "Mgr. Jana Nováková"))
        self.assertEqual(homework.attachments, ())
        self.assertEqual(homework.raw, self.data["Homeworks"][0])

    def test_multiline_content_keeps_its_line_breaks(self):
        self.assertEqual(self.homeworks[1].content,
                         "Vypracujte úlohy z přiloženého listu.\nPostup najdete na https://school.example/ukoly/zlomky")

    def test_attachments_keep_padded_ids(self):
        pdf, image = self.homeworks[1].attachments
        self.assertEqual(pdf, AttachmentInfo("UAB  3XYZQ", "zlomky.pdf", "application/pdf", 48213))
        self.assertEqual((image.id, image.name, image.content_type, image.size),
                         ("UAB  3XYZR", "obrázek.jpg", "image/jpeg", 0))
        self.assertEqual(pdf.raw, self.data["Homeworks"][1]["Attachments"][0])
        self.assertTrue(self.homeworks[1].electronic)

    def test_is_active_follows_closed(self):
        self.assertEqual([homework.is_active for homework in self.homeworks], [True, True, False])
        closed = self.homeworks[2]
        self.assertEqual((closed.done, closed.closed, closed.finished), (True, True, True))

    def test_legacy_shape_without_finished(self):
        homework = Homework.from_json({
            "ID": "LG7Q2WIKAP", "DateAward": "0001-01-01T00:00:00+01:00", "DateControl": None,
            "DateDone": "0001-01-01T00:00:00+01:00", "DateStart": "2020-05-05T00:00:00+02:00",
            "DateEnd": "2020-05-06T00:00:00+02:00", "Content": "Cvičení 5", "Notice": "", "Done": False,
            "Closed": False, "Electronic": False, "Hour": 8, "Class": {"Id": "7B", "Abbrev": "7.B", "Name": "7. B"},
            "Group": {"Id": "G4", "Abbrev": "SeM", "Name": "Seminář z matematiky"},
            "Subject": {"Id": "31", "Abbrev": "SeM", "Name": "Seminář z matematiky"},
            "Teacher": {"Id": "UKR4Z", "Abbrev": "Kř", "Name": "Křížová Alena"},
            "Attachments": [{"Id": "Q   9BBBBH", "Name": "dokument.pdf", "Type": "application/pdf", "Size": 609435}],
        })
        self.assertFalse(homework.finished)
        self.assertEqual((homework.start, homework.end, homework.hour), (dt.date(2020, 5, 5), dt.date(2020, 5, 6), 8))
        self.assertEqual(homework.attachments[0].id, "Q   9BBBBH")
        self.assertEqual(homework.raw["DateDone"], "0001-01-01T00:00:00+01:00")

    def test_lenient_values(self):
        homework = Homework.from_json({
            "ID": " HW1 ", "DateStart": None, "DateEnd": "garbage", "Content": "  Přečíst kapitolu 2.  ",
            "Notice": None, "Done": "true", "Closed": None, "Hour": None, "Class": None,
            "Group": {"Id": "", "Abbrev": "", "Name": ""}, "Subject": {"Id": " 2", "Abbrev": "Čj ", "Name": None},
            "Attachments": [None, {"Id": "A1", "Name": " a.txt ", "Type": None, "Size": "12"}],
        })
        self.assertEqual(homework.id, " HW1 ")
        self.assertEqual((homework.start, homework.end, homework.content, homework.notice),
                         (None, None, "Přečíst kapitolu 2.", ""))
        self.assertEqual((homework.done, homework.closed, homework.finished, homework.hour), (True, False, False, None))
        self.assertEqual((homework.school_class, homework.group, homework.teacher), (None, None, None))
        self.assertEqual(homework.subject, Item(" 2", "Čj", ""))
        self.assertEqual(homework.attachments, (AttachmentInfo("A1", "a.txt", "", 12),))
        self.assertEqual(Homework.from_json({}), Homework(""))

    def test_to_dict_is_json_serialisable_without_raw(self):
        data = self.homeworks[1].to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(data, {
            "id": "HW0A1B2C4E", "start": "2026-10-08", "end": "2026-10-15",
            "content": "Vypracujte úlohy z přiloženého listu.\nPostup najdete na https://school.example/ukoly/zlomky",
            "notice": "", "done": False, "closed": False, "finished": False, "electronic": True, "hour": 5,
            "school_class": {"id": "2F", "abbrev": "6.A", "name": "6. A"},
            "group": {"id": "G7", "abbrev": "6.A M1", "name": "Matematika 1"},
            "subject": {"id": "10", "abbrev": "M", "name": "Matematika"},
            "teacher": {"id": "UQW7B", "abbrev": "Sv", "name": "Ing. Petr Svoboda"},
            "attachments": [
                {"id": "UAB  3XYZQ", "name": "zlomky.pdf", "content_type": "application/pdf", "size": 48213},
                {"id": "UAB  3XYZR", "name": "obrázek.jpg", "content_type": "image/jpeg", "size": 0},
            ],
        })
        self.assertNotIn("raw", repr(self.homeworks[1]))


class HomeworkContractTest(unittest.TestCase):
    def test_missing_list_and_bad_entries(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_homeworks({"Homework": []})
        self.assertEqual(raised.exception.problems, ["Missing list 'Homeworks'"])
        self.assertIn("homework list", str(raised.exception))
        with self.assertRaises(BakalariContractError) as raised:
            parse_homeworks({"Homeworks": [None, "x", {"ID": "1"}]})
        self.assertEqual(raised.exception.problems, ["2 entries of 'Homeworks' are not JSON objects"])

    def test_without_validation_missing_parts_are_skipped(self):
        self.assertEqual(parse_homeworks({"Homeworks": None}, validate=False), [])
        homeworks = parse_homeworks({"Homeworks": [None, {"ID": "1"}]}, validate=False)
        self.assertEqual([homework.id for homework in homeworks], ["1"])

    def test_non_object_payload_is_an_error_even_without_validation(self):
        for validate in (True, False):
            with self.assertRaises(BakalariContractError):
                parse_homeworks([{"ID": "1"}], validate=validate)


class HomeworksEndpointTest(unittest.TestCase):
    def test_default_range_is_left_to_the_server(self):
        client, transport = logged_in_client(HOMEWORKS)
        homeworks = client.homeworks()
        call = transport.calls[1]
        self.assertEqual((call.method, call.url, call.body), ("GET", BASE_URL + "/api/3/homeworks", None))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(homeworks, parse_homeworks(load_fixture(FIXTURE)))

    def test_since_and_until_become_from_and_to(self):
        client, transport = logged_in_client(*[HOMEWORKS] * 5)
        client.homeworks(dt.date(2026, 9, 1), "2026-11-14")
        client.homeworks(since=dt.datetime(2026, 9, 1, 7, 30))
        client.homeworks(until=dt.date(2026, 10, 20))
        client.homeworks("", "")
        client.homeworks(since="2026-9-1")  # strings go to the server unchanged
        self.assertEqual([call.query for call in transport.api_calls], [
            {"from": "2026-09-01", "to": "2026-11-14"}, {"from": "2026-09-01"}, {"to": "2026-10-20"}, {},
            {"from": "2026-9-1"},
        ])
        self.assertEqual({call.api_path for call in transport.api_calls}, {"/api/3/homeworks"})

    def test_invalid_date_answers_http_400(self):
        invalid = json_response(400, {"Message": "The request is invalid.", "ModelState": {
            "$type": "HttpError", "from": {"$type": "String[]", "$values": ["The value 'x' is not valid."]}}})
        client, _ = logged_in_client(invalid)
        with self.assertRaises(BakalariHTTPError) as raised:
            client.homeworks("x")
        self.assertEqual((raised.exception.status, raised.exception.message), (400, "The request is invalid."))

    def test_validation_can_be_disabled(self):
        client, _ = logged_in_client(json_response(200, {}), json_response(200, {}))
        with self.assertRaises(BakalariContractError):
            client.homeworks()
        self.assertEqual(client.homeworks(validate=False), [])

    def test_missing_module_raises_permission_error(self):
        client, _ = logged_in_client(FORBIDDEN, FORBIDDEN, FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.homeworks()
        with self.assertRaises(BakalariPermissionError):
            client.active_homeworks_count()
        with self.assertRaises(BakalariPermissionError):
            client.set_homework_done("HW0A1B2C3D")


class ActiveHomeworksCountTest(unittest.TestCase):
    def test_counter(self):
        client, transport = logged_in_client(json_response(200, 10))
        self.assertEqual(client.active_homeworks_count(), 10)
        call = transport.calls[1]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/homeworks/count-actual", {}))

    def test_non_number_is_a_contract_error(self):
        client, _ = logged_in_client(json_response(200, {"Count": 1}), json_response(200, None))
        for _ in range(2):
            with self.assertRaises(BakalariContractError):
                client.active_homeworks_count()


class SetHomeworkDoneTest(unittest.TestCase):
    def test_marks_done_with_an_empty_put(self):
        client, transport = logged_in_client(DONE)
        self.assertIsNone(client.set_homework_done("HW0A1B2C3D"))
        call = transport.calls[1]
        self.assertEqual((call.method, call.url), ("PUT", BASE_URL + "/api/3/homeworks/HW0A1B2C3D/student-done/true"))
        self.assertIsNone(call.body)
        self.assertNotIn("Content-Type", call.headers)
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")

    def test_undo_and_homework_objects(self):
        client, transport = logged_in_client(DONE, DONE)
        homework = parse_homeworks(load_fixture(FIXTURE))[2]
        client.set_homework_done(homework, done=False)
        client.set_homework_done(homework, False)
        self.assertEqual([call.api_path for call in transport.api_calls],
                         ["/api/3/homeworks/HW0A1B2B9F/student-done/false"] * 2)

    def test_ids_are_percent_encoded(self):
        client, transport = logged_in_client(DONE, DONE, DONE)
        client.set_homework_done("QWRTZB[KLM")
        client.set_homework_done("Q   9BBBBH")
        client.set_homework_done("A/B(C)")
        self.assertEqual([call.api_path for call in transport.api_calls], [
            "/api/3/homeworks/QWRTZB%5BKLM/student-done/true",
            "/api/3/homeworks/Q%20%20%209BBBBH/student-done/true",
            "/api/3/homeworks/A%2FB%28C%29/student-done/true",
        ])

    def test_any_success_body_is_accepted_and_ignored(self):
        client, _ = logged_in_client(empty_response(204), json_response(200, True),
                                     text_response(200, "true", "application/json; charset=utf-8"))
        for _ in range(3):
            self.assertIsNone(client.set_homework_done("HW0A1B2C3D"))

    def test_the_body_is_not_decoded_as_json(self):
        bodies = ["OK", "<html><body>true</body></html>", "\ufefftrue", '"true"', "True\r\n"]
        client, _ = logged_in_client(*[text_response(200, body, PLAIN) for body in bodies])
        for _ in bodies:
            self.assertIsNone(client.set_homework_done("HW0A1B2C3D"))

    def test_an_explicit_false_answer_raises(self):
        bodies = ["false", '"false"', " False\r\n", "\ufefffalse"]
        client, transport = logged_in_client(*[text_response(200, body, PLAIN) for body in bodies])
        for done in (True, False, True, False):
            with self.assertRaises(BakalariError) as raised:
                client.set_homework_done("HW0A1B2C3D", done)
            self.assertNotIsInstance(raised.exception, BakalariHTTPError)
            state = "finished" if done else "not finished"
            self.assertIn(f"answered false: the homework was not marked {state}", str(raised.exception))
        self.assertIn("/api/3/homeworks/HW0A1B2C3D/student-done/false", str(raised.exception))
        self.assertEqual(len(transport.api_calls), 4)  # no retry: the server answered

    def test_backslash_id_cannot_be_addressed(self):
        page = text_response(404, "<html><head><title>404 - File or directory not found.</title></head></html>")
        client, transport = logged_in_client(page)
        with self.assertRaises(BakalariNotFoundError):
            client.set_homework_done("7HJKLM\\NOP")
        self.assertEqual(transport.calls[1].api_path, "/api/3/homeworks/7HJKLM%5CNOP/student-done/true")

    def test_unexpected_status_raises(self):
        client, _ = logged_in_client(json_response(500, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.set_homework_done("HW0A1B2C3D")
        self.assertEqual((raised.exception.method, raised.exception.status), ("PUT", 500))
        self.assertEqual(raised.exception.expected, (200, 204))

    def test_empty_id_is_rejected_without_a_request(self):
        client, transport = make_client()
        for empty in ("", None, Homework("")):
            with self.assertRaises(ValueError):
                client.set_homework_done(empty)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
