import datetime as dt
import json
import unittest

from bakalari import BakalariContractError, BakalariHTTPError, BakalariPermissionError
from bakalari.events import EVENT_SCOPES, Event, EventTime, parse_events
from bakalari.models import Item

from .support import FORBIDDEN, json_response, load_fixture, logged_in_client, text_response

CEST = dt.timezone(dt.timedelta(hours=2))
CET = dt.timezone(dt.timedelta(hours=1))
EVENTS = load_fixture("events.json")
INVALID_DATE = json_response(400, {
    "Message": "The request is invalid.",
    "ModelState": {
        "$type": "HttpError",
        "from": {"$type": "String[]", "$values": ["The value 'not-a-date' is not valid for Nullable`1."]},
    },
})


def events_by_id(name="events.json"):
    return {event.id: event for event in parse_events(load_fixture(name))}


class EventParsingTest(unittest.TestCase):
    def setUp(self):
        self.events = events_by_id()

    def test_events_keep_the_server_order(self):
        self.assertEqual([event.id for event in parse_events(EVENTS)], ["QW3RT", "ZX8CV", "PL4NB", "MT5KL"])

    def test_timed_event(self):
        event = self.events["QW3RT"]
        self.assertEqual(event.title, "Exkurze do hvězdárny")
        self.assertEqual(event.description, "Sraz v 7:40 před školou.\nS sebou svačinu a pití.")
        self.assertEqual(event.note, "")
        self.assertEqual(event.event_type, Item("SA", "škol", "školní akce"))
        self.assertEqual(event.changed, dt.datetime(2026, 10, 1, 14, 5, tzinfo=CEST))
        start, end = dt.datetime(2026, 10, 20, 8, 0, tzinfo=CEST), dt.datetime(2026, 10, 20, 12, 30, tzinfo=CEST)
        self.assertEqual(event.times, (EventTime(False, start, end, start, end, dt.date(2026, 10, 20)),))
        self.assertEqual((event.start, event.end), (start, end))
        self.assertIsNotNone(event.start.tzinfo)
        self.assertFalse(event.whole_day)
        self.assertEqual(event.dates, (dt.date(2026, 10, 20),))

    def test_ids_are_kept_exactly_and_names_trimmed(self):
        event = self.events["QW3RT"]
        self.assertEqual([teacher.id for teacher in event.teachers], ["U  12", "UQX7K"])
        self.assertEqual(event.teachers[0], Item("U  12", "Mo", "Modrá Květoslava"))
        self.assertEqual(event.classes, (Item("2B", "2.B (celá)", "2. B (celá třída)"),))
        self.assertEqual((event.rooms, event.students), ((), ()))
        self.assertEqual((event.class_sets, event.teacher_sets, event.room_sets), ((), (), ()))
        padded = Event.from_json({"Id": " QW3RT ", "Rooms": [{"Id": " 7", "Abbrev": " 105 ", "Name": None}]})
        self.assertEqual((padded.id, padded.rooms), (" QW3RT ", (Item(" 7", "105", ""),)))

    def test_whole_day_event_over_several_days(self):
        event = self.events["ZX8CV"]
        self.assertEqual(len(event.times), 3)
        self.assertTrue(all(time.whole_day for time in event.times))
        self.assertTrue(event.whole_day)
        self.assertEqual([(time.interval_start, time.interval_end) for time in event.times], [(None, None)] * 3)
        self.assertEqual(event.start, dt.datetime(2027, 1, 11, 0, 0, tzinfo=CET))
        self.assertEqual(event.end, dt.datetime(2027, 1, 13, 23, 59, tzinfo=CET))
        self.assertEqual(event.dates, (dt.date(2027, 1, 11), dt.date(2027, 1, 12), dt.date(2027, 1, 13)))
        self.assertEqual([item.abbrev for item in event.classes], ["1.A (celá)", "1.B (celá)"])
        self.assertEqual(event.description, "")

    def test_event_after_midnight_has_open_interval_ends(self):
        event = self.events["PL4NB"]
        first, second = event.times
        self.assertEqual((first.interval_start, first.interval_end), (dt.datetime(2027, 2, 12, 19, tzinfo=CET), None))
        self.assertEqual(first.end, dt.datetime(2027, 2, 12, 23, 59, tzinfo=CET))
        self.assertEqual((second.interval_start, second.interval_end),
                         (None, dt.datetime(2027, 2, 13, 1, 30, tzinfo=CET)))
        self.assertEqual((event.start, event.end),
                         (dt.datetime(2027, 2, 12, 19, tzinfo=CET), dt.datetime(2027, 2, 13, 1, 30, tzinfo=CET)))
        self.assertFalse(event.whole_day)
        self.assertEqual(event.dates, (dt.date(2027, 2, 12), dt.date(2027, 2, 13)))
        self.assertEqual(event.rooms, (Item("TV", "TV1", "Tělocvična"),))
        self.assertEqual(event.classes, ())

    def test_padded_note_and_seven_fractional_digits(self):
        event = self.events["PL4NB"]
        self.assertEqual(event.note, "Pořádá spolek rodičů.")
        self.assertEqual(event.changed, dt.datetime(2026, 10, 10, 8, 15, 0, 123456, tzinfo=CEST))

    def test_students_and_rooms(self):
        event = self.events["MT5KL"]
        self.assertEqual(event.students, (Item("S7Q2W", "", "Vonásek Ondřej"),))
        self.assertEqual(event.rooms, (Item("12", "105", "Učebna 105"),))
        self.assertEqual(event.start, dt.datetime(2026, 11, 5, 16, tzinfo=CET))


