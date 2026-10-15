"""Live tests against a real Bakaláři installation, read-only.

They run when BAKALARI_URL, BAKALARI_USERNAME and BAKALARI_PASSWORD are set and BAKALARI_SKIP_LIVE is not.
LiveBakalariTest logs in once for the whole class; LivePublicPagesTest needs no login (the school's public timetable
pages and the public school directory).

The tests only read. They never call an endpoint that changes data: no marking messages as read, confirming, hiding,
unhiding or deleting them, no sending or replying, no attachment upload, no ticking homeworks as done, no confirming
marks, no what-if mark prediction, no push notification registration and no class book writes. Message details,
reply types and the attachment download use messages that are already read, and the downloaded attachment is neither
saved nor shown. The assertions check the structure of the answers (types, non-negative counters, parsing with the
contract validation on), never personal values, and no assertion message shows a token. An endpoint that the school
or the account may not use (HTTP 403: a module or right that is not enabled, or a teacher-only endpoint) skips its
test.

The negative login uses a random unknown user name, never the real account, because Bakaláři shows failed logins to
the account owner at the next login.
"""
import datetime as dt
import json
import math
import os
import secrets
import unittest

from bakalari import (
    API_PATH,
    BASE_URL_ENV,
    PASSWORD_ENV,
    USERNAME_ENV,
    Absence,
    AbsenceDay,
    AttachmentFile,
    AttachmentInfo,
    BakalariAuthError,
    BakalariClient,
    BakalariHTTPError,
    BakalariPermissionError,
    CertificateTerm,
    Change,
    ClassBook,
    ClassBookRecord,
    ClassFundItem,
    ClassFundMonth,
    ClassFundPaymentInfo,
    ClassFundSummary,
    Commissioner,
    Consent,
    Event,
    EventTime,
    FinalMark,
    Homework,
    LessonPast,
    LessonTag,
    Mark,
    MarkingAtom,
    MarkingMark,
    MarkingSheet,
    MarkingStudent,
    Marks,
    Message,
    MessagePerson,
    MessageRecipient,
    MessageType,
    MessageTypes,
    ModuleRights,
    Municipality,
    PedagogicalMeasure,
    PublicDay,
    PublicLesson,
    PublicTargets,
    PublicTimetable,
    Recipient,
    RecipientType,
    School,
    SchoolDirectory,
    StudentInfo,
    SubjectAbsence,
    SubjectInfo,
    SubjectMarks,
    SubjectThemes,
    Substitutions,
    Theme,
    Timetable,
    UserProfile,
    WebModule,
    WebModules,
    week_of,
)
from bakalari.public_timetable import PUBLIC_KINDS

LIVE_VARIABLES = (BASE_URL_ENV, USERNAME_ENV, PASSWORD_ENV)
LIVE = all(os.environ.get(name) for name in LIVE_VARIABLES) and not os.environ.get("BAKALARI_SKIP_LIVE")
SKIP_REASON = f"set {', '.join(LIVE_VARIABLES)} (and leave BAKALARI_SKIP_LIVE unset) to run the live tests"


