import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariPermissionError
from bakalari.gdpr import Commissioner, Consent, parse_commissioners, parse_consents

from .support import FORBIDDEN, json_response, load_fixture, logged_in_client

CEST = dt.timezone(dt.timedelta(hours=2))
CONSENTS = load_fixture("gdpr_consents.json")
CHILD_CONSENTS = load_fixture("gdpr_child_consents.json")
COMMISSIONERS = load_fixture("gdpr_commissioners.json")


class ConsentParsingTest(unittest.TestCase):
    def test_own_consent(self):
        (consent,) = parse_consents(CONSENTS)
        self.assertEqual(consent.id, "4711")
        self.assertEqual((consent.person_type, consent.person_id), ("parents", "R7KX2"))
        self.assertEqual(consent.created, dt.datetime(2025, 9, 2, 8, 12, 31, tzinfo=CEST))
        self.assertTrue(consent.title.startswith("Souhlas zákonného zástupce"))
        self.assertEqual((consent.personal_data, consent.usage_purpose),
                         ("e-mailová adresa, telefon", "informování rodičů"))
        self.assertTrue(consent.body.endswith("před jeho odvoláním."))
        self.assertEqual((consent.validity, consent.valid_from, consent.valid_to, consent.valid_years),
                         ("5 let", dt.date(2025, 9, 2), None, 5))
        self.assertEqual(consent.state, "Agreed")
        self.assertTrue(consent.is_agreed)
        self.assertEqual((consent.can_agree, consent.can_disagree, consent.can_revoke_request), (False, True, True))

    def test_child_consents(self):
        consents = parse_consents(CHILD_CONSENTS)
        self.assertEqual([consent.id for consent in consents], ["5101", "5102", "5103"])
        self.assertTrue(all(consent.person_type == "student" and consent.person_id == "K9PZ1" for consent in consents))
        photos, results, programme = consents
        self.assertEqual(photos.usage_purpose, "propagace školy")
        self.assertEqual(results.usage_purpose,
                         "zveřejnění výsledků soutěží a olympiád na webu školy a ve školním časopise")
        self.assertEqual((photos.validity, photos.valid_years), ("neomezenou", None))
        self.assertEqual((results.validity, results.valid_years), ("", 5))
        self.assertEqual((programme.personal_data, programme.usage_purpose), ("", ""))
        self.assertEqual((photos.can_disagree, photos.can_revoke_request), (True, False))
        self.assertEqual((programme.can_agree, programme.can_disagree, programme.can_revoke_request),
                         (False, False, False))
        self.assertEqual(programme.created, dt.datetime(2026, 9, 1, 8, 1, 44, tzinfo=CEST))

    def test_missing_optional_fields_get_defaults(self):
        consent = Consent.from_json({"Id": 7, "Rights": None})
        self.assertEqual(consent, Consent(id="7"))
        self.assertEqual((consent.created, consent.valid_from, consent.valid_years, consent.state),
                         (None, None, None, ""))
        self.assertFalse(consent.can_agree or consent.can_disagree or consent.can_revoke_request)
        self.assertFalse(consent.is_agreed)
        self.assertEqual(Consent.from_json({}).id, "")

    def test_lenient_values(self):
        consent = Consent.from_json({
            "Id": "12", "PersonId": " K9PZ1 ", "ValidYears": "3", "ValidFrom": "garbage",
            "ValidTo": "2030-08-31T00:00:00+02:00", "State": " agreed ",
            "Rights": {"CanAgree": "true", "CanDisagree": None},
        })
        self.assertEqual((consent.id, consent.valid_years, consent.valid_from, consent.valid_to),
                         ("12", 3, None, dt.date(2030, 8, 31)))
        self.assertEqual(consent.person_id, " K9PZ1 ")  # ids are kept exactly
        self.assertTrue(consent.is_agreed)
        self.assertEqual((consent.can_agree, consent.can_disagree), (True, False))

    def test_other_states_are_not_agreed(self):
        for state in ("", "Disagreed", "RevokeRequested"):
            self.assertFalse(Consent(id="1", state=state).is_agreed)

    def test_to_dict_round_trips_and_raw_keeps_the_numeric_id(self):
        (consent,) = parse_consents(CONSENTS)
        data = consent.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertNotIn("raw", data)
        self.assertEqual((data["id"], data["valid_from"], data["valid_to"], data["created"]),
                         ("4711", "2025-09-02", None, "2025-09-02T08:12:31+02:00"))
        self.assertEqual(consent.raw["Id"], 4711)
        self.assertEqual(consent.raw["Rights"], {"CanAgree": False, "CanDisagree": True, "CanRevokeRequest": True})
        for child in parse_consents(CHILD_CONSENTS):
            json.dumps(child.to_dict(), ensure_ascii=False)