class AfterSummerBreakTest(unittest.TestCase):
    def setUp(self):
        self.events = events_by_id("events_after_break.json")

    def test_classes_and_rooms_that_no_longer_exist_are_dropped(self):
        sports_day = self.events["OLD1A"]
        self.assertEqual((sports_day.classes, sports_day.rooms, sports_day.students), ((), (), ()))
        self.assertEqual(sports_day.teachers, (Item("UQX7K", "Ze", "Zelený Bohumil"),))
        self.assertEqual(len(sports_day.raw["Classes"]), 2)

    def test_existing_items_survive_next_to_placeholders(self):
        closing = self.events["OLD2B"]
        self.assertEqual(closing.rooms, (Item("AU", "AU", "Aula"),))
        self.assertEqual(closing.classes, ())
        self.assertEqual(closing.teachers[0].id, "U  12")

    def test_only_placeholders_are_dropped(self):
        event = Event.from_json({"Id": "X", "Classes": [
            {"Id": "", "Abbrev": " ()", "Name": " ()"},
            {"Id": " ", "Abbrev": "", "Name": ""},
            {"Id": "", "Abbrev": "", "Name": "Hosté z partnerské školy"},
            {"Id": "K1", "Abbrev": "", "Name": ""},
            {"Id": "", "Abbrev": "3.C", "Name": ""},
            None,
            "K2",
        ]})
        self.assertEqual(event.classes, (Item("", "", "Hosté z partnerské školy"), Item("K1", "", ""),
                                         Item("", "3.C", "")))


