import json
import unittest
import urllib.parse
from unittest import mock

from bakalari import (
    BakalariConfigError,
    BakalariConnectionError,
    BakalariContractError,
    BakalariHTTPError,
    BakalariNotFoundError,
)
from bakalari import schools as schools_module
from bakalari.schools import DIRECTORY_URL, Municipality, School, SchoolDirectory

from .support import FakeTransport, empty_response, json_response, load_fixture, text_response

MUNICIPALITIES = load_fixture("schools_municipalities.json")
KOCOURKOV = load_fixture("schools_kocourkov.json")
ZALESI = "Nová Ves \N{EN DASH} Zálesí"
NOT_FOUND_PAGE = ('<!DOCTYPE html>\r\n<html>\r\n    <head>\r\n        <title>Prostředek nebyl nalezen.</title>\r\n'
                  "    </head>\r\n    <body><h1>Chyba serveru v aplikaci /api.</h1></body>\r\n</html>")


def school_list(name, *schools):
    """A ``GET /municipality/{name}`` answer with ``(id, name, url)`` schools."""
    entries = [{"id": school_id, "name": school_name, "schoolUrl": url} for school_id, school_name, url in schools]
    return json_response(200, {"name": name, "schools": entries})


def directory(*responses):
    transport = FakeTransport(*responses)
    return SchoolDirectory(transport=transport), transport


def requested_names(transport):
    """The municipality names asked for, decoded from the request paths."""
    return [urllib.parse.unquote(call.path.split("/municipality/", 1)[1]) for call in transport.calls
            if "/municipality/" in call.path]


LHOTA = school_list("Lhota u Kocourkova", ("SYKCAAAAAG", "Základní škola Lhota", "https://zs-lhota.school.example/"))
MLYNEC = school_list(
    "Mlýnec (okr. Kocourkov)",
    ("SYKCAAAAAH", "Základní škola Mlýnec", "https://zs-mlynec.school.example"),
    ("SYKCAAAAAA", "Základní škola Kocourkov, Mlýnská 7", "https://zs-kocourkov.school.example/"),  # listed twice
)


class ModelTest(unittest.TestCase):
    def test_municipality(self):
        municipality = Municipality.from_json({"name": " Zlatá Hora ", "schoolCount": 3})
        self.assertEqual(municipality, Municipality("Zlatá Hora", 3))
        self.assertEqual(municipality.raw, {"name": " Zlatá Hora ", "schoolCount": 3})
        self.assertEqual(Municipality.from_json({"name": None, "schoolCount": "2"}), Municipality("", 2))
        self.assertEqual(Municipality.from_json({}), Municipality("", 0))

    def test_school(self):
        school = School.from_json(KOCOURKOV["schools"][1])
        self.assertEqual(school, School("SYKCAAAAAB", "Gymnázium Kocourkov", "https://gym-kocourkov.school.example/bakaweb"))
        self.assertEqual(school.raw, KOCOURKOV["schools"][1])
        self.assertEqual(School.from_json({"id": " SY1", "name": None, "schoolUrl": None}), School(" SY1", "", ""))

    def test_school_base_url_is_normalized_like_the_client_does_it(self):
        cases = {
            "https://zs-kocourkov.school.example/": "https://zs-kocourkov.school.example",
            "https://zus-horni.school.example/bakalari/": "https://zus-horni.school.example/bakalari",
            "gym.school.example/bakaweb/login": "https://gym.school.example/bakaweb",
            "": "",
            "https://zs-kocourkov.school.example]/": "https://zs-kocourkov.school.example]/",  # malformed: as listed
        }
        for url, expected in cases.items():
            self.assertEqual(School("SY", "Škola", url).base_url, expected, url)

    def test_to_dict_is_json_without_raw(self):
        school = School.from_json(KOCOURKOV["schools"][0])
        data = school.to_dict()
        self.assertEqual(data, {"id": "SYKCAAAAAA", "name": "Základní škola Kocourkov, Mlýnská 7",
                                "url": "https://zs-kocourkov.school.example/"})
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(Municipality("Čertovice", 1).to_dict(), {"name": "Čertovice", "school_count": 1})
        self.assertNotIn("raw", repr(school))


class DirectoryClientTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(DIRECTORY_URL, "https://sluzby.bakalari.cz/api/v1")
        self.assertEqual(schools_module.DEFAULT_MAX_REQUESTS, 15)
        self.assertIn("DEFAULT_MAX_REQUESTS", schools_module.__all__)
        self.assertTrue(all(hasattr(schools_module, name) for name in schools_module.__all__))
        client = SchoolDirectory(transport=FakeTransport())
        self.assertEqual((client.base_url, client.timeout), (DIRECTORY_URL, 30.0))
        self.assertEqual(repr(client), "SchoolDirectory(base_url='https://sluzby.bakalari.cz/api/v1')")

    def test_custom_address_and_timeout(self):
        timeouts = []

        def transport(method, url, headers, body, timeout):
            timeouts.append(timeout)
            return FakeTransport(json_response(200, []))(method, url, headers, body, timeout)

        client = SchoolDirectory(" https://directory.example/api/v1/ ", timeout=5.0, transport=transport)
        self.assertEqual(client.municipalities(), [])
        self.assertEqual(client.base_url, "https://directory.example/api/v1")
        self.assertEqual(timeouts, [5.0])

    def test_an_empty_or_invalid_address_is_a_config_error(self):
        for base_url in ("", "  ", "/", "https://", "http:///api/v1", "ftp://directory.example/api/v1", "https://[::1"):
            with self.assertRaises(BakalariConfigError, msg=base_url):
                SchoolDirectory(base_url, transport=FakeTransport())

    def test_an_address_without_a_scheme_gets_https_like_the_client(self):
        transport = FakeTransport(json_response(200, []))
        client = SchoolDirectory("directory.example/api/v1/", transport=transport)
        self.assertEqual(client.base_url, "https://directory.example/api/v1")
        self.assertEqual(client.municipalities(), [])
        self.assertEqual(transport.calls[0].url, "https://directory.example/api/v1/municipality")
        local = SchoolDirectory(" HTTP://localhost:8080/api/v1 ", transport=transport)
        self.assertEqual(local.base_url, "http://localhost:8080/api/v1")


class MunicipalitiesTest(unittest.TestCase):
    def test_municipalities(self):
        client, transport = directory(json_response(200, MUNICIPALITIES))
        municipalities = client.municipalities()
        self.assertEqual(len(municipalities), 11)
        self.assertEqual(municipalities[0], Municipality("", 3))  # schools filed under no municipality
        self.assertEqual(municipalities[1], Municipality("Čertovice", 1))
        self.assertEqual(municipalities[9].name, ZALESI)
        self.assertEqual(sum(item.school_count for item in municipalities), 18)
        call = transport.calls[0]
        self.assertEqual((call.method, call.url, call.body), ("GET", DIRECTORY_URL + "/municipality", None))
        self.assertEqual(call.headers["Accept"], "application/json")
        self.assertTrue(call.headers["User-Agent"].startswith("bakalari-api-python/"))
        self.assertNotIn("Authorization", call.headers)

    def test_contract(self):
        for payload in ({"name": "Kocourkov"}, None, "Kocourkov"):
            for validate in (True, False):
                client, _ = directory(json_response(200, payload))
                with self.assertRaises(BakalariContractError, msg=repr(payload)):
                    client.municipalities(validate=validate)
        payload = [{"schoolCount": 1}, "Kocourkov", {"name": "Zlatá Hora", "schoolCount": 3}]
        client, _ = directory(json_response(200, payload))
        with self.assertRaises(BakalariContractError) as raised:
            client.municipalities()
        self.assertIn("2 of 3 entries", str(raised.exception))
        client, _ = directory(json_response(200, payload))
        self.assertEqual(client.municipalities(validate=False), [Municipality("", 1), Municipality("Zlatá Hora", 3)])

    def test_xml_answer_is_a_contract_error(self):
        xml = '<?xml version="1.0" encoding="UTF-8"?><ArrayOfmunicipalityInfo></ArrayOfmunicipalityInfo>'
        client, _ = directory(text_response(200, xml, "application/xml; charset=utf-8"))
        with self.assertRaises(BakalariContractError) as raised:
            client.municipalities()
        self.assertIn("application/xml instead of JSON", str(raised.exception))


