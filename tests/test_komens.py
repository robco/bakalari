import base64
import copy
import datetime as dt
import io
import json
import tempfile
import time
import unittest
import urllib.parse
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from bakalari import (
    AttachmentInfo,
    BakalariContractError,
    BakalariError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    HttpResponse,
)
from bakalari.komens import (
    MESSAGE_FOLDERS,
    AttachmentFile,
    Message,
    MessagePerson,
    MessageRecipient,
    MessageTypes,
    Recipient,
    Sender,
    parse_message,
    parse_messages,
)

from .support import (
    FORBIDDEN,
    binary_response,
    empty_response,
    json_response,
    load_fixture,
    logged_in_client,
    text_response,
)

CEST = dt.timezone(dt.timedelta(hours=2))
RECEIVED = load_fixture("komens_received.json")
SENT = load_fixture("komens_sent.json")
SENT_DETAIL = load_fixture("komens_sent_detail.json")
RECEIVED_DETAIL = load_fixture("komens_received_detail.json")
MESSAGE_TYPES = load_fixture("komens_message_types.json")
REPLY_TYPES = load_fixture("komens_message_types_reply.json")
SEND_KEYS = [
    "MessageType", "Title", "Text", "RecipientType", "Recipients", "Lifetime", "DateFrom", "DateTo",
    "PreviousMessageId", "CopyForClassTeacher", "CopyForParent", "EmailNotification", "SendAsDirector",
    "RequireConfirmation", "TypeOfRatingId", "Scale", "Attachments", "DraftDate",
]
SENT_OK = json_response(200, {"Message": ""})
ATTACHMENT_ID = "ATT{7Q}x/2026 10 12=AbCdEfGhIjKlMnOpQrSt"
QUOTED_ATTACHMENT_ID = "ATT%7B7Q%7Dx%2F2026%2010%2012%3DAbCdEfGhIjKlMnOpQrSt"


def received_messages():
    return parse_messages(RECEIVED)


def content_disposition(name):
    encoded = base64.b64encode(name.encode("utf-8")).decode("ascii")
    return f"attachment; name=\"=?utf-8?B?{encoded}?=\"; filename*=utf-8''{urllib.parse.quote(name)}"


def split_multipart(call):
    """The boundary, the decoded part header lines and the content of a one-part multipart body."""
    boundary = call.headers["Content-Type"].split("boundary=", 1)[1]
    opening, closing = f"--{boundary}\r\n".encode("ascii"), f"\r\n--{boundary}--\r\n".encode("ascii")
    body = call.body
    if not (body.startswith(opening) and body.endswith(closing)):
        raise AssertionError(f"not a one-part multipart body: {body[:200]!r}")
    head, _, content = body[len(opening):-len(closing)].partition(b"\r\n\r\n")
    return boundary, head.decode("utf-8").split("\r\n"), content


def email_part(call):
    """The single part parsed by the standard library e-mail parser (an independent multipart reader)."""
    header = b"Content-Type: " + call.headers["Content-Type"].encode("ascii") + b"\r\n\r\n"
    parts = list(BytesParser(policy=policy.HTTP).parsebytes(header + call.body).iter_parts())
    if len(parts) != 1:
        raise AssertionError(f"expected one part, got {len(parts)}")
    return parts[0]


class ReceivedMessageTest(unittest.TestCase):
    def setUp(self):
        self.first, self.unconfirmed, self.hidden = received_messages()

    def test_list_keeps_the_server_order(self):
        self.assertEqual([message.id for message in received_messages()], ["400101", "400099", "400087"])

    def test_fields_are_parsed_and_trimmed(self):
        message = self.first
        self.assertEqual((message.id, message.kind, message.message_type),
                         ("400101", "GeneralMessageReceived", "OBECNA"))
        self.assertEqual(message.title, "Třídní schůzky")
        self.assertEqual(message.sent, dt.datetime(2026, 10, 12, 9, 15, 30, tzinfo=CEST))
        self.assertEqual(message.sender, Sender(id="UQX7K", type="teacher", name="Mgr. Petra Ukázková"))
        self.assertEqual(str(message.sender), "Mgr. Petra Ukázková")
        self.assertEqual((message.relevant_name, message.relevant_person_type), ("Mgr. Petra Ukázková", "teacher"))
        self.assertEqual((message.life_time, message.date_from, message.date_to), ("ToRead", None, None))
        self.assertTrue(message.text.startswith("<div><p>Vážení rodiče,</p>"))

    def test_flags(self):
        message = self.first
        self.assertEqual(
            (message.read, message.confirmed, message.can_confirm, message.can_answer, message.hidden,
             message.can_hide, message.can_delete),
            (True, True, False, True, False, True, False),
        )
        self.assertFalse(message.needs_confirmation)
        self.assertTrue(self.unconfirmed.needs_confirmation)
        self.assertEqual((self.unconfirmed.read, self.unconfirmed.life_time), (False, "ToConfirm"))
        self.assertTrue(self.hidden.hidden)

    def test_ids_are_kept_exactly(self):
        self.assertEqual(self.unconfirmed.sender.id, " Z9Q2")
        self.assertEqual(self.first.attachments[0].id, ATTACHMENT_ID)

    def test_attachments_ignore_the_type_marker(self):
        attachment = self.first.attachments[0]
        self.assertEqual(attachment, AttachmentInfo(ATTACHMENT_ID, "Pozvánka na schůzky.pdf", "application/pdf", 48213))
        self.assertEqual(attachment.raw["$type"], "AttachmentInfo")
        self.assertEqual(self.hidden.attachments[0].content_type, "")
        self.assertEqual(self.unconfirmed.attachments, ())

    def test_counts_and_detail_fields_are_absent_from_received_messages(self):
        message = self.first
        self.assertEqual((message.recipients_count, message.recipients_processed_count, message.attachments_count),
                         (None, None, None))
        self.assertEqual((message.recipients, message.recipients_processed, message.persons), ((), (), ()))

    def test_raw_keeps_the_server_object(self):
        self.assertEqual(self.first.raw, RECEIVED["Messages"][0])
        self.assertIsNot(self.first.raw, RECEIVED["Messages"][0])

    def test_missing_optional_fields_get_defaults(self):
        message = Message.from_json({"Id": "1"})
        self.assertEqual(message, Message(id="1"))
        self.assertEqual((message.title, message.text, message.plain_text, message.kind), ("", "", "", ""))
        self.assertEqual((message.sent, message.sender, message.attachments), (None, Sender(), ()))
        self.assertFalse(message.read or message.can_answer or message.needs_confirmation)

    def test_nulls_and_garbage_are_parsed_leniently(self):
        message = Message.from_json({
            "Id": 400111, "Title": None, "Text": None, "SentDate": "0001-01-01T00:00:00", "Sender": None,
            "Attachments": [None, "x", {"Id": "A1", "Name": "a.txt"}], "Read": "true", "RecipientsCount": "3",
            "Persons": None, "Recipients": "nothing",
        })
        self.assertEqual((message.id, message.title, message.text, message.sent), ("400111", "", "", None))
        self.assertEqual(message.sender, Sender())
        self.assertEqual([attachment.id for attachment in message.attachments], ["A1"])
        self.assertTrue(message.read)
        self.assertEqual((message.recipients_count, message.recipients, message.persons), (3, (), ()))