class LenientParsingTest(unittest.TestCase):
    def test_missing_optional_fields_get_defaults(self):
        event = Event.from_json({"Id": "MIN01"})
        self.assertEqual(event, Event(id="MIN01", title=""))
        self.assertEqual((event.description, event.note, event.event_type, event.times, event.changed),
                         ("", "", None, (), None))
        self.assertEqual((event.start, event.end, event.whole_day, event.dates), (None, None, False, ()))

    def test_wrong_types_and_empty_dates_are_tolerated(self):
        event = Event.from_json({
            "Id": None, "Title": None, "Times": [None, {"WholeDay": "true", "StartTime": "garbage",
                                                    "IntervalDate": "0001-01-01T00:00:00"}],
            "EventType": "SA", "Classes": "2B", "Teachers": None, "DateChanged": "",
        })
        self.assertEqual((event.id, event.title, event.event_type, event.classes, event.changed),
                         ("", "", None, (), None))
        self.assertEqual(event.times, (EventTime(whole_day=True),))
        self.assertEqual(event.times[0].date, None)
        self.assertTrue(event.whole_day)
        self.assertEqual(event.dates, ())

    def test_empty_event_type_is_none(self):
        self.assertIsNone(Event.from_json({"Id": "A", "EventType": {"Id": "", "Abbrev": "", "Name": ""}}).event_type)

    def test_entry_date_falls_back_to_the_start(self):
        time = EventTime.from_json({"WholeDay": False, "StartTime": "2026-10-21T10:00:00+02:00"})
        self.assertIsNone(time.interval_date)
        self.assertEqual(time.date, dt.date(2026, 10, 21))

    def test_start_and_end_tolerate_naive_timestamps(self):
        event = Event.from_json({"Id": "A", "Times": [
            {"StartTime": "2026-10-21T10:00:00", "EndTime": "2026-10-21T11:00:00"},
            {"StartTime": "2026-10-20T10:00:00+02:00", "EndTime": "2026-10-20T11:00:00+02:00"},
        ]})
        self.assertEqual(event.start, dt.datetime(2026, 10, 20, 10, tzinfo=CEST))
        self.assertEqual(event.end, dt.datetime(2026, 10, 21, 11))

    def test_start_and_end_compare_instants_across_offsets(self):
        event = Event.from_json({"Id": "A", "Times": [
            {"StartTime": "2026-10-25T01:30:00+01:00", "EndTime": "2026-10-25T02:10:00+01:00"},
            {"StartTime": "2026-10-25T01:45:00+02:00", "EndTime": "2026-10-25T02:20:00+02:00"},
        ]})
        self.assertEqual(event.start, dt.datetime(2026, 10, 25, 1, 45, tzinfo=CEST))
        self.assertEqual(event.end, dt.datetime(2026, 10, 25, 2, 10, tzinfo=CET))


class SerialisationTest(unittest.TestCase):
    def test_to_dict_is_json_serialisable_and_round_trips(self):
        event = events_by_id()["PL4NB"]
        data = event.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertNotIn("raw", data)
        self.assertEqual(data["event_type"], {"id": "SP", "abbrev": "spol", "name": "společenská akce"})
        self.assertEqual(data["times"][0], {
            "whole_day": False, "start": "2027-02-12T19:00:00+01:00", "end": "2027-02-12T23:59:00+01:00",
            "interval_start": "2027-02-12T19:00:00+01:00", "interval_end": None, "interval_date": "2027-02-12",
        })
        self.assertEqual(data["rooms"], [{"id": "TV", "abbrev": "TV1", "name": "Tělocvična"}])
        self.assertEqual(data["changed"], "2026-10-10T08:15:00.123456+02:00")

    def test_every_event_of_the_fixtures_serialises(self):
        for name in ("events.json", "events_after_break.json"):
            for event in parse_events(load_fixture(name)):
                json.dumps(event.to_dict(), ensure_ascii=False)

    def test_raw_keeps_the_server_object_and_is_ignored_by_equality(self):
        event = events_by_id()["QW3RT"]
        self.assertEqual(event.raw["Times"][0]["IntervalDate"], "2026-10-20T00:00:00+02:00")
        self.assertEqual(event.raw, EVENTS["Events"][0])
        self.assertNotIn("raw", repr(event))
        self.assertEqual(event, Event.from_json(dict(EVENTS["Events"][0], Unknown=1)))


