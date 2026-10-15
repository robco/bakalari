# Endpoint coverage

This page lists every known endpoint of the Bakaláři REST API v3, the public HTML pages and the services outside a
school's installation that the client uses, with the `BakalariClient` method that wraps each one. The sources are
the [community documentation of API v3](https://github.com/bakalari-api/bakalari-api-v3), its issues and forks,
other client implementations and captured traffic of the official app, and read-only checks against a live
installation (API 3.52.1, a parent account) on 2026-10-15.

Paths are relative to the school's address (`BAKALARI_URL`, e.g. `https://skola.bakalari.cz`), so `/api/3/marks`
means `https://skola.bakalari.cz/api/3/marks`. `{id}` stands for an id percent-encoded as one path segment (a
space becomes `%20`), which the client does for you. Every `/api/3` request carries
`Authorization: Bearer <access token>`; the client logs in and renews the token as needed. The
[library guide](library.md) describes the methods and their models, and the [command line reference](cli.md) the
`bakalari` commands built on them.

## Verification status

| Status | Meaning |
|---|---|
| LIVE verified 2026-10-15 | Called read-only against the live installation; the response shape was captured and the models follow it. A route marked "does not exist" answered HTTP 404 or 405 there. |
| route+method verified only | The route and the HTTP method were confirmed on 2026-10-15 without changing any data: a `GET` answered HTTP 405 with an `Allow` header naming the method, or the API itself refused the request (HTTP 403 because the module or the user type does not allow it, or HTTP 500 for an invalid id) instead of the "not found" page of the web server. The request and response formats come from the community documentation, other clients or captured traffic; the notes say which. |
| community docs | Only the community documentation describes it; the test account could not use it. |
| other clients | Found in other client implementations, forks of the documentation, its issues or captured traffic of the official app. |

Unless a note says otherwise, an account without the module or right gets HTTP 403, raised as
`BakalariPermissionError`, and the teacher endpoints answer other accounts with
`Some privilege is missing (IsTeacher)`.

## Summary

- The tables below have 91 entries: 71 endpoints with a typed method (each Komens folder, each event list and each
  grant of the token endpoint counts separately), 17 known endpoints that are not wrapped and 3 routes that were
  checked and do not exist.
- Of the 71 wrapped endpoints, 41 are LIVE verified, 23 are route+method verified only, 6 follow the community
  docs only and 1 follows other clients only. The others are mostly teacher and payment endpoints, which the test
  account could not call, and write endpoints, which were not executed.
- Every read endpoint of the REST API whose request is known has a typed method (the OpenID discovery document
  and the information banners are not part of it). Of the write endpoints, the documented ones are wrapped:
  marking messages read, confirmed, hidden and unhidden, deleting, sending and replying to messages, uploading
  attachments, confirming marks, ticking homeworks, saving class-book records and registering a push token.
- Payloads that are undocumented are returned as raw JSON (`rating_templates()`, `regular_payments_summary()`,
  `emergency_configuration()`, `lesson_absence()`, `lesson_students_timetable()`, `timetable_json()`); every model
  also keeps the server's object in its `raw` field.

## Authentication and API information

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| POST | `/api/login` (`grant_type=password`) | `login()`; implicitly on the first authorized request | `TokenInfo` | LIVE verified 2026-10-15 | Form body with `client_id=ANDR`, `username` and `password`; a wrong login answers HTTP 400 `invalid_grant` (`BakalariAuthError`). Failed logins are shown to the account owner. |
| POST | `/api/login` (`grant_type=refresh_token`) | `refresh()`; implicitly before the access token expires | `TokenInfo` | LIVE verified 2026-10-15 | Returns new tokens, including a new refresh token; `on_session_update` receives each new `SessionState`. |
| GET | `/api` | `available_api_versions()` | `List[Dict[str, Any]]` | LIVE verified 2026-10-15 | No login. |
| GET | `/api/3` | `api_version()` | `Dict[str, Any]` | LIVE verified 2026-10-15 | No login; `ApiVersion`, `ApplicationVersion`, `BaseUrl`. |
| GET | `/.well-known/openid-configuration` | not wrapped | | LIVE verified 2026-10-15 | The OpenID Connect discovery document the official app 4.x reads first; not needed, because `POST /api/login` works. |

## Account

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/user` | `user_profile()`, `enabled_modules()` | `UserProfile`, `List[str]` | LIVE verified 2026-10-15 | Type, names, class, school, the students of a parent account, the modules with their rights and the module settings (semester, school year). |
| GET | `/api/3/user/student-at-school` | `student_at_school()` | `bool` | LIVE verified 2026-10-15 | Module AccessSystem, right `CanShowStudentPresentAtSchool`. |
| GET | `/api/3/webmodule` | `web_modules()` | `WebModules` | LIVE verified 2026-10-15 | The web pages the app links to, and the dashboard. |
| GET | `/api/3/logintoken` | `login_token()`, `web_login_url()` | `str` | community docs | A one-time token for the web login: a credential until it is used. |
| GET | `/api/3/login/{token}?returnUrl=` | not wrapped; `web_login_url()` builds the URL | | community docs | A browser step: HTTP 302 to `returnUrl` with a web session (to the login page for a used token). |
| POST | `/api/3/register-notification?token=` | `register_notification(token)` | `None` | route+method verified only | JSON body `null`, HTTP 200 or 204 (issue #54 of the documentation). The server expects the official app's Firebase token, so a third-party token receives no pushes; poll the counters instead. |
| ? | `/api/3/unregister-user-notification` | not wrapped | | community docs | No route matched any method and parameter shape tried (HTTP 404). |

## Timetable

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/timetable/actual?date=` | `actual_timetable(date)`, `timetable_json("actual", date)` | `Timetable`, `Dict[str, Any]` | LIVE verified 2026-10-15 | The Monday-Friday week that contains `date` (default today) with its changes; an invalid date answers HTTP 400. |
| GET | `/api/3/timetable/permanent` | `permanent_timetable()`, `timetable_json("permanent")` | `Timetable`, `Dict[str, Any]` | LIVE verified 2026-10-15 | A lesson of some weeks only lists its week cycles. |
| GET | `/api/3/timetable/actual/class/{classId}?date=` | `class_timetable(class_id, date)`, `timetable_json("actual", date, class_id=...)` | `Timetable`, `Dict[str, Any]` | LIVE verified 2026-10-15 | The whole class with all its groups, in the shape of the personal timetable; verified for the account's own class (another class may be refused). |
| GET | `/api/3/timetable/permanent/class/{classId}` | `class_timetable(class_id, permanent=True)`, `timetable_json("permanent", class_id=...)` | `Timetable`, `Dict[str, Any]` | LIVE verified 2026-10-15 | |
| GET | `/api/3/timetable/student/{studentId}` | not wrapped | | other clients | Found in the official app (issue #63 of the documentation); parameters and answer unverified. |
| GET | `/api/3/timetable/{actual,permanent}/{teacher,room}/{id}` | does not exist | | LIVE verified 2026-10-15 | HTTP 404. The timetables of teachers and rooms are available as public pages (see below). |

## Substitutions

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/substitutions?from=` | `substitutions(since)` | `Substitutions` | LIVE verified 2026-10-15 | 14 days from `from`; without it from Monday of the current week. Module Substitutions. |

## Marks

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/marks?from=` | `marks(since=...)` | `Marks` | LIVE verified 2026-10-15 | With `from` only the marks from that day on (verified live). |
| GET | `/api/3/marks/count-new` | `new_marks_count()` | `int` | LIVE verified 2026-10-15 | The server's counter, often 0 even when marks are flagged new; `Marks.new_marks` lists the flagged marks. |
| GET | `/api/3/marks/final` | `final_marks()` | `List[CertificateTerm]` | LIVE verified 2026-10-15 | Empty on the test account; the shape of a term follows the community docs. |
| GET | `/api/3/marks/measures` | `pedagogical_measures()` | `List[PedagogicalMeasure]` | LIVE verified 2026-10-15 | Empty on the test account; the shape of a measure follows the community docs. Its text is HTML-entity encoded. |
| POST | `/api/3/marks/what-if` | `what_if(marks)`, `predict_marks(subject, hypothetical)` | `SubjectMarks` | route+method verified only | A JSON list of all marks of one subject `{Id, MarkText, Weight, MaxPoints, SubjectId}` plus hypothetical ones with `Id` null (community docs); computes only, changes nothing. HTTP 403 when prediction is disabled for the subject or the right `PredictMarks` is missing. |
| POST | `/api/3/marks/SetClassificationConfirmation` | `confirm_marks(mark_ids)` | `bool` | route+method verified only | A JSON list of mark ids (the community docs say subject ids; other clients and issue #65 of the documentation use mark ids); HTTP 200 when confirmed (True), 204 when there was nothing to confirm (False). Right `CanConfirmClassification`. |

## Absence

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/absence/student` | `absence()` | `Absence` | LIVE verified 2026-10-15 | Module Absence; the per-subject list is empty without the right `ShowAbsencePercentage`. |

## Subjects

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/subjects` | `subjects()` | `List[SubjectInfo]` | LIVE verified 2026-10-15 | The teachers' contacts are usually `null`. |
| GET | `/api/3/subjects/themes/{subjectId}` | `subject_themes(subject_id)` | `SubjectThemes` | LIVE verified 2026-10-15 | Ids exactly as sent: `" 2"` becomes `%202`. Right `ShowSubjectThemes`. |
| GET | `/api/3/subjects/themes/get?subjectid=` | `subject_themes(subject_id)` | `SubjectThemes` | LIVE verified 2026-10-15 | The same answer; used for ids a URL path cannot carry (the web server answers HTTP 404 for a backslash). |

## Homeworks

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/homeworks?from=&to=` | `homeworks(since, until)` | `List[Homework]` | LIVE verified 2026-10-15 | Without the dates the server returns 14 days back and one day ahead; an invalid date answers HTTP 400. |
| GET | `/api/3/homeworks/count-actual` | `active_homeworks_count()` | `int` | LIVE verified 2026-10-15 | The homeworks that are not closed. |
| PUT | `/api/3/homeworks/{id}/student-done/{true\|false}` | `set_homework_done(homework_id, done)` | `None` | route+method verified only | No body; the answer is the text `true` (other clients). Sets the student's `Finished` flag (`Done` is the teacher's). Ids with a backslash cannot be addressed (none since server 26.0.429.0). |

Electronic homework submission has no known REST endpoint: it works on the web only (open it with
`web_login_url()`).

## Events

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/events?from=` | `events(since)` | `List[Event]` | LIVE verified 2026-10-15 | Without `from` the events of the whole school year. Module Events. |
| GET | `/api/3/events/my?from=` | `events(since, scope="my")` | `List[Event]` | LIVE verified 2026-10-15 | The user's own events. |
| GET | `/api/3/events/public?from=` | `events(since, scope="public")` | `List[Event]` | LIVE verified 2026-10-15 | The public events. |

## Komens messages

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| POST | `/api/3/komens/messages/received` | `messages()`, `messages("received", since=...)` | `List[Message]` | LIVE verified 2026-10-15 | An empty form body; the form field `dateFrom` returns only the messages from that date on (verified live). `GET` answers HTTP 405. |
| POST | `/api/3/komens/messages/sent` | `messages("sent")` | `List[Message]` | LIVE verified 2026-10-15 | Adds the recipient and attachment counts. |
| POST | `/api/3/komens/messages/noticeboard` | `messages("noticeboard")` | `List[Message]` | LIVE verified 2026-10-15 | The list carries the whole messages; no detail endpoint is documented for them. |
| POST | `/api/3/komens/messages/apology` | `messages("apology")` | `List[Message]` | route+method verified only | HTTP 403 for the test account (extra rights); assumed to have the shape of the other lists. |
| POST | `/api/3/komens/messages/rating` | `messages("rating")` | `List[Message]` | route+method verified only | As above. |
| GET | `/api/3/komens/messages/received/unread` | `unread_messages_count()` | `int` | LIVE verified 2026-10-15 | |
| GET | `/api/3/komens/messages/noticeboard/unread` | `unread_messages_count("noticeboard")` | `int` | LIVE verified 2026-10-15 | |
| GET | `/api/3/komens/messages/received/{id}` | `message(message_id)` | `Message` | LIVE verified 2026-10-15 | Reading the detail does not mark the message as read. |
| GET | `/api/3/komens/messages/sent/{id}` | `message(message_id, "sent")` | `Message` | LIVE verified 2026-10-15 | Adds the recipients and the persons involved. |
| PUT | `/api/3/komens/message/{id}/mark-as-read` | `mark_message_read(message_id)` | `None` | route+method verified only | No body; HTTP 204 (community docs). |
| PUT | `/api/3/komens/message/{id}/mark-as-confirmed` | `confirm_message(message_id)` | `None` | route+method verified only | No body; allowed when `Message.can_confirm`. The path comes from a fork of the documentation; HTTP 200 and 204 are accepted. |
| PUT | `/api/3/komens/message/{id}/mark-as-hidden` | `hide_message(message_id)` | `None` | route+method verified only | No body; allowed when `Message.can_hide`. From a fork of the documentation, like the next one. |
| PUT | `/api/3/komens/message/{id}/mark-as-unhidden` | `unhide_message(message_id)` | `None` | route+method verified only | No body. |
| DELETE | `/api/3/komens/message/{id}` | `delete_message(message_id)` | `None` | route+method verified only | Allowed when `Message.can_delete`. |
| PUT | `/api/3/komens/message/{id}` | not wrapped | | route+method verified only | The route allows PUT and DELETE; the PUT body is unknown. |
| GET | `/api/3/komens/message/{id}` | does not exist | | LIVE verified 2026-10-15 | HTTP 405; the detail is `GET /api/3/komens/messages/{received\|sent}/{id}`. |
| GET | `/api/3/komens/message-types` | `message_types()` | `MessageTypes` | LIVE verified 2026-10-15 | The types the account may send, with their recipient types and recipients. |
| GET | `/api/3/komens/message-types/reply/{id}` | `message_types(reply_to=...)`, `reply_to_message(...)` | `MessageTypes` | LIVE verified 2026-10-15 | The same shape, limited to what a reply allows (live: one recipient type with the selection `ZERO`). |
| GET | `/api/3/komens/message-types/edit/{conceptId}` | not wrapped | | route+method verified only | For drafts; a normal message id answers HTTP 404 JSON. |
| POST | `/api/3/komens/message` | `send_message(...)`, `reply_to_message(...)` | `None` | route+method verified only | A JSON body with every documented key (`MessageType`, `Title`, `Text`, `RecipientType`, `Recipients`, `Attachments`, ...); HTTP 200 `{"Message": ""}` (community docs). Right `SendMessages`. |
| POST | `/api/3/komens/attachment` | `upload_attachment(source)` | `str` | route+method verified only | `multipart/form-data` with one file part named `attachment` (captured in issue #57); answers the attachment id as a JSON string. Right `SendAttachments`. |
| GET | `/api/3/komens/attachment/{id}` | `download_attachment(attachment_id)` | `AttachmentFile` | route+method verified only | Downloads message and homework attachments (community docs); since server 2.1.0810.1 only attachments of the user's own messages. An unknown id answers HTTP 500 (`BakalariHTTPError`). |
| GET | `/api/3/komens/rating-templates` | `rating_templates()` | `Any` (raw JSON) | route+method verified only | HTTP 403 for the parent account; for teacher accounts. |
| POST | `/api/3/komens/concept`, `/api/3/komens/concepts` | not wrapped | | route+method verified only | Drafts (concepts); the payloads are unknown. |

## GDPR

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/gdpr/commissioners` | `gdpr_commissioners()` | `List[Commissioner]` | LIVE verified 2026-10-15 | Empty when the school has entered no data protection officer. |
| GET | `/api/3/gdpr/consents/person` | `consents()` | `List[Consent]` | LIVE verified 2026-10-15 | Right `ShowOwnConsents`. |
| GET | `/api/3/gdpr/consents/person/child` | `child_consents()` | `List[Consent]` | LIVE verified 2026-10-15 | Right `ShowChildConsents`. |
| GET | `/api/3/gdpr/consents/person/new` | `new_consents_count()` | `int` | LIVE verified 2026-10-15 | |
| ? | `/api/3/gdpr/consent` | not wrapped | | community docs | Answering a consent; the route shape is unknown (`GET` with or without an id answers the web server's 404 page). |
| ? | `/api/3/gdpr/commissioner` | not wrapped | | community docs | No route matches `GET`, with or without an id. |
| POST | `/api/3/gdpr/commissioner/send-objection` | not wrapped | | route+method verified only | The body is unknown. |
| POST | `/api/3/gdpr/commissioner/send-report` | not wrapped | | route+method verified only | The body is unknown. |

## Payments

The Payments module is disabled at the test school, which answered HTTP 403 to every payments endpoint; the shapes
of the class fund payloads follow the community docs.

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/payments/classfund/summary` | `class_fund_summary()` | `ClassFundSummary` | route+method verified only | The balance and the amount spent. |
| GET | `/api/3/payments/classfund?sort=&search=` | `class_fund_payments(sort=..., search=...)` | `List[ClassFundMonth]` | route+method verified only | `sort` is `asc` or `desc`; the server rejects an empty search with HTTP 400, so the client raises `ValueError` before the request. |
| GET | `/api/3/payments/classfund/paymentsinfo` | `class_fund_payment_info()` | `ClassFundPaymentInfo` | route+method verified only | `iban` and `qr_payment()` (the Czech QR payment string) are computed by the client. |
| GET | `/api/3/payments/regularpayments/summary` | `regular_payments_summary()` | `Any` (raw JSON) | route+method verified only | The payload is undocumented. |
| GET | `/api/3/payments/regularpayments` | does not exist | | LIVE verified 2026-10-15 | HTTP 404 `No HTTP resource was found`; only `/summary` exists. |
| ? | `/api/3/payments/regularpayments/teacher/prescriptions/{id}` and `.../{id}/students` | not wrapped | | other clients | Teacher payment prescriptions; methods and payloads unknown. |
| ? | `/api/3/payments/classfund/teacher/documents/{classId}` | not wrapped | | other clients | Class fund documents of a teacher; method and payload unknown. |

## Teachers

None of these could be called with the parent account; the models follow the community docs, other clients and
captured traffic of the official app, and keep the server's objects in `raw`.

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/3/classbook?from=&to=` | `classbook(since, until)` | `ClassBook` | community docs | `from` and `to` as `YYYY-MM-DDTHH:mm:ss.SSS` without an offset; a date covers the whole day. |
| POST | `/api/3/classbook/{id}` | `save_classbook_record(record)` | `ClassBook` | route+method verified only | The body follows the community docs and captured traffic (`ClassBookRecord.request_body()`); the answer is the saved day with `Hours: null`. |
| GET | `/api/3/classbook/lessonTags` | `lesson_tags()` | `List[LessonTag]` | route+method verified only | HTTP 403 `IsTeacher` for the parent account; the shape follows the community docs. |
| ? | `/api/3/classbook/{lessonId}/absence` | not wrapped | | other clients | Writing the attendance of a lesson; method and body unknown. `lesson_absence()` reads it. |
| GET | `/api/3/lesson/{lessonId}/absence` | `lesson_absence(lesson_id)` | `Dict[str, Any]` | community docs | Raw JSON. `lessonId` is a record's `lesson_id`, not its `id`. |
| GET | `/api/3/lesson/{lessonId}/past` | `lesson_past(lesson_id)` | `LessonPast` | community docs | The last theme and the label of the next record. |
| GET | `/api/3/lesson/{lessonId}/studentsTimetable` | `lesson_students_timetable(lesson_id)` | `Dict[str, Any]` | community docs | Raw JSON. |
| GET | `/api/3/marking/atoms` | `marking_atoms()` | `List[MarkingAtom]` | route+method verified only | HTTP 403 `Some privilege is missing (IsTeacher,IsSuperuser)` for the parent account; the shape follows other clients. |
| GET | `/api/3/marking/marks/{atomId}` | `marking_marks(atom_id)` | `MarkingSheet` | other clients | |
| GET | `/api/3/emergency/configuration` | `emergency_configuration()` | `Any` (raw JSON) | route+method verified only | HTTP 403 `IsTeacher` for the parent account; the payload is undocumented. |
| ? | `/api/3/emergency/startemergency` | not wrapped | | other clients | Starts an emergency alarm; method and body unknown. |
| ? | `/api/3/emergency/participantsselection` | not wrapped | | other clients | Method and body unknown. |

Mark entry by teachers has no publicly known endpoint; `marking_atoms()` and `marking_marks()` only read.

## Public pages (no login)

These are HTML pages of the Bakaláři web, not JSON endpoints; the client parses them with the standard library.

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `/Timetable/Public` | `public_timetable_targets()` | `PublicTargets` | LIVE verified 2026-10-15 | The published classes, teachers and rooms (`<select>` options and off-canvas links). |
| GET | `/Timetable/Public/{Actual\|Permanent\|Next}/{Class\|Teacher\|Room}/{id}` | `public_timetable(kind, target_id, week=...)`, `public_timetable_url(...)` | `PublicTimetable`, `str` | community docs | The embedded `timetableData` JSON (newer servers) or server-rendered cells (older servers), checked against anonymized pages from other clients. A timetable the school does not publish redirects to an error or login page (the test school does that for every timetable), raised as `BakalariPermissionError`. |

## Outside the school's installation

| Method | Path | Client method | Returns | Status | Notes |
|---|---|---|---|---|---|
| GET | `https://sluzby.bakalari.cz/api/v1/municipality` | `SchoolDirectory().municipalities()`, `bakalari.schools.municipalities()` | `List[Municipality]` | LIVE verified 2026-10-15 | No login; `Accept: application/json` (XML otherwise). |
| GET | `https://sluzby.bakalari.cz/api/v1/municipality/{name}` | `SchoolDirectory().schools(name)`, `SchoolDirectory().find(text)`, `bakalari.schools.schools(name)`, `bakalari.schools.find(text)` | `List[School]` | LIVE verified 2026-10-15 | A case-insensitive prefix match; for a name with a dot that answers HTTP 404, the part before the dot is asked for (server quirk). |
| GET | `https://campaign.bakalari.cz/bannerinfo/{Location}/{CampaignCategoryCode}` | not wrapped | | community docs | The information banners of the app; the code is `UserProfile.campaign_category_code`. |

## Endpoints that are not wrapped

`request()` sends any request with the same token handling as the typed methods, and `get_json()` and `post_json()`
decode the JSON answer (see the [library guide](library.md#raw-requests)). Paths are relative to the school's
address; percent-encode ids with `urllib.parse.quote(value, safe="")`. `expected_status=None` accepts any status,
so you can inspect an answer before you rely on it. On the command line, `bakalari api METHOD PATH` sends the same
requests, e.g. `bakalari api GET /.well-known/openid-configuration --no-auth` (see the
[command line reference](cli.md#api)). Never send guessed bodies to write endpoints on a real account: capture the
request of the official app or the web first.

| Endpoint | Why it is not wrapped | How to call it |
|---|---|---|
| `GET /.well-known/openid-configuration` | Not needed: the client logs in through `POST /api/login`. | `client.get_json("/.well-known/openid-configuration", authorized=False)` |
| `GET /api/3/login/{token}?returnUrl=` | A browser step that starts a web session. | Open `client.web_login_url(return_url)` in a browser. |
| `/api/3/unregister-user-notification` | No route matched any method and parameter shape tried. | Unknown. |
| `GET /api/3/timetable/student/{studentId}` | Seen in the official app only; parameters (presumably `date`) and answer unverified. | `client.get_json("/api/3/timetable/student/" + quote(student_id, safe=""), {"date": "2026-10-22"})` |
| `PUT /api/3/komens/message/{id}` | The body is unknown. | `client.request("PUT", "/api/3/komens/message/" + quote(message_id, safe=""), json_body=body, expected_status=(200, 204))` |
| `GET /api/3/komens/message-types/edit/{conceptId}`, `POST /api/3/komens/concept`, `POST /api/3/komens/concepts` | Komens drafts: the payloads are unknown (`send_message()` sends `DraftDate` as null; its `extra=` argument overrides any body key). | `client.get_json("/api/3/komens/message-types/edit/" + quote(concept_id, safe=""))`; `client.request("POST", "/api/3/komens/concepts", json_body=body, expected_status=None)` |
| `/api/3/gdpr/consent` | Answering a consent: the route shape and the body are unknown. | Unknown; answer consents on the web (`web_login_url()`). |
| `/api/3/gdpr/commissioner` | No route matches. | Unknown. |
| `POST /api/3/gdpr/commissioner/send-objection`, `POST /api/3/gdpr/commissioner/send-report` | The bodies are unknown. | `client.request("POST", "/api/3/gdpr/commissioner/send-objection", json_body=body, expected_status=None)` |
| `/api/3/payments/regularpayments/teacher/prescriptions/{id}[/students]`, `/api/3/payments/classfund/teacher/documents/{classId}` | Teacher endpoints with unknown methods and payloads. | `client.get_json("/api/3/payments/classfund/teacher/documents/" + quote(class_id, safe=""))` |
| `/api/3/classbook/{lessonId}/absence` (write) | Method and body unknown. | `client.request("POST", "/api/3/classbook/" + quote(lesson_id, safe="") + "/absence", json_body=body, expected_status=None)` |
| `/api/3/emergency/startemergency`, `/api/3/emergency/participantsselection` | Methods and bodies unknown; an emergency alarm must not be triggered by experiment. | Unknown. |
| `https://campaign.bakalari.cz/bannerinfo/{Location}/{CampaignCategoryCode}` | Information banners on another host, which `request()` does not reach. | Any HTTP client, e.g. `urllib.request.urlopen(...)`, with `UserProfile.campaign_category_code`. |

A read-only example: the discovery document, which needs no login, and a call to the unverified student timetable
that accepts any status, so the answer can be inspected first.

```python
from urllib.parse import quote

from bakalari import BakalariClient

client = BakalariClient.from_env()
discovery = client.get_json("/.well-known/openid-configuration", authorized=False)
print(sorted(discovery))

response = client.request(
    "GET", "/api/3/timetable/student/" + quote("STUDENT-ID", safe=""), params={"date": "2026-10-22"},
    expected_status=None,
)
print(response.status, response.content_type)
```