class SentMessageTest(unittest.TestCase):
    def test_sent_list_has_counts_and_attachments_without_type_markers(self):
        first, excuse = parse_messages(SENT)
        self.assertEqual(first.kind, "SentMessageWithRecipients")
        self.assertEqual((first.recipients_count, first.recipients_processed_count, first.attachments_count), (1, 1, 1))
        self.assertEqual(first.attachments[0].name, "Lékařská zpráva.jpg")
        self.assertEqual((first.attachments[0].content_type, first.attachments[0].size), ("image/jpeg", 183402))
        self.assertEqual(first.sender, Sender(id="RPX3N", type="parents", name="Eva Příkladná"))
        self.assertTrue(first.can_delete)
        self.assertEqual((excuse.recipients_count, excuse.recipients_processed_count, excuse.attachments_count),
                         (2, 1, 0))

    def test_excuse_period(self):
        excuse = parse_messages(SENT)[1]
        self.assertEqual(excuse.message_type, "OMLUVENKA")
        self.assertEqual(excuse.date_from, dt.datetime(2026, 10, 7, tzinfo=CEST))
        self.assertEqual(excuse.date_to, dt.datetime(2026, 10, 9, 23, 59, 59, tzinfo=CEST))
        self.assertEqual((excuse.life_time, excuse.confirmed, excuse.relevant_name), ("ToConfirm", False, ""))

    def test_detail_has_recipients_and_persons(self):
        message = parse_message(SENT_DETAIL)
        self.assertEqual(message.kind, "SentMessageWithRecipientsDetail")
        self.assertEqual(message.recipients,
                         (MessageRecipient("UQX7K", "teacher"), MessageRecipient("T8M4W", "teacher")))
        processed = message.recipients_processed[0]
        self.assertEqual((processed.id, processed.user_type, processed.parent_persons), ("UQX7K", "teacher", ()))
        self.assertEqual(processed.action_date, dt.datetime(2026, 10, 14, 7, 41, 20, tzinfo=CEST))
        self.assertEqual(processed.raw["ParentPersons"], [])
        self.assertEqual(len(message.persons), 3)

    def test_persons_and_their_names(self):
        message = parse_message(SENT_DETAIL)
        teacher, colleague, parent = message.persons
        self.assertEqual(teacher.full_name, "Mgr. Petra Ukázková")
        self.assertEqual(colleague.full_name, "Ing. Tomáš Vzorník, Ph.D.")
        self.assertEqual((colleague.middle_name, colleague.class_abbreviation), ("", ""))
        self.assertEqual((parent.full_name, str(parent), parent.person_id), ("", "RPX3N", "P{4Q}"))
        self.assertEqual(str(teacher), "Mgr. Petra Ukázková")
        self.assertEqual(MessagePerson("X", degree_behind="Ph.D.").full_name, "Ph.D.")

    def test_person_lookup_by_account_or_person_id(self):
        message = parse_message(SENT_DETAIL)
        self.assertEqual(message.person(message.recipients[1].id).last_name, "Vzorník")
        self.assertEqual(message.person(message.sender.id).user_type, "parents")
        self.assertEqual(message.person("P{4Q}").id, "RPX3N")
        self.assertIsNone(message.person("NOBODY"))
        self.assertIsNone(message.person(""))
        self.assertIsNone(received_messages()[0].person("UQX7K"))

    def test_parent_persons_are_parsed_leniently(self):
        parent = {"RecipientId": "P2", "UserType": "parents", "ActionDate": "2026-10-14T08:00:00+02:00"}
        recipient = MessageRecipient.from_json({
            "RecipientId": "S1", "UserType": "student", "ActionDate": None,
            "ParentPersons": ["P1", parent, {"Id": "P3"}, None],
        })
        self.assertEqual([parent.id for parent in recipient.parent_persons], ["P1", "P2", "P3"])
        self.assertEqual(recipient.parent_persons[1].action_date, dt.datetime(2026, 10, 14, 8, tzinfo=CEST))
        self.assertIsNone(recipient.action_date)
        self.assertEqual(MessageRecipient.from_json({"RecipientId": None, "Id": "P4"}).id, "P4")
        self.assertEqual(MessageRecipient.from_json({"RecipientId": " 5", "Id": "P5"}).id, " 5")


class PlainTextTest(unittest.TestCase):
    def test_html_body_becomes_readable_text(self):
        self.assertEqual(
            received_messages()[0].plain_text,
            "Vážení rodiče,\n\nzveme Vás na třídní schůzky ve čtvrtek 22. 10.\n\n- 17:00 společná část\n"
            "- 18:00 konzultace\n\nProgram je na webu školy (https://skola.example/schuzky).",
        )
        self.assertEqual(parse_message(RECEIVED_DETAIL).plain_text, "Ve středu proběhne sběr papíru.\nDěkujeme.")

    def test_body_with_embedded_images_of_about_a_megabyte_converts_fast(self):
        image = base64.b64encode(bytes(range(256)) * 3000).decode("ascii")
        html = (f'<p>Plakát:</p><p><img src="data:image/png;base64,{image}" alt="plakát" style="width: 100%;"></p>'
                f"<p>Pozvánka</p><img src='data:image/jpeg;base64,{image[:200000]}'><p>Konec</p>")
        message = Message.from_json({"Id": "1", "Text": html})
        self.assertGreater(len(message.text), 1_000_000)
        start = time.perf_counter()
        self.assertEqual(message.plain_text, "Plakát:\n\nPozvánka\n\nKonec")
        self.assertLess(time.perf_counter() - start, 1.0)
        self.assertEqual(len(message.text), len(html))  # the body itself is untouched

    def test_data_uris_with_parameters_and_line_breaks_are_dropped(self):
        image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ\r\nAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        html = f'<p>Graf</p><img src="DATA:image/png;name=graf.png;charset=x;base64,{image}" alt="graf"><p>Konec</p>'
        self.assertEqual(Message.from_json({"Id": "1", "Text": html}).plain_text, "Graf\n\nKonec")
        visible = f"<p>Náhled: data:image/png;name=graf.png;base64,{image}</p><p>Konec</p>"
        self.assertEqual(Message.from_json({"Id": "2", "Text": visible}).plain_text, "Náhled:\n\nKonec")
        untyped = f"<p>Bez typu: data:;base64,{image}</p><p>Konec</p>"  # RFC 2397 allows leaving the type out
        self.assertEqual(Message.from_json({"Id": "3", "Text": untyped}).plain_text, "Bez typu:\n\nKonec")

    def test_terminal_control_characters_are_dropped(self):
        # Raw escape sequences, a bell and backspaces that would hide "schůzka" on a terminal, a NUL and a C1 control.
        body = "<p>Dobrý den\x1b[2J\x1b]0;titulek\x07, schůzka\x08\x08\x08 se ruší\x00\x85</p><p>Tab\tkonec</p>"
        self.assertEqual(Message.from_json({"Id": "1", "Text": body}).plain_text,
                         "Dobrý den[2J]0;titulek, schůzka se ruší\n\nTab konec")

    def test_text_mentioning_data_is_kept(self):
        message = Message.from_json({"Id": "1", "Text": "<p>Odevzdejte data: tabulku a graf.</p>"})
        self.assertEqual(message.plain_text, "Odevzdejte data: tabulku a graf.")