class ContractTest(unittest.TestCase):
    def test_non_object_payload_always_raises(self):
        for payload in ([], None, "Events"):
            for validate in (True, False):
                with self.assertRaises(BakalariContractError):
                    parse_events(payload, validate=validate)

    def test_missing_event_list(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_events({"events": []})
        self.assertEqual(raised.exception.problems, ["Missing list 'Events'"])
        self.assertEqual(parse_events({"events": []}, validate=False), [])

    def test_entries_that_are_not_objects(self):
        payload = {"Events": [EVENTS["Events"][0], "QW3RT", None]}
        with self.assertRaises(BakalariContractError) as raised:
            parse_events(payload)
        self.assertIn("2 entries of 'Events' are not JSON objects", raised.exception.problems)
        self.assertEqual([event.id for event in parse_events(payload, validate=False)], ["QW3RT"])

    def test_event_without_times(self):
        payload = {"Events": [{"Id": "NT1ME", "Title": "Bez termínu"}, {"Id": "BAD02", "Times": None}]}
        with self.assertRaises(BakalariContractError) as raised:
            parse_events(payload)
        self.assertEqual(raised.exception.problems,
                         ["Event 'NT1ME': Missing list 'Times'", "Event 'BAD02': Missing list 'Times'"])
        self.assertIn("event list", str(raised.exception))
        self.assertEqual([event.times for event in parse_events(payload, validate=False)], [(), ()])

    def test_valid_fixtures_parse_with_validation(self):
        self.assertEqual(len(parse_events(load_fixture("events_after_break.json"))), 2)
        self.assertEqual(parse_events({"Events": []}), [])


class EventsEndpointTest(unittest.TestCase):
    def test_events_of_the_whole_school_year(self):
        client, transport = logged_in_client(json_response(200, EVENTS))
        events = client.events()
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/api/3/events", {}))
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual([event.id for event in events], ["QW3RT", "ZX8CV", "PL4NB", "MT5KL"])
        self.assertIsInstance(events, list)

    def test_since_is_sent_as_the_from_date(self):
        cases = ((dt.date(2026, 9, 1), "2026-09-01"), (dt.datetime(2026, 9, 1, 15, 30), "2026-09-01"),
                 ("2025-09-01", "2025-09-01"))
        for since, expected in cases:
            client, transport = logged_in_client(json_response(200, {"Events": []}))
            self.assertEqual(client.events(since), [])
            self.assertEqual(transport.api_calls[0].query, {"from": expected})

    def test_scope_selects_the_path(self):
        self.assertEqual(EVENT_SCOPES, ("all", "my", "public"))
        for scope, path in (("all", "/api/3/events"), ("my", "/api/3/events/my"), ("public", "/api/3/events/public")):
            client, transport = logged_in_client(json_response(200, EVENTS))
            self.assertEqual(len(client.events("2026-09-01", scope=scope)), 4)
            self.assertEqual((transport.api_calls[0].api_path, transport.api_calls[0].query),
                             (path, {"from": "2026-09-01"}))

    def test_unknown_scope_is_rejected_before_any_request(self):
        client, transport = logged_in_client()
        for scope in ("mine", "All", ""):
            with self.assertRaises(ValueError):
                client.events(scope=scope)
        self.assertEqual(transport.calls, [])

    def test_missing_module_raises_permission_error(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.events(scope="my")

    def test_invalid_date_raises_http_error(self):
        client, transport = logged_in_client(INVALID_DATE)
        with self.assertRaises(BakalariHTTPError) as raised:
            client.events("not-a-date")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("from", raised.exception.body["ModelState"])
        self.assertEqual(transport.api_calls[0].query, {"from": "not-a-date"})

    def test_validation_can_be_turned_off(self):
        payload = {"Events": [{"Id": "NT1ME", "Title": "Bez termínu"}]}
        client, _ = logged_in_client(json_response(200, payload), json_response(200, payload))
        with self.assertRaises(BakalariContractError):
            client.events()
        self.assertEqual([event.title for event in client.events(validate=False)], ["Bez termínu"])

    def test_non_json_answer_is_a_contract_error(self):
        client, _ = logged_in_client(text_response(200, "<html><title>Přihlášení</title></html>"))
        with self.assertRaises(BakalariContractError):
            client.events()


if __name__ == "__main__":
    unittest.main()