class LiveTestCase(unittest.TestCase):
    """Helpers of the live test classes, which create ``client`` and the ``_cache`` dictionary in setUpClass."""

    client: BakalariClient
    _cache: dict

    def fetch(self, method, *args, **kwargs):
        """Calls a read method; HTTP 403 (the school has not enabled the module, the account lacks the right or is
        of another type, or the school does not publish the page) skips the test."""
        try:
            return method(*args, **kwargs)
        except BakalariPermissionError as error:
            reason = f"HTTP 403: {error.message}" if error.message else "HTTP 403"
            self.skipTest(f"the server refuses {method.__name__} ({reason})")

    def cached(self, key, method, *args, **kwargs):
        """Like :meth:`fetch`, but once for the whole class (the received messages can be about a megabyte)."""
        if key not in self._cache:
            self._cache[key] = self.fetch(method, *args, **kwargs)
        return self._cache[key]

    def assert_json_data(self, value):
        """``to_dict()`` of a model, or of every model of a list, is strict JSON data (the CLI prints it with
        --json)."""
        models = value if isinstance(value, list) else [value]
        try:
            json.dumps([model.to_dict() for model in models], ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            self.fail(f"to_dict() is not JSON data: {error}")

    def assert_counter(self, value):
        self.assertIsInstance(value, int)
        self.assertGreaterEqual(value, 0)


@unittest.skipUnless(LIVE, SKIP_REASON)
class LiveBakalariTest(LiveTestCase):
    """The REST API with the account from the environment: one login for the whole class."""

    @classmethod
    def setUpClass(cls):
        cls.client = BakalariClient.from_env(retries=2)
        cls.login_info = cls.client.login()  # the only login with the account's password
        cls._cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.client.logout()

    def profile(self) -> UserProfile:
        return self.cached("profile", self.client.user_profile)

    def own_class(self):
        school_class = self.profile().school_class
        if school_class is None:
            self.skipTest("the account has no class of its own")
        return school_class

    # --- The installation, the login and the tokens ---------------------------------------------------------

    def test_rest_api_is_available(self):
        self.assertTrue(self.client.api_version()["ApiVersion"].startswith("3."))
        self.assertIn("api/3", [version["BaseUrl"] for version in self.client.available_api_versions()])

    def test_login_with_the_web_credentials_grants_api_access(self):
        info = self.login_info
        self.assertEqual(info.token_type, "Bearer")
        self.assertGreater(info.expires_in, 0)
        self.assertIn("bakalari_api", info.scopes)
        self.assertTrue(info.user_id)
        self.assertIn("Timetable", self.client.enabled_modules())

    def test_access_token_is_renewed_with_the_refresh_token(self):
        info = self.client.refresh()  # the refresh-token grant, not another login
        self.assertIn("bakalari_api", info.scopes)
        self.assertTrue(self.client.actual_timetable().days)

    def test_timetable_request_without_access_token_is_rejected(self):
        response = self.client.request("GET", f"{API_PATH}/timetable/actual", authorized=False, expected_status=401)
        self.assertEqual(response.json()["Message"], "Authorization has been denied for this request.")

    def test_timetable_request_with_forged_access_token_is_rejected(self):
        response = self.client.request("GET", f"{API_PATH}/timetable/actual", access_token="forged.access.token",
                                       expected_status=401)
        self.assertEqual(response.json()["Message"], "Authorization has been denied for this request.")

    def test_timetable_request_with_invalid_date_is_rejected(self):
        with self.assertRaises(BakalariHTTPError) as raised:
            self.client.actual_timetable("not-a-date")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("date", raised.exception.body["ModelState"])

    def test_login_with_unknown_credentials_is_rejected(self):
        stranger = BakalariClient(self.client.base_url)
        with self.assertRaises(BakalariAuthError) as raised:
            stranger.login(f"python-unknown-{secrets.token_hex(6)}", secrets.token_urlsafe(12))
        self.assertEqual((raised.exception.status, raised.exception.body["error"]), (400, "invalid_grant"))
        self.assertFalse(stranger.is_authenticated)

    # --- The account: profile, modules, presence at school, web modules, web login token -------------------

    def test_user_profile(self):
        profile = self.profile()  # validates the contract
        self.assertIsInstance(profile, UserProfile)
        self.assertTrue(profile.user_type, "the profile has no user type")
        self.assertTrue(profile.modules, "the profile lists no enabled module")
        for module in profile.modules:
            self.assertIsInstance(module, ModuleRights)
            self.assertTrue(module.module, "an enabled module has no name")
            self.assertTrue(all(isinstance(right, str) and right for right in module.rights), "an empty right")
        self.assertTrue(all(isinstance(student, StudentInfo) for student in profile.students))
        for period in (profile.semester, profile.school_year):
            if period is not None and period.start and period.end:
                self.assertLessEqual(period.start, period.end)
        self.assert_json_data(profile)

    def test_user_enabled_modules_are_those_of_the_profile(self):
        modules = self.client.enabled_modules()
        self.assertIsInstance(modules, list)
        self.assertEqual(modules, self.profile().module_names)

    def test_user_student_at_school_is_a_boolean(self):
        self.assertIsInstance(self.fetch(self.client.student_at_school), bool)

    def test_user_web_modules(self):
        web = self.fetch(self.client.web_modules)  # validates the contract
        self.assertIsInstance(web, WebModules)
        for module in web.modules + ((web.dashboard,) if web.dashboard else ()):
            self.assertIsInstance(module, WebModule)
            self.assertIsInstance(module.url, str)
        self.assert_json_data(web)

    def test_user_login_token_is_not_empty(self):
        token = self.client.login_token()
        # The token logs in to the web: only a boolean is asserted, so that no failure message can show it.
        self.assertTrue(isinstance(token, str) and bool(token.strip()), "the login token is empty")

    # --- Timetable and substitutions ------------------------------------------------------------------------

    def test_actual_timetable_of_the_current_week(self):
        today = dt.date.today()
        timetable = self.client.actual_timetable(today)  # validates the contract
        self.assertTrue(timetable.covers_week_of(today))
        for lesson in timetable.lessons:  # every lesson resolves to a slot; a holiday week has none
            self.assertTrue(lesson.hour.caption)

    def test_actual_timetable_of_a_requested_week(self):
        next_week = dt.date.today() + dt.timedelta(weeks=1)
        self.assertTrue(self.client.actual_timetable(next_week).covers_week_of(next_week))

    def test_permanent_timetable_lists_the_regular_lessons(self):
        taught = self.client.permanent_timetable().taught_lessons
        self.assertTrue(taught)
        self.assertEqual([lesson.format() for lesson in taught if not (lesson.teacher and lesson.room)], [])

    def test_timetable_of_the_own_class(self):
        today = dt.date.today()
        timetable = self.fetch(self.client.class_timetable, self.own_class(), today)  # validates the contract
        self.assertTrue(timetable.covers_week_of(today))

    def test_timetable_permanent_of_the_own_class(self):
        timetable = self.fetch(self.client.class_timetable, self.own_class(), permanent=True)
        self.assertIsInstance(timetable, Timetable)
        self.assertTrue(timetable.days)

    def check_substitutions(self, substitutions):
        self.assertIsInstance(substitutions, Substitutions)
        self.assertTrue(all(isinstance(change, Change) for change in substitutions.changes))
        start, end = substitutions.start, substitutions.end
        if start and end:
            self.assertLessEqual(start, end)
            outside = [change for change in substitutions.changes if change.day and not start <= change.day <= end]
            self.assertEqual(len(outside), 0, "changes outside the From-To period of the answer")
        self.assert_json_data(substitutions)

    def test_substitutions_of_the_default_period(self):
        self.check_substitutions(self.fetch(self.client.substitutions))

    def test_substitutions_since_today(self):
        self.check_substitutions(self.fetch(self.client.substitutions, dt.date.today()))

    # --- Marks ----------------------------------------------------------------------------------------------

    def check_marks(self, marks):
        self.assertIsInstance(marks, Marks)
        for subject in marks.subjects:
            self.assertIsInstance(subject, SubjectMarks)
            self.assertTrue(subject.average is None or math.isfinite(subject.average), "an average is not finite")
        for mark in marks.all_marks:
            self.assertIsInstance(mark, Mark)
            self.assertTrue(mark.id, "a mark has no id")
            self.assertTrue(mark.weight is None or mark.weight >= 0, "a mark has a negative weight")
            self.assertGreaterEqual(mark.max_points, 0)
        self.assert_json_data(marks)

    def test_marks(self):
        self.check_marks(self.fetch(self.client.marks))  # validates the contract

    def test_marks_since_the_start_of_the_semester(self):
        semester = self.profile().semester
        since = semester.start if semester is not None and semester.start else dt.date.today()
        recent = self.fetch(self.client.marks, since=since)
        self.check_marks(recent)
        listed = {mark.id for mark in self.fetch(self.client.marks).all_marks}  # fetched after, so it has them all
        self.assertTrue(all(mark.id in listed for mark in recent.all_marks), "marks(since=...) lists other marks")

    def test_marks_new_count(self):
        self.assert_counter(self.fetch(self.client.new_marks_count))

    def test_marks_final(self):
        terms = self.fetch(self.client.final_marks)
        self.assertIsInstance(terms, list)
        for term in terms:
            self.assertIsInstance(term, CertificateTerm)
            self.assertTrue(all(isinstance(mark, FinalMark) for mark in term.final_marks))
            hours = (term.absent_hours, term.not_excused_hours)
            self.assertTrue(all(value is None or value >= 0 for value in hours), "negative absent hours")
        self.assert_json_data(terms)

    def test_marks_pedagogical_measures(self):
        measures = self.fetch(self.client.pedagogical_measures)
        self.assertIsInstance(measures, list)
        self.assertTrue(all(isinstance(measure, PedagogicalMeasure) for measure in measures))
        self.assert_json_data(measures)

    # --- Absence, subjects, homeworks and events ------------------------------------------------------------

    def test_absence(self):
        absence = self.fetch(self.client.absence)
        self.assertIsInstance(absence, Absence)
        threshold = absence.percentage_threshold
        self.assertTrue(threshold is None or threshold >= 0, "a negative percentage threshold")
        for day in absence.days:
            self.assertIsInstance(day, AbsenceDay)
            self.assertTrue(all(count >= 0 for count in day.counts().values()), "a negative counter of a day")
        for subject in absence.subjects:
            self.assertIsInstance(subject, SubjectAbsence)
            counts = (subject.lessons_count, subject.base, subject.late, subject.soon, subject.school,
                      subject.distance_teaching)
            self.assertTrue(all(count >= 0 for count in counts), "a negative counter of a subject")
        self.assertTrue(all(count >= 0 for count in absence.totals().values()), "a negative total")
        self.assert_json_data(absence)

    def subject_list(self):
        return self.cached("subjects", self.client.subjects)

    def test_subjects(self):
        subjects = self.subject_list()
        self.assertIsInstance(subjects, list)
        self.assertTrue(all(isinstance(subject, SubjectInfo) and subject.id.strip() for subject in subjects))
        self.assert_json_data(subjects)

    def test_subjects_themes_of_one_subject(self):
        subjects = self.subject_list()
        if not subjects:
            self.skipTest("the account has no subjects")
        themes = self.fetch(self.client.subject_themes, subjects[0])
        self.assertIsInstance(themes, SubjectThemes)
        self.assertEqual(themes.subject.id.strip(), subjects[0].id.strip())
        for theme in themes.themes:
            self.assertIsInstance(theme, Theme)
            self.assertTrue(theme.duration is None or theme.duration >= 0, "a negative lesson duration")
        self.assert_json_data(themes)

    def check_homeworks(self, homeworks):
        self.assertIsInstance(homeworks, list)
        for homework in homeworks:
            self.assertIsInstance(homework, Homework)
            self.assertTrue(homework.id, "a homework has no id")
            self.assertTrue(all(isinstance(item, AttachmentInfo) and item.id for item in homework.attachments))
        self.assert_json_data(homeworks)

    def test_homeworks_of_the_default_period(self):
        self.check_homeworks(self.fetch(self.client.homeworks))

    def test_homeworks_of_a_given_period(self):
        today = dt.date.today()
        since, until = today - dt.timedelta(days=30), today + dt.timedelta(days=7)
        self.check_homeworks(self.fetch(self.client.homeworks, since, until))

    def test_homeworks_active_count(self):
        self.assert_counter(self.fetch(self.client.active_homeworks_count))

    def check_events(self, events):
        self.assertIsInstance(events, list)
        for event in events:
            self.assertIsInstance(event, Event)
            self.assertTrue(event.id, "an event has no id")
            self.assertTrue(all(isinstance(time, EventTime) for time in event.times))
        self.assert_json_data(events)

    def test_events_of_the_school(self):
        self.check_events(self.fetch(self.client.events))

    def test_events_of_the_user(self):
        self.check_events(self.fetch(self.client.events, scope="my"))

    def test_events_public(self):
        self.check_events(self.fetch(self.client.events, scope="public"))

    def test_events_since_today(self):
        self.check_events(self.fetch(self.client.events, dt.date.today()))

    # --- Komens messages ------------------------------------------------------------------------------------

    def messages_in(self, folder):
        return self.cached(("messages", folder), self.client.messages, folder)

    def read_message(self, folder, *, answerable=False):
        """The first message of the folder that is already read (and may be answered, with ``answerable``)."""
        found = next((message for message in self.messages_in(folder)
                      if message.read and (message.can_answer or not answerable)), None)
        if found is None:
            kind = "answerable message" if answerable else "message"
            self.skipTest(f"the {folder} folder has no already-read {kind}")
        return found

    def check_messages(self, messages):
        self.assertIsInstance(messages, list)
        for message in messages:
            self.assertIsInstance(message, Message)
            self.assertTrue(message.id, "a message has no id")
            self.assertIsInstance(message.read, bool)
            self.assertTrue(all(isinstance(item, AttachmentInfo) and item.id for item in message.attachments))
            counts = (message.recipients_count, message.recipients_processed_count, message.attachments_count)
            self.assertTrue(all(count is None or count >= 0 for count in counts), "a negative message counter")
        self.assert_json_data(messages)

    def test_komens_received_messages(self):
        self.check_messages(self.messages_in("received"))  # validates the contract

    def test_komens_sent_messages(self):
        self.check_messages(self.messages_in("sent"))

    def test_komens_noticeboard_messages(self):
        self.check_messages(self.messages_in("noticeboard"))

    def test_komens_apology_messages(self):
        self.check_messages(self.messages_in("apology"))  # needs an extra right

    def test_komens_rating_messages(self):
        self.check_messages(self.messages_in("rating"))  # needs an extra right

    def test_komens_unread_received_messages_count(self):
        self.assert_counter(self.fetch(self.client.unread_messages_count, "received"))

    def test_komens_unread_noticeboard_messages_count(self):
        self.assert_counter(self.fetch(self.client.unread_messages_count, "noticeboard"))

    def check_message_types(self, types):
        self.assertIsInstance(types, MessageTypes)
        for message_type in types.types:
            self.assertIsInstance(message_type, MessageType)
            self.assertTrue(message_type.code, "a message type has no code")
            for recipient_type in message_type.recipient_types:
                self.assertIsInstance(recipient_type, RecipientType)
                self.assertTrue(recipient_type.code, "a recipient type has no code")
                self.assertTrue(all(isinstance(recipient, Recipient) for recipient in recipient_type.recipients))
        self.assertTrue(all(isinstance(recipient, Recipient) for recipient in types.recipients))
        self.assert_json_data(types)

    def test_komens_message_types(self):
        self.check_message_types(self.fetch(self.client.message_types))

    def test_komens_reply_message_types_of_a_read_message(self):
        message = self.read_message("received", answerable=True)
        types = self.fetch(self.client.message_types, reply_to=message)  # a GET: nothing is sent
        self.check_message_types(types)
        # What reply_to_message() needs: a message type with a recipient type.
        self.assertTrue(types.types and types.types[0].recipient_types, "the server offers no way to reply")

    def test_komens_detail_of_a_read_received_message(self):
        message = self.read_message("received")
        detail = self.fetch(self.client.message, message, "received")
        self.assertIsInstance(detail, Message)
        self.assertEqual(detail.id, message.id)
        self.assert_json_data(detail)

    def test_komens_detail_of_a_read_sent_message(self):
        message = self.read_message("sent")
        detail = self.fetch(self.client.message, message, "sent")
        self.assertIsInstance(detail, Message)
        self.assertEqual(detail.id, message.id)
        self.assertTrue(all(isinstance(item, MessageRecipient) and item.id for item in detail.recipients))
        self.assertTrue(all(isinstance(person, MessagePerson) for person in detail.persons))
        self.assert_json_data(detail)

    def test_komens_attachment_download_of_a_read_message(self):
        attachments = []
        for folder in ("received", "sent"):  # the sent folder only when no received message has one
            attachments = [item for message in self.messages_in(folder) if message.read
                           for item in message.attachments if item.id]
            if attachments:
                break
        if not attachments:
            self.skipTest("no already-read message has an attachment")
        smallest = min(attachments, key=lambda item: math.inf if item.size is None else item.size)
        attachment = self.fetch(self.client.download_attachment, smallest)
        # Only that bytes and a file name came back: the content is neither saved nor shown.
        self.assertIsInstance(attachment, AttachmentFile)
        self.assertTrue(isinstance(attachment.content, bytes), "the attachment content is not bytes")
        self.assertTrue(isinstance(attachment.filename, str) and attachment.filename.strip(), "no file name")

    def test_komens_rating_templates(self):
        self.fetch(self.client.rating_templates)  # raw JSON of an undocumented shape; teacher accounts only

    # --- GDPR -----------------------------------------------------------------------------------------------

    def check_consents(self, consents):
        self.assertIsInstance(consents, list)
        for consent in consents:
            self.assertIsInstance(consent, Consent)
            self.assertTrue(consent.id, "a consent has no id")
            self.assertTrue(consent.valid_years is None or consent.valid_years >= 0, "negative years of validity")
        self.assert_json_data(consents)

    def test_gdpr_commissioners(self):
        commissioners = self.fetch(self.client.gdpr_commissioners)
        self.assertIsInstance(commissioners, list)
        self.assertTrue(all(isinstance(commissioner, Commissioner) for commissioner in commissioners))
        self.assert_json_data(commissioners)

    def test_gdpr_consents(self):
        self.check_consents(self.fetch(self.client.consents))

    def test_gdpr_child_consents(self):
        self.check_consents(self.fetch(self.client.child_consents))

    def test_gdpr_new_consents_count(self):
        self.assert_counter(self.fetch(self.client.new_consents_count))

    # --- Payments (the module is often not enabled: these tests skip then) -------------------------------

    def test_payments_class_fund_summary(self):
        summary = self.fetch(self.client.class_fund_summary)
        self.assertIsInstance(summary, ClassFundSummary)
        self.assertTrue(math.isfinite(summary.balance) and math.isfinite(summary.spent), "an amount is not finite")
        self.assert_json_data(summary)

    def test_payments_class_fund_months(self):
        months = self.fetch(self.client.class_fund_payments)
        self.assertIsInstance(months, list)
        for month in months:
            self.assertIsInstance(month, ClassFundMonth)
            self.assertTrue(all(isinstance(item, ClassFundItem) for item in month.items))
        self.assert_json_data(months)

    def test_payments_class_fund_payment_info(self):
        info = self.fetch(self.client.class_fund_payment_info)
        self.assertIsInstance(info, ClassFundPaymentInfo)
        payment = info.qr_payment()
        self.assertTrue(payment is None or payment.startswith("SPD*1.0*ACC:"), "not a QR payment (SPAYD) string")
        self.assert_json_data(info)

    def test_payments_regular_payments_summary(self):
        self.fetch(self.client.regular_payments_summary)  # raw JSON of an undocumented shape

    # --- Teacher accounts (other accounts are refused: these tests skip then) ------------------------------

    def class_book(self):
        monday, sunday = week_of(dt.date.today())
        return self.cached("classbook", self.client.classbook, monday, sunday)

    def test_teacher_class_book_of_this_week(self):
        book = self.class_book()  # validates the contract
        self.assertIsInstance(book, ClassBook)
        self.assertTrue(all(isinstance(record, ClassBookRecord) for record in book.records))
        self.assert_json_data(book)

    def test_teacher_lesson_details_of_a_class_book_record(self):
        record = next((record for record in self.class_book().records if record.lesson_id.strip()), None)
        if record is None:
            self.skipTest("this week's class book has no lesson")
        self.assertIsInstance(self.fetch(self.client.lesson_absence, record.lesson_id), dict)
        self.assertIsInstance(self.fetch(self.client.lesson_past, record.lesson_id), LessonPast)
        self.assertIsInstance(self.fetch(self.client.lesson_students_timetable, record.lesson_id), dict)

    def test_teacher_lesson_tags(self):
        tags = self.fetch(self.client.lesson_tags)
        self.assertIsInstance(tags, list)
        self.assertTrue(all(isinstance(tag, LessonTag) and tag.id for tag in tags))

    def test_teacher_marking_atoms_and_the_sheet_of_one(self):
        atoms = self.fetch(self.client.marking_atoms)
        self.assertTrue(all(isinstance(atom, MarkingAtom) for atom in atoms))
        atom = next((atom for atom in atoms if atom.id.strip() and not atom.disabled), None)
        if atom is None:
            self.skipTest("no marking atom that can be opened")
        sheet = self.fetch(self.client.marking_marks, atom.id)
        self.assertIsInstance(sheet, MarkingSheet)
        self.assertTrue(all(isinstance(mark, MarkingMark) for mark in sheet.marks))
        self.assertTrue(all(isinstance(student, MarkingStudent) for student in sheet.students))

    def test_teacher_emergency_configuration(self):
        self.fetch(self.client.emergency_configuration)  # raw JSON of an undocumented shape


@unittest.skipUnless(LIVE, SKIP_REASON)
class LivePublicPagesTest(LiveTestCase):
    """The school's public timetable pages and the public school directory, which need no login."""

    @classmethod
    def setUpClass(cls):
        cls.client = BakalariClient(os.environ[BASE_URL_ENV], retries=2)  # no credentials: it cannot log in
        cls.directory = SchoolDirectory()
        cls._cache = {}

    def targets(self):
        return self.cached("targets", self.client.public_timetable_targets)  # a school that publishes none: skip

    def test_public_timetable_targets(self):
        targets = self.targets()
        self.assertIsInstance(targets, PublicTargets)
        for target in targets.all_targets:
            self.assertIn(target.kind, PUBLIC_KINDS)
            self.assertTrue(target.id.strip(), "a target has no id")
        self.assert_json_data(targets)

    def test_public_timetable_of_one_target(self):
        target = next(iter(self.targets().all_targets), None)  # a class when the school publishes classes
        if target is None:
            self.skipTest("the school lists no public timetable")
        timetable = self.fetch(self.client.public_timetable, target.kind, target)  # a refusal skips
        self.assertIsInstance(timetable, PublicTimetable)
        self.assertEqual((timetable.kind, timetable.target_id, timetable.week), (target.kind, target.id, "actual"))
        self.assertTrue(all(isinstance(day, PublicDay) for day in timetable.days))
        self.assertTrue(all(isinstance(lesson, PublicLesson) for lesson in timetable.lessons))
        self.assert_json_data(timetable)

    def municipalities(self):
        return self.cached("municipalities", self.directory.municipalities)

    def test_school_directory_municipalities(self):
        municipalities = self.municipalities()  # validates the contract
        self.assertTrue(municipalities, "the directory lists no municipality")
        self.assertTrue(all(isinstance(item, Municipality) and item.school_count >= 0 for item in municipalities))
        self.assert_json_data(municipalities)

    def test_school_directory_schools_of_one_town(self):
        # The town with the fewest schools gives the shortest answer. Only plain names (letters, digits, spaces and
        # dashes) are candidates: the service mishandles names with a dot.
        towns = [
            item for item in self.municipalities()
            if item.school_count and item.name and all(char.isalnum() or char in " -" for char in item.name)
        ]
        self.assertTrue(towns, "the directory lists no town with schools")
        town = min(towns, key=lambda item: item.school_count)
        schools = self.directory.schools(town)
        self.assertTrue(schools, "the directory lists no school of the town")
        self.assertTrue(all(isinstance(school, School) and school.name for school in schools))
        self.assert_json_data(schools)


if __name__ == "__main__":
    unittest.main()