class MessageSerializationTest(unittest.TestCase):
    def test_to_dict_round_trips_through_json(self):
        for message in received_messages() + parse_messages(SENT) + [parse_message(SENT_DETAIL)]:
            data = message.to_dict()
            self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
            self.assertNotIn("raw", data)

    def test_to_dict_contents(self):
        data = received_messages()[0].to_dict()
        self.assertEqual(data["sent"], "2026-10-12T09:15:30+02:00")
        self.assertEqual(data["sender"], {"id": "UQX7K", "type": "teacher", "name": "Mgr. Petra Ukázková"})
        self.assertEqual(data["attachments"][0], {
            "id": ATTACHMENT_ID, "name": "Pozvánka na schůzky.pdf", "content_type": "application/pdf", "size": 48213,
        })
        self.assertEqual(data["text"], received_messages()[0].text)
        detail = parse_message(SENT_DETAIL).to_dict()
        self.assertEqual(detail["recipients_processed"][0]["action_date"], "2026-10-14T07:41:20+02:00")
        self.assertNotIn("raw", detail["persons"][0])

    def test_repr_shortens_a_long_body_and_hides_raw(self):
        message = Message.from_json({"Id": "7", "Title": "Plakát", "Text": "<p>" + "x" * 5000 + "</p>"})
        shown = repr(message)
        self.assertLess(len(shown), 1200)
        self.assertIn("(5007 characters)", shown)
        self.assertIn("title='Plakát'", shown)
        self.assertNotIn("raw", shown)
        self.assertEqual(len(message.to_dict()["text"]), 5007)
        short = Message.from_json({"Id": "8", "Text": "<p>Ahoj</p>"})
        self.assertIn("text='<p>Ahoj</p>'", repr(short))
        self.assertTrue(repr(short).startswith("Message(id='8', kind=''"))
        self.assertIn("text=None", repr(Message(id="9", text=None)))

    def test_models_are_hashable_values(self):
        first, second = received_messages(), received_messages()
        self.assertEqual(first, second)
        self.assertEqual(len({*first, *second}), 3)


class MessageContractTest(unittest.TestCase):
    def assert_problems(self, function, payload, *expected):
        with self.assertRaises(BakalariContractError) as raised:
            function(payload)
        for problem in expected:
            self.assertIn(problem, raised.exception.problems)
        return raised.exception

    def test_message_list_shape(self):
        self.assert_problems(parse_messages, [], "The Komens message list must be a JSON object")
        self.assert_problems(parse_messages, {}, "Missing list 'Messages'")
        self.assert_problems(parse_messages, {"Messages": None}, "Missing list 'Messages'")
        error = self.assert_problems(
            parse_messages, {"Messages": [{"Title": "bez Id"}, 5, {"Id": "2", "Sender": "x", "Attachments": {}}]},
            "1 entry of 'Messages' is not a JSON object", "Message #1 has no Id",
            "Message '2': 'Sender' is not a JSON object", "Message '2': 'Attachments' is not a list",
        )
        self.assertIn("Komens message list violates its contract", str(error))
        self.assert_problems(parse_messages, {"Messages": [{"Id": "3", "Persons": [1, 2]}]},
                             "Message '3': 2 entries of 'Persons' are not JSON objects")

    def test_message_list_without_validation_is_lenient(self):
        self.assertEqual(parse_messages({}, validate=False), [])
        messages = parse_messages({"Messages": [{"Title": "bez Id"}, 5, {"Id": "2", "Attachments": {}}]},
                                  validate=False)
        self.assertEqual([(message.id, message.title, message.attachments) for message in messages],
                         [("", "bez Id", ()), ("2", "", ())])
        with self.assertRaises(BakalariContractError):
            parse_messages(["not", "an", "object"], validate=False)

    def test_null_nested_values_are_accepted(self):
        payload = {"Messages": [{"Id": "1", "Sender": None, "Attachments": None, "Persons": None}]}
        self.assertEqual(parse_messages(payload)[0].attachments, ())

    def test_message_detail_shape(self):
        self.assert_problems(parse_message, {"Messages": []}, "Missing object 'Message'")
        self.assert_problems(parse_message, {"Message": {"Title": "x"}}, "The message has no Id")
        self.assert_problems(parse_message, {"Message": {"Id": "1", "Recipients": "x"}},
                             "The message: 'Recipients' is not a list")
        self.assertEqual(parse_message({"Message": {"Title": "x"}}, validate=False).title, "x")
        for payload in ({"Message": None}, {}, "text"):
            with self.assertRaises(BakalariContractError):
                parse_message(payload, validate=False)