class SchoolsTest(unittest.TestCase):
    def test_schools_of_a_municipality(self):
        client, transport = directory(json_response(200, KOCOURKOV))
        schools = client.schools("Kocourkov")
        self.assertEqual(len(schools), 6)
        self.assertEqual(schools[0], School("SYKCAAAAAA", "Základní škola Kocourkov, Mlýnská 7",
                                            "https://zs-kocourkov.school.example/"))
        self.assertEqual(schools[1].name, "Gymnázium Kocourkov")  # padding removed
        call = transport.calls[0]
        self.assertEqual((call.method, call.url, call.body), ("GET", DIRECTORY_URL + "/municipality/Kocourkov", None))
        self.assertEqual(call.headers["Accept"], "application/json")
        self.assertNotIn("Authorization", call.headers)

    def test_names_are_trimmed_and_percent_encoded_as_one_segment(self):
        client, transport = directory(school_list("Zlatá Hora"), school_list("Mlýnec (okr. Zlatá Hora)"))
        self.assertEqual(client.schools("  Zlatá Hora "), [])
        client.schools(Municipality("Mlýnec (okr. Zlatá Hora)", 2))
        self.assertEqual(transport.calls[0].path, "/api/v1/municipality/Zlat%C3%A1%20Hora")
        self.assertEqual(transport.calls[1].path, "/api/v1/municipality/Ml%C3%BDnec%20%28okr.%20Zlat%C3%A1%20Hora%29")

    def test_the_unnamed_municipality_cannot_be_listed(self):
        client, transport = directory()
        for name in ("", "   ", Municipality("", 3)):
            with self.assertRaises(ValueError):
                client.schools(name)
        self.assertEqual(transport.calls, [])

    def test_a_dotted_name_falls_back_to_the_part_before_the_dot_after_a_404(self):
        client, transport = directory(empty_response(404), school_list("Mlýnec (okr", ("SY1", "Škola", "https://a.example")))
        self.assertEqual(client.schools("Mlýnec (okr. Kocourkov)"), [School("SY1", "Škola", "https://a.example")])
        self.assertEqual(requested_names(transport), ["Mlýnec (okr. Kocourkov)", "Mlýnec (okr"])

    def test_a_dotted_name_the_service_knows_takes_one_request(self):
        client, transport = directory(school_list("Mlýnec (okr. Kocourkov)", ("SY1", "Škola", "https://a.example")))
        self.assertEqual(len(client.schools("Mlýnec (okr. Kocourkov)")), 1)
        self.assertEqual(len(transport.calls), 1)

    def test_an_unknown_name_raises_not_found(self):
        client, transport = directory(empty_response(404))
        with self.assertRaises(BakalariNotFoundError) as raised:
            client.schools("Nezná mov")
        error = raised.exception
        self.assertEqual((error.method, error.status, error.expected, error.body), ("GET", 404, 200, None))
        self.assertEqual(error.path, DIRECTORY_URL + "/municipality/Nezn%C3%A1%20mov")
        self.assertIn("HTTP 404", str(error))
        client, transport = directory(empty_response(404), empty_response(404))
        with self.assertRaises(BakalariNotFoundError):
            client.schools("Nová.Ves")
        self.assertEqual(requested_names(transport), ["Nová.Ves", "Nová"])
        client, transport = directory(empty_response(404))
        with self.assertRaises(BakalariNotFoundError):
            client.schools(".Ves")
        self.assertEqual(len(transport.calls), 1)

    def test_error_bodies(self):
        client, _ = directory(text_response(404, NOT_FOUND_PAGE))
        with self.assertRaises(BakalariNotFoundError) as raised:
            client.schools("Kocourkov")
        self.assertEqual(raised.exception.body, "Prostředek nebyl nalezen.")
        client, _ = directory(json_response(500, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.schools("Kocourkov")
        self.assertNotIsInstance(raised.exception, BakalariNotFoundError)
        self.assertEqual((raised.exception.status, raised.exception.message), (500, "An error has occurred."))
        client, _ = directory(text_response(503, "Service Unavailable", "text/plain"))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.municipalities()
        self.assertEqual(raised.exception.body, "Service Unavailable")
        client, _ = directory(text_response(502, "<html><body>Bad gateway</body></html>"))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.municipalities()
        self.assertEqual(raised.exception.body, "")

    def test_connection_failure_stays_a_connection_error(self):
        client, _ = directory(BakalariConnectionError("GET https://sluzby.bakalari.cz failed: timed out"))
        with self.assertRaises(BakalariConnectionError):
            client.schools("Kocourkov")

    def test_contract_and_lenient_parsing(self):
        lenient = {"name": "Kocourkov", "schools": [{"id": "SYKC", "name": None, "schoolUrl": None}, "junk", None]}
        client, _ = directory(json_response(200, lenient), json_response(200, lenient))
        with self.assertRaises(BakalariContractError) as raised:
            client.schools("Kocourkov")
        self.assertIn("'schools'", str(raised.exception))
        self.assertEqual(client.schools("Kocourkov", validate=False), [School("SYKC", "", "")])
        client, _ = directory(json_response(200, {"name": "Kocourkov"}), json_response(200, {"name": "Kocourkov"}))
        with self.assertRaises(BakalariContractError):
            client.schools("Kocourkov")
        self.assertEqual(client.schools("Kocourkov", validate=False), [])
        for validate in (True, False):
            client, _ = directory(json_response(200, MUNICIPALITIES))  # e.g. the list for a request without a name
            with self.assertRaises(BakalariContractError):
                client.schools("Kocourkov", validate=validate)


class FindTest(unittest.TestCase):
    def test_find_asks_only_for_the_matching_municipalities(self):
        client, transport = directory(json_response(200, MUNICIPALITIES), json_response(200, KOCOURKOV), LHOTA, MLYNEC)
        found = client.find("kocourkov")
        # "Kocourkov" also answers for "Kocourkov - Dolní Konec", "Kocourkov - Horní Konec" and "Kocourkovice".
        self.assertEqual(requested_names(transport), ["Kocourkov", "Lhota u Kocourkova", "Mlýnec (okr. Kocourkov)"])
        self.assertEqual([school.id for school in found], [
            "SYKCAAAAAA", "SYKCAAAAAB", "SYKCAAAAAC", "SYKCAAAAAD", "SYKCAAAAAE", "SYKCAAAAAF", "SYKCAAAAAG",
            "SYKCAAAAAH",
        ])  # the school listed twice comes once
        self.assertEqual(transport.calls[3].path, "/api/v1/municipality/Ml%C3%BDnec%20%28okr.%20Kocourkov%29")

    def test_find_ignores_case_diacritics_and_spacing_around_dashes(self):
        horni = school_list("Kocourkov - Horní Konec", ("SYKCAAAAAD", "ZUŠ", "https://zus.example"),
                            ("SYKCAAAAAE", "SOŠ", "https://sos.example"))
        cases = [
            ("KOCOURKOV-horni", "Kocourkov - Horní Konec", horni),
            ("certovice", "Čertovice", school_list("Čertovice", ("SY2", "ZŠ Čertovice", "https://c.example"))),
            ("ves - zalesi", ZALESI, school_list(ZALESI)),
            ("VES\N{EM DASH}ZÁLESÍ", ZALESI, school_list(ZALESI)),
            ("  nová   ves  ", ZALESI, school_list(ZALESI)),
        ]
        for text, name, answer in cases:
            client, transport = directory(json_response(200, MUNICIPALITIES), answer)
            client.find(text)
            self.assertEqual(requested_names(transport), [name], text)
        self.assertEqual(transport.calls[1].path, "/api/v1/municipality/Nov%C3%A1%20Ves%20%E2%80%93%20Z%C3%A1les%C3%AD")

    def test_find_without_a_match_returns_an_empty_list(self):
        client, transport = directory(json_response(200, MUNICIPALITIES))
        self.assertEqual(client.find("Neexistující"), [])
        self.assertEqual(len(transport.calls), 1)

    def test_find_needs_a_text(self):
        client, transport = directory()
        for text in ("", "   ", "\N{COMBINING ACUTE ACCENT}", "\t\n"):
            with self.assertRaises(ValueError):
                client.find(text)
        self.assertEqual(transport.calls, [])

    def test_find_refuses_a_text_that_needs_too_many_requests(self):
        client, transport = directory(json_response(200, MUNICIPALITIES))
        with self.assertRaises(ValueError) as raised:
            client.find("o", max_requests=6)
        self.assertIn("matches 10 municipalities, which takes 7 requests (max_requests=6)", str(raised.exception))
        self.assertEqual(len(transport.calls), 1)
        answers = [school_list("Čertovice"), json_response(200, KOCOURKOV), LHOTA, MLYNEC] + [school_list("x")] * 3
        client, transport = directory(json_response(200, MUNICIPALITIES), *answers)
        self.assertEqual(len(client.find("o", max_requests=7)), 8)
        self.assertEqual(requested_names(transport), [
            "Čertovice", "Kocourkov", "Lhota u Kocourkova", "Mlýnec (okr. Kocourkov)", "Mlýnec (okr. Zlatá Hora)",
            ZALESI, "Zlatá Hora",
        ])

    def test_find_asks_for_each_name_when_the_service_matches_names_exactly(self):
        exact = school_list("Kocourkov", ("SYKCAAAAAA", "ZŠ Kocourkov", "https://zs.example"),
                            ("SYKCAAAAAB", "Gymnázium Kocourkov", "https://gym.example"))
        dolni = school_list("Kocourkov - Dolní Konec", ("SYKCAAAAAC", "MŠ Dolní Konec", "https://ms.example"))
        horni = school_list("Kocourkov - Horní Konec", ("SYKCAAAAAD", "ZUŠ", "https://zus.example"),
                            ("SYKCAAAAAE", "SOŠ", "https://sos.example"))
        vesnice = school_list("Kocourkovice", ("SYKCAAAAAF", "ZŠ Kocourkovice", "https://zsk.example"))
        client, transport = directory(json_response(200, MUNICIPALITIES), exact, dolni, horni, vesnice, LHOTA, MLYNEC)
        found = client.find("kocourkov")
        self.assertEqual(requested_names(transport), [
            "Kocourkov", "Kocourkov - Dolní Konec", "Kocourkov - Horní Konec", "Kocourkovice", "Lhota u Kocourkova",
            "Mlýnec (okr. Kocourkov)",
        ])
        self.assertEqual(len(found), 9)

    def test_find_asks_for_the_other_names_of_a_group_whatever_the_directory_order(self):
        payload = [{"name": "Kocourkov - Dolní Konec", "schoolCount": 1}, {"name": "Kocourkov", "schoolCount": 2}]
        exact = school_list("Kocourkov", ("SYKCAAAAAA", "ZŠ Kocourkov", "https://zs.example"),
                            ("SYKCAAAAAB", "Gymnázium Kocourkov", "https://gym.example"))
        dolni = school_list("Kocourkov - Dolní Konec", ("SYKCAAAAAC", "MŠ Dolní Konec", "https://ms.example"))
        client, transport = directory(json_response(200, payload), exact, dolni)
        found = client.find("kocourkov")
        self.assertEqual(requested_names(transport), ["Kocourkov", "Kocourkov - Dolní Konec"])
        self.assertEqual([school.id for school in found], ["SYKCAAAAAA", "SYKCAAAAAB", "SYKCAAAAAC"])

    def test_find_merges_names_that_differ_only_in_case(self):
        payload = [{"name": "Zálesí - Horka", "schoolCount": 1}, {"name": "Zálesí - horka", "schoolCount": 1}]
        answer = school_list("Zálesí - Horka", ("SY1", "ZŠ Horka", "https://h1.example"),
                             ("SY2", "MŠ Horka", "https://h2.example"))
        client, transport = directory(json_response(200, payload), answer)
        self.assertEqual([school.id for school in client.find("horka")], ["SY1", "SY2"])
        self.assertEqual(requested_names(transport), ["Zálesí - Horka"])

    def test_find_uses_the_dot_fallback(self):
        client, transport = directory(json_response(200, MUNICIPALITIES), empty_response(404),
                                      school_list("Mlýnec (okr", ("SY1", "ZŠ Mlýnec", "https://m.example")))
        self.assertEqual([school.id for school in client.find("okr. kocour")], ["SY1"])
        self.assertEqual(requested_names(transport), ["Mlýnec (okr. Kocourkov)", "Mlýnec (okr"])

    def test_find_passes_validation_on(self):
        client, _ = directory(json_response(200, [{"schoolCount": 1}]))
        with self.assertRaises(BakalariContractError):
            client.find("kocourkov")
        client, _ = directory(json_response(200, MUNICIPALITIES), json_response(200, {"name": "Lhota u Kocourkova"}))
        with self.assertRaises(BakalariContractError):
            client.find("lhota")
        client, _ = directory(json_response(200, MUNICIPALITIES), json_response(200, {"name": "Lhota u Kocourkova"}))
        self.assertEqual(client.find("lhota", validate=False), [])


class ModuleFunctionsTest(unittest.TestCase):
    def test_module_functions_use_a_default_directory(self):
        transport = FakeTransport(json_response(200, MUNICIPALITIES), json_response(200, KOCOURKOV),
                                  json_response(200, MUNICIPALITIES), LHOTA)
        with mock.patch.object(schools_module, "urllib_transport", return_value=transport):
            self.assertEqual(len(schools_module.municipalities()), 11)
            self.assertEqual(len(schools_module.schools("Kocourkov")), 6)
            self.assertEqual([school.id for school in schools_module.find("lhota")], ["SYKCAAAAAG"])
        self.assertTrue(all(call.url.startswith(DIRECTORY_URL + "/municipality") for call in transport.calls))
        self.assertEqual(len(transport.calls), 4)


if __name__ == "__main__":
    unittest.main()