class CommissionerParsingTest(unittest.TestCase):
    def test_commissioner_contacts(self):
        (commissioner,) = parse_commissioners(COMMISSIONERS)
        self.assertEqual(commissioner, Commissioner(
            id="PV01A", name="Mgr. Ludmila Pokorná", mobile="+420 799 000 111", phone="",
            email="poverenec@skola.example", web="https://poverenec.example", data_box="x7k2mpq",
        ))
        self.assertEqual(commissioner.raw, COMMISSIONERS["Commissioners"][0])

    def test_missing_fields_and_round_trip(self):
        commissioner = Commissioner.from_json({"Id": " 7", "Name": None})
        self.assertEqual((commissioner.id, commissioner.name, commissioner.email, commissioner.data_box),
                         (" 7", "", "", ""))
        data = parse_commissioners(COMMISSIONERS)[0].to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(sorted(data), ["data_box", "email", "id", "mobile", "name", "phone", "web"])

    def test_school_without_commissioners(self):
        self.assertEqual(parse_commissioners({"Commissioners": []}), [])


class ContractTest(unittest.TestCase):
    def test_non_object_payloads_always_raise(self):
        for parse in (parse_consents, parse_commissioners):
            for payload in ([], None, 3):
                for validate in (True, False):
                    with self.assertRaises(BakalariContractError):
                        parse(payload, validate=validate)

    def test_missing_lists(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_consents({"Consents": []})
        self.assertEqual(raised.exception.problems, ["Missing list 'PersonConsents'"])
        self.assertIn("consent list", str(raised.exception))
        with self.assertRaises(BakalariContractError) as raised:
            parse_commissioners({"Commissioners": None})
        self.assertEqual(raised.exception.problems, ["Missing list 'Commissioners'"])
        self.assertEqual(parse_consents({}, validate=False), [])
        self.assertEqual(parse_commissioners({}, validate=False), [])

    def test_entries_that_are_not_objects(self):
        payload = {"PersonConsents": [CONSENTS["PersonConsents"][0], 4711]}
        with self.assertRaises(BakalariContractError) as raised:
            parse_consents(payload)
        self.assertIn("1 entry of 'PersonConsents' is not a JSON object", raised.exception.problems)
        self.assertEqual([consent.id for consent in parse_consents(payload, validate=False)], ["4711"])


class GdprEndpointTest(unittest.TestCase):
    def test_own_consents(self):
        client, transport = logged_in_client(json_response(200, CONSENTS))
        consents = client.consents()
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/gdpr/consents/person", {}))
        self.assertEqual([consent.id for consent in consents], ["4711"])

    def test_child_consents(self):
        client, transport = logged_in_client(json_response(200, CHILD_CONSENTS))
        self.assertEqual(len(client.child_consents()), 3)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("GET", "/api/3/gdpr/consents/person/child"))

    def test_new_consents_count(self):
        client, transport = logged_in_client(json_response(200, 0), json_response(200, 2))
        self.assertEqual(client.new_consents_count(), 0)
        self.assertEqual(client.new_consents_count(), 2)
        self.assertEqual([call.api_path for call in transport.api_calls], ["/api/3/gdpr/consents/person/new"] * 2)
        self.assertEqual({call.method for call in transport.api_calls}, {"GET"})

    def test_new_consents_count_must_be_a_number(self):
        for payload in ({"Count": 1}, None, "many", True):
            client, _ = logged_in_client(json_response(200, payload))
            with self.assertRaises(BakalariContractError):
                client.new_consents_count()

    def test_commissioners(self):
        client, transport = logged_in_client(json_response(200, COMMISSIONERS),
                                             json_response(200, {"Commissioners": []}))
        self.assertEqual([commissioner.name for commissioner in client.gdpr_commissioners()], ["Mgr. Ludmila Pokorná"])
        self.assertEqual(client.gdpr_commissioners(), [])
        self.assertEqual(transport.api_calls[0].api_path, "/api/3/gdpr/commissioners")

    def test_missing_rights_raise_permission_errors(self):
        client, _ = logged_in_client(FORBIDDEN, FORBIDDEN, FORBIDDEN, FORBIDDEN)
        for method in (client.consents, client.child_consents, client.new_consents_count, client.gdpr_commissioners):
            with self.assertRaises(BakalariPermissionError):
                method()

    def test_validation_can_be_turned_off(self):
        client, _ = logged_in_client(json_response(200, {}), json_response(200, {}), json_response(200, {}))
        self.assertEqual(client.consents(validate=False), [])
        self.assertEqual(client.child_consents(validate=False), [])
        with self.assertRaises(BakalariContractError):
            client.gdpr_commissioners()


if __name__ == "__main__":
    unittest.main()