class MessageTypesTest(unittest.TestCase):
    def setUp(self):
        self.types = MessageTypes.from_json(MESSAGE_TYPES)

    def test_types_and_recipient_types(self):
        general, excuse = self.types.types
        self.assertEqual((general.code, general.name, general.super_type), ("OBECNA", "Obecná zpráva", "Message"))
        self.assertEqual((general.has_title, general.show_email_notification, general.show_confirmation),
                         (True, True, True))
        self.assertEqual((excuse.code, excuse.has_title, excuse.show_confirmation), ("OMLUVENKA", False, False))
        self.assertEqual([item.code for item in general.recipient_types], ["U", "UV", "VS"])
        self.assertEqual([item.selection for item in general.recipient_types], ["ONE", "ZERO", "MULTI"])
        self.assertEqual((str(general), str(general.recipient_types[1])), ("Obecná zpráva", "učitelé - všichni"))

    def test_copy_flags(self):
        teacher, everyone, management = self.types.types[0].recipient_types
        self.assertEqual(
            (teacher.show_copy_for_class_teacher, teacher.show_copy_for_director, teacher.show_copy_for_parent,
             teacher.show_copy_for_student),
            (False, False, True, False),
        )
        self.assertTrue(everyone.show_copy_for_director)
        self.assertTrue(management.show_copy_for_class_teacher and management.show_copy_for_student)

    def test_recipients(self):
        teacher = self.types.types[0].recipient_types[0]
        self.assertEqual(teacher.recipients[0], Recipient("UQX7K", "Petra Ukázková Mgr.", "Ukázková Petra, Mgr."))
        self.assertEqual(teacher.recipients[2].code, " 9KX")
        self.assertEqual(str(teacher.recipients[1]), "Vzorník Tomáš, Ing., Ph.D.")
        self.assertEqual(len(self.types.recipients), 4)
        self.assertFalse(any(recipient.is_default for recipient in self.types.recipients))
        self.assertEqual(self.types.recipients[0].raw, MESSAGE_TYPES["Recipients"][0])

    def test_selection_helpers(self):
        teacher, everyone, management = self.types.types[0].recipient_types
        self.assertTrue(teacher.needs_recipients)
        self.assertFalse(everyone.needs_recipients)
        self.assertTrue(management.needs_recipients)
        self.assertEqual([recipient.code for recipient in management.default_recipients], ["RS"])
        self.assertEqual(teacher.default_recipients, ())
        self.assertEqual(self.types.types[1].recipient_types[0].default_recipients[0].code, "UQX7K")

    def test_lookups(self):
        self.assertIs(self.types.message_type("OBECNA"), self.types.types[0])
        self.assertIs(self.types.message_type("omluvenka"), self.types.types[1])
        self.assertIs(self.types.message_type("Obecná zpráva"), self.types.types[0])
        self.assertIsNone(self.types.message_type("HODNOCENI"))
        self.assertIsNone(self.types.message_type(""))
        general = self.types.types[0]
        self.assertEqual(general.recipient_type("uv").name, "učitelé - všichni")
        self.assertIsNone(general.recipient_type("X"))
        teacher = general.recipient_type("U")
        self.assertEqual(teacher.recipient("T8M4W").name, "Tomáš Vzorník Ing., Ph.D.")
        self.assertEqual(teacher.recipient(" 9KX").name, "Alena Zkušební")
        self.assertEqual(teacher.recipient("9kx").name, "Alena Zkušební")
        self.assertEqual(teacher.recipient("ukázková petra, mgr.").code, "UQX7K")
        self.assertIsNone(teacher.recipient("   "))
        self.assertEqual(self.types.recipient("RS").name, "ředitel školy")

    def test_reply_types(self):
        reply = MessageTypes.from_json(REPLY_TYPES)
        self.assertEqual(len(reply.types), 1)
        recipient_type = reply.types[0].recipient_types[0]
        self.assertEqual((recipient_type.code, recipient_type.selection, recipient_type.recipients), ("OD", "ZERO", ()))
        self.assertFalse(recipient_type.needs_recipients)
        self.assertEqual(reply.recipients, ())

    def test_to_dict_round_trips(self):
        data = self.types.to_dict()
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(data["types"][0]["recipient_types"][0]["recipients"][0]["code"], "UQX7K")
        self.assertNotIn("raw", data)

    def test_contract(self):
        broken = copy.deepcopy(MESSAGE_TYPES)
        broken["MessageTypes"][0]["Abbreviation"] = ""
        broken["MessageTypes"][0]["RecipientsTypes"][1]["Code"] = None
        broken["MessageTypes"][0]["RecipientsTypes"][2]["Recipients"] = {"Code": "RS"}
        broken["MessageTypes"][1]["RecipientsTypes"] = "U"
        broken["Recipients"] = [None]
        with self.assertRaises(BakalariContractError) as raised:
            MessageTypes.from_json(broken)
        self.assertEqual(raised.exception.problems, [
            "Message type #1 has no Abbreviation",
            "Message type #1: a recipient type has no Code",
            "Message type #1, recipient type 'VS': 'Recipients' is not a list",
            "Message type 'OMLUVENKA': 'RecipientsTypes' is not a list",
            "The message types: 1 entry of 'Recipients' is not a JSON object",
        ])
        lenient = MessageTypes.from_json(broken, validate=False)
        self.assertEqual([item.code for item in lenient.types], ["", "OMLUVENKA"])
        self.assertEqual(lenient.types[1].recipient_types, ())
        with self.assertRaises(BakalariContractError):
            MessageTypes.from_json({"Recipients": []})
        with self.assertRaises(BakalariContractError):
            MessageTypes.from_json([], validate=False)
        self.assertEqual(MessageTypes.from_json({}, validate=False), MessageTypes())

    def test_null_recipient_lists_are_accepted(self):
        recipient_types = [{"Code": "UV", "Recipients": None}]
        payload = {"MessageTypes": [{"Abbreviation": "OBECNA", "RecipientsTypes": recipient_types}], "Recipients": None}
        self.assertEqual(MessageTypes.from_json(payload).types[0].recipient_types[0].recipients, ())

    def test_payloads_that_are_not_objects(self):
        with self.assertRaises(BakalariContractError) as raised:
            MessageTypes.from_json("Not found")
        self.assertEqual(raised.exception.problems, ["The Komens message types must be a JSON object"])
        with self.assertRaises(BakalariContractError) as raised:
            MessageTypes.from_json({"MessageTypes": [5, {"Abbreviation": "OBECNA"}]})
        self.assertEqual(raised.exception.problems, ["1 entry of 'MessageTypes' is not a JSON object"])


class MessageEndpointsTest(unittest.TestCase):
    def test_messages_post_an_empty_form(self):
        client, transport = logged_in_client(json_response(200, RECEIVED))
        messages = client.messages()
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("POST", "/api/3/komens/messages/received", {}))
        self.assertEqual(call.body, b"")
        self.assertEqual(call.headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(messages, received_messages())

    def test_every_folder(self):
        responses = [json_response(200, {"Messages": []}) for _ in MESSAGE_FOLDERS]
        client, transport = logged_in_client(*responses)
        for folder in MESSAGE_FOLDERS:
            self.assertEqual(client.messages(folder), [])
        self.assertEqual([call.api_path for call in transport.api_calls],
                         [f"/api/3/komens/messages/{folder}" for folder in MESSAGE_FOLDERS])

    def test_since_sends_date_from(self):
        cases = [dt.date(2026, 10, 1), dt.datetime(2026, 10, 1, 8, 30, tzinfo=CEST), "2026-10-01"]
        client, transport = logged_in_client(*(json_response(200, SENT) for _ in cases))
        for since in cases:
            self.assertEqual(len(client.messages("Sent", since=since)), 2)
        for call in transport.api_calls:
            self.assertEqual((call.api_path, call.form), ("/api/3/komens/messages/sent", {"dateFrom": "2026-10-01"}))

    def test_unknown_folders_are_rejected_before_any_request(self):
        client, transport = logged_in_client()
        with self.assertRaises(ValueError) as raised:
            client.messages("drafts")
        self.assertIn("received, sent, noticeboard, apology, rating", str(raised.exception))
        with self.assertRaises(ValueError):
            client.message("400101", "noticeboard")
        with self.assertRaises(ValueError):
            client.unread_messages_count("sent")
        self.assertEqual(transport.calls, [])

    def test_folder_without_rights_raises_permission_error(self):
        client, _ = logged_in_client(FORBIDDEN)
        with self.assertRaises(BakalariPermissionError):
            client.messages("apology")

    def test_message_list_contract(self):
        client, _ = logged_in_client(json_response(200, {"Messages": None}), json_response(200, {"Messages": None}),
                                     text_response(200, "<html>login</html>"))
        with self.assertRaises(BakalariContractError):
            client.messages()
        self.assertEqual(client.messages(validate=False), [])
        with self.assertRaises(BakalariContractError):
            client.messages()

    def test_message_detail(self):
        client, transport = logged_in_client(json_response(200, RECEIVED_DETAIL), json_response(200, SENT_DETAIL))
        received = client.message("400095")
        sent = client.message(parse_messages(SENT)[0], "sent")
        self.assertEqual((received.id, received.sender.id, received.can_answer), ("400095", " Z9Q2", True))
        self.assertEqual(sent.persons[1].last_name, "Vzorník")
        self.assertEqual([(call.method, call.api_path) for call in transport.api_calls],
                         [("GET", "/api/3/komens/messages/received/400095"),
                          ("GET", "/api/3/komens/messages/sent/400120")])

    def test_message_id_is_percent_encoded(self):
        client, transport = logged_in_client(json_response(200, RECEIVED_DETAIL))
        client.message(" 4/01{x}")
        self.assertEqual(transport.api_calls[0].api_path, "/api/3/komens/messages/received/%204%2F01%7Bx%7D")

    def test_message_detail_contract_and_errors(self):
        client, _ = logged_in_client(json_response(200, {"Message": {"Title": "x"}}),
                                     json_response(200, {"Message": {"Title": "x"}}),
                                     json_response(404, {"Message": "Zpráva nenalezena."}))
        with self.assertRaises(BakalariContractError):
            client.message("1")
        self.assertEqual(client.message("1", validate=False).title, "x")
        with self.assertRaises(BakalariNotFoundError):
            client.message("1")

    def test_unread_counts(self):
        client, transport = logged_in_client(json_response(200, 3), json_response(200, 0), json_response(200, {}))
        self.assertEqual(client.unread_messages_count(), 3)
        self.assertEqual(client.unread_messages_count("noticeboard"), 0)
        with self.assertRaises(BakalariContractError):
            client.unread_messages_count()
        self.assertEqual([(call.method, call.api_path) for call in transport.api_calls[:2]],
                         [("GET", "/api/3/komens/messages/received/unread"),
                          ("GET", "/api/3/komens/messages/noticeboard/unread")])

    def test_mark_read_confirm_hide_and_unhide_put_without_a_body(self):
        client, transport = logged_in_client(empty_response(204), empty_response(200), empty_response(204),
                                             empty_response(204))
        message = received_messages()[1]
        self.assertIsNone(client.mark_message_read("400099"))
        self.assertIsNone(client.confirm_message(message))
        self.assertIsNone(client.hide_message("400099"))
        self.assertIsNone(client.unhide_message(" 400099"))
        self.assertEqual([(call.method, call.api_path, call.body) for call in transport.api_calls], [
            ("PUT", "/api/3/komens/message/400099/mark-as-read", None),
            ("PUT", "/api/3/komens/message/400099/mark-as-confirmed", None),
            ("PUT", "/api/3/komens/message/400099/mark-as-hidden", None),
            ("PUT", "/api/3/komens/message/%20400099/mark-as-unhidden", None),
        ])
        self.assertNotIn("Content-Type", transport.api_calls[0].headers)

    def test_delete(self):
        client, transport = logged_in_client(empty_response(200), empty_response(204), FORBIDDEN)
        client.delete_message("400120")
        client.delete_message(parse_messages(SENT)[0])
        with self.assertRaises(BakalariPermissionError):
            client.delete_message("400108")
        self.assertEqual([(call.method, call.api_path, call.body) for call in transport.api_calls[:2]],
                         [("DELETE", "/api/3/komens/message/400120", None)] * 2)

    def test_message_actions_raise_on_errors_and_reject_empty_ids(self):
        client, transport = logged_in_client(json_response(500, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.mark_message_read("400099")
        self.assertEqual(raised.exception.status, 500)
        actions = (client.mark_message_read, client.confirm_message, client.hide_message, client.unhide_message,
                   client.delete_message, client.message, lambda value: client.message_types(reply_to=value))
        for action in actions:
            with self.assertRaises(ValueError):
                action("")
        with self.assertRaises(ValueError):
            client.confirm_message(Message(id=""))
        self.assertEqual(len(transport.api_calls), 1)

    def test_message_types(self):
        client, transport = logged_in_client(json_response(200, MESSAGE_TYPES), json_response(200, REPLY_TYPES),
                                             json_response(200, REPLY_TYPES))
        self.assertEqual(client.message_types(), MessageTypes.from_json(MESSAGE_TYPES))
        self.assertEqual(client.message_types(reply_to="400101").types[0].recipient_types[0].code, "OD")
        client.message_types(reply_to=Message(id="40/01"))
        self.assertEqual([(call.method, call.api_path) for call in transport.api_calls], [
            ("GET", "/api/3/komens/message-types"),
            ("GET", "/api/3/komens/message-types/reply/400101"),
            ("GET", "/api/3/komens/message-types/reply/40%2F01"),
        ])

    def test_message_types_contract(self):
        client, _ = logged_in_client(json_response(200, {"Recipients": []}), json_response(200, {"Recipients": []}))
        with self.assertRaises(BakalariContractError):
            client.message_types()
        self.assertEqual(client.message_types(validate=False).types, ())

    def test_rating_templates_return_raw_json(self):
        templates = {"Templates": [{"Id": "T1", "Name": "Pochvala"}]}
        client, transport = logged_in_client(json_response(200, templates), FORBIDDEN)
        self.assertEqual(client.rating_templates(), templates)
        with self.assertRaises(BakalariPermissionError):
            client.rating_templates()
        self.assertEqual((transport.api_calls[0].method, transport.api_calls[0].api_path),
                         ("GET", "/api/3/komens/rating-templates"))


class SendMessageTest(unittest.TestCase):
    def test_minimal_message_sends_every_documented_key(self):
        client, transport = logged_in_client(SENT_OK)
        result = client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"],
                                     title="Dotaz", text="<p>Dobrý den</p>")
        self.assertIsNone(result)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("POST", "/api/3/komens/message"))
        self.assertEqual(call.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(list(call.json), SEND_KEYS)
        self.assertEqual(call.json, {
            "MessageType": "OBECNA", "Title": "Dotaz", "Text": "<p>Dobrý den</p>", "RecipientType": "U",
            "Recipients": ["UQX7K"], "Lifetime": None, "DateFrom": None, "DateTo": None, "PreviousMessageId": None,
            "CopyForClassTeacher": False, "CopyForParent": False, "EmailNotification": False,
            "SendAsDirector": False, "RequireConfirmation": False, "TypeOfRatingId": None, "Scale": None,
            "Attachments": [], "DraftDate": None,
        })

    def test_every_option_is_mapped(self):
        types = MessageTypes.from_json(MESSAGE_TYPES)
        general = types.message_type("OBECNA")
        management = general.recipient_type("VS")
        client, transport = logged_in_client(SENT_OK)
        client.send_message(
            message_type=general, recipient_type=management, recipients=management.recipients, text="Text",
            title="Výlet", previous_message_id=received_messages()[0], attachments=("att-1", "att-2"),
            require_confirmation=True, email_notification=True, copy_for_class_teacher=True, copy_for_parent=True,
            send_as_director=True, lifetime="ToConfirm", date_from=dt.date(2026, 10, 20),
            date_to=dt.datetime(2026, 10, 21, 23, 59, 59, tzinfo=CEST), type_of_rating_id="R1", scale=3,
        )
        body = transport.api_calls[0].json
        self.assertEqual(list(body), SEND_KEYS)
        self.assertEqual((body["MessageType"], body["RecipientType"], body["Recipients"]),
                         ("OBECNA", "VS", ["RS", "ZR"]))
        self.assertEqual((body["PreviousMessageId"], body["Attachments"]), ("400101", ["att-1", "att-2"]))
        self.assertEqual((body["DateFrom"], body["DateTo"]), ("2026-10-20", "2026-10-21T23:59:59+02:00"))
        self.assertEqual((body["Lifetime"], body["TypeOfRatingId"], body["Scale"], body["DraftDate"]),
                         ("ToConfirm", "R1", 3, None))
        flags = ("RequireConfirmation", "EmailNotification", "CopyForClassTeacher", "CopyForParent", "SendAsDirector")
        self.assertTrue(all(body[flag] is True for flag in flags))

    def test_single_values_strings_and_extra_keys(self):
        client, transport = logged_in_client(SENT_OK)
        client.send_message(message_type="OBECNA", recipient_type="U", recipients=" 9KX", text="Ahoj",
                            attachments="att-1", date_from="2026-10-20T08:00:00", previous_message_id="400101",
                            extra={"CopyForStudent": True, "DraftDate": "2026-10-15T10:00:00"})
        body = transport.api_calls[0].json
        self.assertEqual((body["Recipients"], body["Attachments"]), ([" 9KX"], ["att-1"]))
        self.assertEqual((body["DateFrom"], body["PreviousMessageId"]), ("2026-10-20T08:00:00", "400101"))
        self.assertEqual((body["CopyForStudent"], body["DraftDate"]), (True, "2026-10-15T10:00:00"))
        self.assertEqual(body["Title"], "")

    def test_codes_are_required(self):
        client, transport = logged_in_client()
        with self.assertRaises(ValueError):
            client.send_message(message_type="", recipient_type="U", text="x")
        with self.assertRaises(ValueError):
            client.send_message(message_type="OBECNA", recipient_type=" ", text="x")
        with self.assertRaises(ValueError):
            client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K", ""], text="x")
        for attachments in ("", ["att-1", " "]):
            with self.assertRaises(ValueError):
                client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"], text="x",
                                    attachments=attachments)
        self.assertEqual(transport.calls, [])

    def test_non_200_answers_raise(self):
        client, _ = logged_in_client(
            json_response(400, {"Message": "The request is invalid."}), FORBIDDEN, empty_response(204)
        )
        with self.assertRaises(BakalariHTTPError) as raised:
            client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"], text="x")
        self.assertEqual(raised.exception.message, "The request is invalid.")
        with self.assertRaises(BakalariPermissionError):
            client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"], text="x")
        with self.assertRaises(BakalariHTTPError):
            client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"], text="x")

    def test_reply_with_implied_recipient(self):
        original = received_messages()[0]
        client, transport = logged_in_client(json_response(200, REPLY_TYPES), SENT_OK)
        self.assertIsNone(client.reply_to_message(original, "<p>Děkuji, přijdu.</p>"))
        types_call, send_call = transport.api_calls
        self.assertEqual((types_call.method, types_call.api_path), ("GET", "/api/3/komens/message-types/reply/400101"))
        self.assertEqual((send_call.method, send_call.api_path), ("POST", "/api/3/komens/message"))
        body = send_call.json
        self.assertEqual(list(body), SEND_KEYS)
        self.assertEqual(
            (body["MessageType"], body["RecipientType"], body["Recipients"], body["PreviousMessageId"]),
            ("OBECNA", "OD", [], "400101"),
        )
        self.assertEqual((body["Title"], body["Text"]), ("Re: Třídní schůzky", "<p>Děkuji, přijdu.</p>"))
        self.assertEqual((body["Attachments"], body["RequireConfirmation"]), ([], False))

    def test_reply_to_a_chosen_recipient_type_names_the_sender(self):
        types = copy.deepcopy(REPLY_TYPES)
        types["MessageTypes"][0]["HasTitle"] = False
        types["MessageTypes"][0]["RecipientsTypes"][0]["TypeOfSelection"] = "ONE"
        client, transport = logged_in_client(json_response(200, types), SENT_OK)
        client.reply_to_message(received_messages()[1], "Potvrzuji.", attachments=["att-9"], require_confirmation=True)
        body = transport.api_calls[1].json
        self.assertEqual((body["Recipients"], body["Title"]), ([" Z9Q2"], ""))
        self.assertEqual((body["Attachments"], body["RequireConfirmation"]), (["att-9"], True))

    def test_reply_titles(self):
        client, transport = logged_in_client(json_response(200, REPLY_TYPES), SENT_OK,
                                             json_response(200, REPLY_TYPES), SENT_OK)
        client.reply_to_message(Message(id="5", title="Re: Výlet", sender=Sender("UQX7K")), "Ano")
        client.reply_to_message(Message(id="5", title="Výlet"), "Ano", title="Odpověď k výletu")
        self.assertEqual([call.json["Title"] for call in transport.api_calls[1::2]], ["Re: Výlet", "Odpověď k výletu"])

    def test_reply_by_id_fetches_the_message_first(self):
        client, transport = logged_in_client(json_response(200, RECEIVED_DETAIL), json_response(200, REPLY_TYPES),
                                             SENT_OK)
        client.reply_to_message("400095", "Rozumím.")
        self.assertEqual([call.api_path for call in transport.api_calls], [
            "/api/3/komens/messages/received/400095", "/api/3/komens/message-types/reply/400095",
            "/api/3/komens/message",
        ])
        self.assertEqual(transport.api_calls[2].json["Title"], "Re: Sběr papíru")

    def test_reply_without_an_allowed_type_raises(self):
        empty = {"MessageTypes": [], "Recipients": []}
        no_recipient_type = {"MessageTypes": [{"Abbreviation": "OBECNA", "RecipientsTypes": []}], "Recipients": []}
        client, transport = logged_in_client(json_response(200, empty), json_response(200, no_recipient_type))
        for _ in range(2):
            with self.assertRaises(BakalariError) as raised:
                client.reply_to_message(received_messages()[0], "x")
            self.assertIn("400101", str(raised.exception))
        self.assertEqual([call.method for call in transport.api_calls], ["GET", "GET"])


class AttachmentDownloadTest(unittest.TestCase):
    def test_download_names_the_file_from_content_disposition(self):
        headers = {"Content-Type": "application/octet-stream",
                   "Content-Disposition": content_disposition("Rozvrh hodin – 6.B.pdf")}
        client, transport = logged_in_client(binary_response(b"%PDF-1.7 data", headers))
        attachment = client.download_attachment(ATTACHMENT_ID)
        self.assertEqual(attachment, AttachmentFile("Rozvrh hodin – 6.B.pdf", "application/pdf", b"%PDF-1.7 data",
                                                    ATTACHMENT_ID))
        self.assertEqual(attachment.size, 13)
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path, call.body),
                         ("GET", f"/api/3/komens/attachment/{QUOTED_ATTACHMENT_ID}", None))
        self.assertEqual(call.headers["Accept"], "*/*")

    def test_ascii_name_parameter(self):
        headers = {"Content-Type": "application/octet-stream", "Content-Disposition": "attachment; name=ukol.pdf"}
        client, _ = logged_in_client(binary_response(b"%PDF", headers))
        attachment = client.download_attachment("A1")
        self.assertEqual((attachment.filename, attachment.content_type), ("ukol.pdf", "application/pdf"))

    def test_fallback_names_and_types(self):
        info = received_messages()[0].attachments[0]
        client, transport = logged_in_client(binary_response(b"1"), binary_response(b"2"),
                                             binary_response(b"3", {"Content-Type": "image/png"}),
                                             HttpResponse(200, {}, b"4"))
        by_info = client.download_attachment(info)
        self.assertEqual((by_info.filename, by_info.content_type, by_info.id),
                         ("Pozvánka na schůzky.pdf", "application/pdf", ATTACHMENT_ID))
        by_id = client.download_attachment("A/2")
        self.assertEqual((by_id.filename, by_id.content_type, by_id.id),
                         ("attachment-A_2", "application/octet-stream", "A/2"))
        self.assertEqual(by_id.safe_filename, "attachment-A_2")
        self.assertEqual(client.download_attachment("A3").content_type, "image/png")
        self.assertEqual(client.download_attachment("A4").content_type, "")
        self.assertEqual(transport.api_calls[0].api_path, f"/api/3/komens/attachment/{QUOTED_ATTACHMENT_ID}")
        self.assertEqual(transport.api_calls[1].api_path, "/api/3/komens/attachment/A%2F2")

    def test_errors(self):
        client, transport = logged_in_client(json_response(500, {"Message": "An error has occurred."}),
                                             json_response(404, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.download_attachment("unknown")
        self.assertEqual(raised.exception.status, 500)
        with self.assertRaises(BakalariNotFoundError):
            client.download_attachment("unknown")
        with self.assertRaises(ValueError):
            client.download_attachment("")
        self.assertEqual(len(transport.api_calls), 2)

    def test_repr_and_to_dict_leave_the_content_out(self):
        attachment = AttachmentFile("a.txt", "text/plain", b"secret content", "A1")
        self.assertNotIn("secret", repr(attachment))
        self.assertEqual(attachment.to_dict(),
                         {"filename": "a.txt", "content_type": "text/plain", "id": "A1", "size": 14})


class AttachmentSaveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.attachment = AttachmentFile("Rozvrh – 6.B.pdf", "application/pdf", b"%PDF content", "A1")

    def test_directory_target_receives_the_file_name(self):
        path = self.attachment.save(self.directory)
        self.assertEqual(path, self.directory / "Rozvrh – 6.B.pdf")
        self.assertEqual(path.read_bytes(), b"%PDF content")

    def test_path_with_a_trailing_separator_is_a_directory(self):
        (self.directory / "sub").mkdir()
        path = self.attachment.save(str(self.directory / "sub") + "/")
        self.assertEqual(path, self.directory / "sub" / "Rozvrh – 6.B.pdf")
        self.assertEqual(path.read_bytes(), b"%PDF content")

    def test_file_target(self):
        target = self.directory / "kopie.pdf"
        self.assertEqual(self.attachment.save(str(target)), target)
        self.assertEqual(target.read_bytes(), b"%PDF content")

    def test_existing_files_are_kept_unless_overwrite(self):
        target = self.directory / "Rozvrh – 6.B.pdf"
        target.write_bytes(b"original")
        with self.assertRaises(FileExistsError) as raised:
            self.attachment.save(self.directory)
        self.assertIn("overwrite=True", str(raised.exception))
        self.assertEqual(raised.exception.filename, str(target))
        with self.assertRaises(FileExistsError):
            self.attachment.save(target)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(self.attachment.save(target, overwrite=True), target)
        self.assertEqual(target.read_bytes(), b"%PDF content")
        self.assertEqual(self.attachment.save(self.directory, True), target)

    def test_missing_parent_directory_is_not_created(self):
        with self.assertRaises(OSError):
            self.attachment.save(self.directory / "missing" / "a.pdf")
        self.assertFalse((self.directory / "missing").exists())

    def test_unsafe_names_are_sanitized(self):
        cases = {
            "../../etc/passwd": "passwd",
            "C:\\Users\\Public\\ukol.txt": "ukol.txt",
            'a<b>:c"d|e?f*.txt': "a_b__c_d_e_f_.txt",
            "tab\there\x00.txt": "tab_here_.txt",
            "...skryty": "skryty",
            " jméno.pdf. ": "jméno.pdf",
            "CON.txt": "_CON.txt",
            "lpt1": "_lpt1",
            "console.txt": "console.txt",
            "..": "attachment-A1",
            "": "attachment-A1",
            ". skryty": "skryty",
            ".. .skryty": "skryty",
            "faktura\u202efdp.exe": "faktura_fdp.exe",  # a right-to-left override would display "fakturaexe.pdf"
            "x\x85y\x9b.txt": "x_y_.txt",  # C1 control characters
            "\ufeffzprava\u200b.txt": "_zprava_.txt",  # format characters
            "radek\u2028dva.txt": "radek_dva.txt",
            "CONIN$": "_CONIN$",
            "conout$.txt": "_conout$.txt",
            "COM0.log": "_COM0.log",
            "lpt\u00b9.txt": "_lpt\u00b9.txt",
            "chybny\udc80nazev.txt": "chybny_nazev.txt",  # a lone surrogate (undecodable byte)
        }
        for name, expected in cases.items():
            self.assertEqual(AttachmentFile(name, id="A1").safe_filename, expected, repr(name))
        self.assertEqual(AttachmentFile("/").safe_filename, "attachment")
        self.assertEqual(AttachmentFile("", id="a/b:c").safe_filename, "attachment-a_b_c")

    def test_crafted_names_never_become_hidden_files(self):
        self.assertEqual(AttachmentFile(". " * 200 + ".bashrc").safe_filename, "bashrc")
        self.assertEqual(AttachmentFile(". " * 201 + "x" * 50 + ".pdf").safe_filename, "x" * 50 + ".pdf")
        self.assertEqual(AttachmentFile(". " * 201 + "x").safe_filename, "x")
        # The shortening cuts inside a run of spaces and dots, which must not stay at the end of the stem.
        self.assertEqual(AttachmentFile("a" + " ." * 200 + "b" * 100 + ".pdf").safe_filename, "a.pdf")

    def test_downloaded_crafted_name_is_saved_as_a_visible_file(self):
        crafted = urllib.parse.quote(". " * 200 + ".bashrc")
        headers = {"Content-Type": "application/octet-stream",
                   "Content-Disposition": f"attachment; filename*=utf-8''{crafted}"}
        client, _ = logged_in_client(binary_response(b"echo x\n", headers))
        path = client.download_attachment("A1").save(self.directory)
        self.assertEqual(path, self.directory / "bashrc")
        self.assertEqual([entry.name for entry in self.directory.iterdir()], ["bashrc"])

    def test_a_failed_write_leaves_no_partial_file(self):
        broken = AttachmentFile("a.txt", content="text instead of bytes")  # writing it to a binary file fails
        with self.assertRaises(TypeError):
            broken.save(self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.attachment.save(self.directory / "a.txt"), self.directory / "a.txt")  # no FileExistsError
        self.assertEqual((self.directory / "a.txt").read_bytes(), b"%PDF content")
        with self.assertRaises(TypeError):
            broken.save(self.directory / "a.txt", overwrite=True)
        self.assertTrue((self.directory / "a.txt").exists())  # a file the caller asked to replace is never deleted

    def test_long_names_are_shortened_keeping_the_extension(self):
        name = AttachmentFile("ř" * 300 + ".pdf").safe_filename
        self.assertLessEqual(len(name.encode("utf-8")), 255)
        self.assertTrue(name.endswith("ř.pdf"))
        without_extension = AttachmentFile("x" * 400).safe_filename
        self.assertEqual(without_extension, "x" * 255)

    def test_sanitized_name_is_used_inside_the_directory(self):
        path = AttachmentFile("../escape.txt", content=b"x").save(self.directory)
        self.assertEqual(path, self.directory / "escape.txt")
        self.assertEqual(path.read_bytes(), b"x")


class AttachmentUploadTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_upload_from_a_path_with_a_non_ascii_name(self):
        path = self.directory / "Omluvenka – Příkladný.pdf"
        content = b"%PDF-1.7\r\n\x00\xff binary\r\n--not-a-boundary\r\n"
        path.write_bytes(content)
        client, transport = logged_in_client(json_response(200, "agepbggdmlp0123456789"))
        self.assertEqual(client.upload_attachment(str(path)), "agepbggdmlp0123456789")
        call = transport.api_calls[0]
        self.assertEqual((call.method, call.api_path), ("POST", "/api/3/komens/attachment"))
        self.assertEqual(call.headers["Accept"], "text/plain, application/json")
        self.assertTrue(call.headers["Content-Type"].startswith("multipart/form-data; boundary="))
        boundary, headers, sent = split_multipart(call)
        self.assertEqual(sent, content)
        self.assertNotIn(boundary.encode("ascii"), content)
        self.assertEqual(headers, [
            'Content-Disposition: form-data; name="attachment"; filename="Omluvenka – Příkladný.pdf"; '
            "filename*=UTF-8''Omluvenka%20%E2%80%93%20P%C5%99%C3%ADkladn%C3%BD.pdf",
            "Content-Type: application/pdf",
        ])
        part = email_part(call)
        self.assertEqual(part.get_param("name", header="content-disposition"), "attachment")
        self.assertEqual(part.get_filename(), "Omluvenka – Příkladný.pdf")
        self.assertEqual(part.get_content_type(), "application/pdf")

    def test_upload_from_bytes_and_file_objects(self):
        path = self.directory / "ukol.bakx"
        path.write_bytes(b"file object content")
        client, transport = logged_in_client(*(text_response(200, value, "text/plain; charset=utf-8")
                                               for value in ('"id-1"', "id-2\r\n", "id-3")))
        self.assertEqual(client.upload_attachment(b"bytes", filename="poznamky.txt", content_type="text/plain"), "id-1")
        self.assertEqual(client.upload_attachment(io.BytesIO(b"buffer"), filename='a"b.bakx'), "id-2")
        with open(path, "rb") as file:
            self.assertEqual(client.upload_attachment(file), "id-3")
        first, second, third = (split_multipart(call) for call in transport.api_calls)
        self.assertEqual(first[1], ['Content-Disposition: form-data; name="attachment"; filename="poznamky.txt"',
                                    "Content-Type: text/plain"])
        self.assertEqual(first[2], b"bytes")
        self.assertEqual(second[1], ['Content-Disposition: form-data; name="attachment"; filename="a%22b.bakx"',
                                     "Content-Type: application/octet-stream"])
        self.assertEqual(second[2], b"buffer")
        self.assertEqual(third[1][0], 'Content-Disposition: form-data; name="attachment"; filename="ukol.bakx"')
        self.assertEqual(third[2], b"file object content")
        self.assertNotEqual(first[0], second[0])  # a random boundary per upload

    def test_upload_from_a_path_object(self):
        path = self.directory / "rozvrh.txt"
        path.write_bytes(b"rozvrh")
        client, transport = logged_in_client(json_response(200, "id-7"))
        self.assertEqual(client.upload_attachment(path), "id-7")
        _, headers, content = split_multipart(transport.api_calls[0])
        self.assertEqual(headers, ['Content-Disposition: form-data; name="attachment"; filename="rozvrh.txt"',
                                   "Content-Type: text/plain"])
        self.assertEqual(content, b"rozvrh")

    def test_undecodable_name_bytes_are_replaced(self):
        client, transport = logged_in_client(json_response(201, "id-5"))
        # os.fsdecode(b"caf\xe9.txt") on a UTF-8 system, e.g. the name of a file copied from a Latin-2 disk
        self.assertEqual(client.upload_attachment(b"x", filename="caf\udce9.txt"), "id-5")
        _, headers, _ = split_multipart(transport.api_calls[0])
        self.assertEqual(headers[0], 'Content-Disposition: form-data; name="attachment"; filename="caf\ufffd.txt"; '
                                     "filename*=UTF-8''caf%EF%BF%BD.txt")

    def test_boundary_never_occurs_in_the_content(self):
        content = b"prefix --bakalari-" + b"a" * 32 + b" suffix"
        client, transport = logged_in_client(json_response(200, "id-4"))
        with mock.patch("bakalari.komens.secrets.token_hex", side_effect=["a" * 32, "b" * 32]) as token_hex:
            client.upload_attachment(content, filename="a.bin")
        self.assertEqual(token_hex.call_count, 2)
        boundary, _, sent = split_multipart(transport.api_calls[0])
        self.assertEqual((boundary, sent), ("bakalari-" + "b" * 32, content))

    def test_invalid_sources(self):
        client, transport = logged_in_client()
        with self.assertRaises(ValueError):
            client.upload_attachment(b"bytes")
        with self.assertRaises(ValueError):
            client.upload_attachment(io.BytesIO(b"buffer"))
        with self.assertRaises(TypeError):
            client.upload_attachment(io.StringIO("text"), filename="a.txt")
        with self.assertRaises(TypeError):
            client.upload_attachment(12345)
        with self.assertRaises(ValueError):
            client.upload_attachment(b"x", filename="a.txt", content_type="text/plain\r\nX-Injected: 1")
        with self.assertRaises(FileNotFoundError):
            client.upload_attachment(self.directory / "missing.pdf")
        self.assertEqual(transport.calls, [])

    def test_unusable_answers(self):
        client, _ = logged_in_client(text_response(200, "", "text/plain"), json_response(200, {"Id": "x"}),
                                     text_response(200, '""', "text/plain"), json_response(200, 42), FORBIDDEN)
        for _ in range(3):
            with self.assertRaises(BakalariContractError):
                client.upload_attachment(b"x", filename="a.txt")
        self.assertEqual(client.upload_attachment(b"x", filename="a.txt"), "42")
        with self.assertRaises(BakalariPermissionError):
            client.upload_attachment(b"x", filename="a.txt")

    def test_uploaded_id_can_be_sent(self):
        client, transport = logged_in_client(json_response(200, "att-77"), SENT_OK)
        attachment_id = client.upload_attachment(b"%PDF", filename="a.pdf")
        client.send_message(message_type="OBECNA", recipient_type="U", recipients=["UQX7K"], text="Příloha",
                            attachments=[attachment_id])
        self.assertEqual(transport.api_calls[1].json["Attachments"], ["att-77"])


if __name__ == "__main__":
    unittest.main()
