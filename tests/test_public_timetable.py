import copy
import datetime as dt
import json
import unittest

from bakalari import (
    BakalariContractError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    Hour,
    HttpResponse,
)
from bakalari.public_timetable import (
    LOGIN_REQUIRED,
    NOT_PUBLISHED,
    PublicDay,
    PublicLesson,
    PublicTarget,
    PublicTargets,
    PublicTimetable,
    _resolve_dates,
    parse_public_targets,
    parse_public_timetable,
    public_timetable_path,
)

from .support import BASE_URL, json_response, load_fixture, load_text_fixture, make_client, text_response

ACTUAL_PAGE = load_text_fixture("public_timetable_actual.html")
ACTUAL_DATA = load_fixture("public_timetable_actual.json")
PERMANENT_PAGE = load_text_fixture("public_timetable_permanent.html")
INDEX_PAGE = load_text_fixture("public_timetable_index.html")
LEGACY_PAGE = load_text_fixture("public_timetable_legacy.html")
ERROR_PAGE = load_text_fixture("public_timetable_errinfo.html")
LOGIN_PAGE = """<!DOCTYPE html><html><head><title>Přihlášení</title></head><body>
<form method="post" action="/bakaweb/Login"><input type="text" name="username" id="username" />
<input type="password" name="password" id="password" /><input type="submit" value="Přihlásit" /></form></body></html>"""
ERROR_URL = (BASE_URL + "/next/errinfo.aspx?e=K+po%c5%beadovan%c3%a9+str%c3%a1nce+nem%c3%a1te+p%c5%99%c3%adstup."
             "&requestId=00000000-1111-2222-3333-444444444444")
REFUSED = "K požadované stránce nemáte přístup."


def page_response(page, url="", status=200, headers=None):
    response = text_response(status, page, url=url)
    return HttpResponse(status, {**response.headers, **(headers or {})}, response.body, url)


class TargetParsingTest(unittest.TestCase):
    def test_select_options_and_canvas_links_are_merged_by_id(self):
        targets = parse_public_targets(ACTUAL_PAGE)
        self.assertEqual([(target.id, target.name) for target in targets.classes],
                         [("2B", "2.B"), ("1A", "1.A"), ("ZQ", "3.C")])
        # The select lists three teachers; the off-canvas list adds "U  19" (written percent-encoded in its link).
        self.assertEqual([target.id for target in targets.teachers], ["UQX01", "UZK(7)", "UFI02", "U  19"])
        self.assertEqual(targets.teachers[0], PublicTarget("teacher", "UQX01", "Testová Ema"))  # entities decoded
        self.assertEqual([(target.id, target.name) for target in targets.rooms],
                         [("R1", "12"), ("G 7", "14"), ("KL", "Tělocvična")])
        self.assertTrue(all(target.kind == "room" for target in targets.rooms))

    def test_canvas_layout_alone_with_literal_spaces_and_a_path_prefix(self):
        targets = parse_public_targets(INDEX_PAGE)
        self.assertEqual([target.id for target in targets.teachers], ["UQX01", "U  19", "UZK(7)", "UFI02"])
        self.assertEqual(targets.teachers[1].name, "Vzorový Karel")
        self.assertEqual([target.id for target in targets.rooms], ["R1", "G 7", "KL"])

    def test_legacy_select_markup_without_end_tags_and_empty_options(self):
        page = """<select id="selectedClass"><option></option><option value="">Prázdná<option value=" 5A">5.A
        <option value="5B" selected>5.B</select>
        <select id="selectedRoom"><option>bez hodnoty</option><option value="U&amp;1">Učebna &#8470; 1</option>
        </select><select id="other"><option value="X">X</option></select>"""
        targets = parse_public_targets(page)
        self.assertEqual([(target.id, target.name) for target in targets.classes], [(" 5A", "5.A"), ("5B", "5.B")])
        self.assertEqual(targets.rooms, (PublicTarget("room", "U&1", "Učebna № 1"),))
        self.assertEqual(targets.teachers, ())

    def test_links_outside_the_canvases_or_without_a_target_are_ignored(self):
        page = """<a href="/timetable/public/Actual/class/9Z">9.Z</a>
        <div id="class_canvas"><a href="/timetable/public/Actual/class/">nic</a><a href="#">nic</a>
        <a href="https://skola.example/timetable/public/Next/Class/7C?x=1#top"><span>7.C</span></a></div>"""
        self.assertEqual(parse_public_targets(page).classes, (PublicTarget("class", "7C", "7.C"),))

    def test_helpers(self):
        targets = parse_public_targets(ACTUAL_PAGE)
        self.assertEqual(len(targets.all_targets), 10)
        self.assertEqual(targets.of_kind("Teacher"), targets.teachers)
        self.assertEqual(targets.find("U  19").name, "Vzorový Karel")
        self.assertEqual(targets.find("u19").id, "U  19")  # case and spaces are ignored after the exact match
        self.assertEqual(targets.find("vzorový karel", kind="teacher").id, "U  19")
        self.assertIsNone(targets.find("U  19", kind="room"))
        self.assertEqual(targets.find("tělocvična").id, "KL")
        self.assertIsNone(targets.find("nobody"))
        self.assertEqual(str(targets.rooms[2]), "Tělocvična")
        self.assertEqual(str(PublicTarget("class", "2B")), "2B")
        with self.assertRaises(ValueError):
            targets.of_kind("student")

    def test_to_dict(self):
        data = parse_public_targets(INDEX_PAGE).to_dict()
        self.assertEqual(data["teachers"][1], {"kind": "teacher", "id": "U  19", "name": "Vzorový Karel"})
        json.dumps(data, ensure_ascii=False)

    def test_page_without_target_lists(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_public_targets(ERROR_PAGE)
        self.assertIn(REFUSED, str(raised.exception))
        with self.assertRaises(BakalariContractError):
            parse_public_targets("<html><body>Nic</body></html>")
        self.assertEqual(parse_public_targets('<select id="selectedTeacher"><option></option></select>'),
                         PublicTargets())


class ActualTimetableParsingTest(unittest.TestCase):
    def setUp(self):
        self.timetable = parse_public_timetable(ACTUAL_PAGE)

    def test_page_names_kind_target_and_week(self):
        timetable = self.timetable
        self.assertEqual((timetable.kind, timetable.target_id, timetable.week), ("class", "2B", "actual"))
        other = parse_public_timetable(ACTUAL_PAGE, kind="room", target_id="R1", week="next")
        self.assertEqual((other.kind, other.target_id, other.week), ("room", "R1", "next"))
        other = parse_public_timetable(ACTUAL_PAGE, kind="Room", week="NEXT")  # normalized like the endpoint does
        self.assertEqual((other.kind, other.target_id, other.week), ("room", "2B", "next"))
        for arguments in ({"kind": "student"}, {"week": "last"}):
            with self.assertRaises(ValueError):
                parse_public_timetable(ACTUAL_PAGE, **arguments)

    def test_hours_get_the_servers_hour_numbers(self):
        hours = self.timetable.hours
        self.assertEqual([hour.caption for hour in hours], ["0", "1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual([hour.id for hour in hours], [2, 3, 4, 5, 6, 7, 8, 9])  # lessons reveal 3..6; the rest follow
        self.assertIsInstance(hours[0], Hour)
        self.assertEqual((hours[3].begin, hours[3].end), ("10:00", "10:45"))

    def test_days_and_their_dates(self):
        days = self.timetable.days
        self.assertEqual([(day.day_abbrev, day.date_text) for day in days],
                         [("po", "16.11."), ("út", "17.11."), ("st", "18.11."), ("čt", "19.11."), ("pá", "20.11.")])
        # Lessons and supervisions name the year; the day off and the empty Friday follow the rest of the week.
        self.assertEqual([day.date for day in days], [dt.date(2026, 11, d) for d in (16, 17, 18, 19, 20)])
        self.assertEqual([day.day_of_week for day in days], [1, 2, 3, 4, 5])
        self.assertEqual((days[1].day_off, days[1].day_off_name, days[1].lessons), (True, "státní svátek", ()))
        self.assertEqual(days[4].lessons, ())
        self.assertIsInstance(days[0], PublicDay)
        self.assertEqual(days[0].raw["DayAbbrev"], "po")

    def test_lessons_are_ordered_by_time(self):
        monday = self.timetable.days[0].lessons
        self.assertEqual([(lesson.hour_caption, lesson.subject_abbrev) for lesson in monday],
                         [("1", "Aj"), ("1", "Nj"), ("1", ""), ("2", "Fy"), ("3", "M")])
        self.assertEqual([lesson.hour_index for lesson in monday], [3, 3, 3, 4, 5])

    def test_regular_lesson(self):
        lesson = self.timetable.days[0].lessons[0]
        self.assertEqual((lesson.begin, lesson.end, lesson.subject, lesson.subject_abbrev),
                         ("8:00", "8:45", "Anglický jazyk", "Aj"))
        self.assertEqual((lesson.teacher, lesson.teacher_abbrev), ("Ing. Karel Vzorový", "Vz"))
        self.assertEqual((lesson.room, lesson.room_name), ("14", "14 - jazyková učebna"))
        self.assertEqual((lesson.group, lesson.group_name), ("Aj1", "Aj1 - angličtina 1"))
        self.assertEqual((lesson.changed, lesson.change_info, lesson.change_type, lesson.absent_info),
                         (False, "", "", ""))
        self.assertEqual((lesson.atom_type, lesson.removed, lesson.cycle), ("atom", False, ""))
        self.assertEqual((lesson.raw["Teacher"], lesson.raw["HourIndex"]), ("Vz", 3))
        self.assertIsInstance(lesson, PublicLesson)

    def test_removed_lesson(self):
        removed = self.timetable.days[0].lessons[2]
        self.assertEqual((removed.atom_type, removed.removed, removed.changed, removed.change_type),
                         ("removed", True, True, "Removed"))
        self.assertEqual(removed.hour_index, 3)  # the atom says 0; its hour entry knows the slot
        self.assertEqual((removed.begin, removed.end, removed.hour_caption), ("8:00", "8:45", "1"))
        self.assertEqual((removed.subject, removed.teacher, removed.room), ("", "", ""))
        self.assertEqual(removed.change_info, "Odebráno z rozvrhu (Fy, Fiktivní Oto)")
        self.assertEqual(removed.title, "Odebráno z rozvrhu (Fy, Fiktivní Oto)")

    def test_changed_lessons(self):
        room_change = self.timetable.days[0].lessons[3]
        self.assertEqual((room_change.changed, room_change.change_type, room_change.change_info),
                         (True, "RoomChanged", "Změna místnosti: 14 (12)"))
        substitution = self.timetable.days[2].lessons[0]
        self.assertEqual((substitution.change_type, substitution.absent_info), ("Substitution", "nem | nemoc"))
        self.assertEqual((substitution.room, substitution.theme), ("12", "Vyjmenovaná slova po B"))  # trimmed
        self.assertEqual(self.timetable.changed_lessons, [self.timetable.days[0].lessons[2], room_change, substitution])

    def test_merged_groups_written_as_html_become_a_list(self):
        # GroupsNames and GroupsFullNames are rendered as HTML and separate the groups of a merged lesson with <br/>.
        data = copy.deepcopy(ACTUAL_DATA)
        atom = data["Days"][0]["Hours"][1]["Atoms"][0]
        atom["GroupsNames"] = "2.B Aj1<br/>2.C Aj1"
        atom["GroupsFullNames"] = "2.B Aj1 - angličtina 1<br />2.C Aj1 - angličtina &amp; konverzace"
        lesson = PublicTimetable.from_json(data).days[0].lessons[0]
        self.assertEqual(lesson.group, "2.B Aj1, 2.C Aj1")
        self.assertEqual(lesson.group_name, "2.B Aj1 - angličtina 1, 2.C Aj1 - angličtina & konverzace")
        self.assertTrue(lesson.format().endswith("| 2.B Aj1, 2.C Aj1"))
        atom["GroupsFullNames"] = None
        self.assertEqual(PublicTimetable.from_json(data).days[0].lessons[0].group_name, "Aj1 - angličtina 1")  # tooltip
        atom["GroupsNames"] = "Aj1  S"  # plain text stays as sent, only trimmed
        self.assertEqual(PublicTimetable.from_json(data).days[0].lessons[0].group, "Aj1  S")

    def test_theme_and_notice(self):
        lesson = self.timetable.days[3].lessons[0]
        self.assertEqual((lesson.theme, lesson.notice, lesson.hour_caption),
                         ("Podzimní krajina", "Přinést vodovky", "4"))

    def test_lookups(self):
        self.assertEqual(len(self.timetable.lessons), 7)
        self.assertIs(self.timetable.day("st"), self.timetable.days[2])
        self.assertIs(self.timetable.day(dt.date(2026, 11, 19)), self.timetable.days[3])
        self.assertIs(self.timetable.day("2026-11-20"), self.timetable.days[4])
        self.assertIsNone(self.timetable.day("so"))
        self.assertIsNone(self.timetable.day(dt.date(2026, 11, 23)))
        lesson = self.timetable.days[3].lessons[0]
        self.assertEqual(self.timetable.hour_of(lesson).id, 6)
        self.assertEqual(self.timetable.hour_of(PublicLesson(begin="12:45")).caption, "6")
        self.assertIsNone(self.timetable.hour_of(PublicLesson(begin="6:00")))

    def test_format(self):
        lines = self.timetable.format().splitlines()
        self.assertEqual(lines[0], "po 16.11. (2026-11-16): 5 lesson(s)")
        self.assertEqual(lines[1], "     1.  8:00-8:45  Anglický jazyk | Ing. Karel Vzorový | 14 | Aj1")
        self.assertEqual(lines[3], "     1.  8:00-8:45  Odebráno z rozvrhu (Fy, Fiktivní Oto)")
        self.assertEqual(lines[4], "     2.  8:55-9:40  Fyzika | PaedDr. Oto Fiktivní | 14 [Změna místnosti: 14 (12)]")
        self.assertEqual(lines[6], "út 17.11. (2026-11-17): day off (státní svátek)")
        self.assertEqual(lines[-1], "pá 20.11. (2026-11-20): 0 lesson(s)")

    def test_to_dict_is_json_serialisable(self):
        data = self.timetable.to_dict()
        text = json.dumps(data, ensure_ascii=False)
        self.assertNotIn('"raw"', text)
        self.assertEqual(data["days"][0]["date"], "2026-11-16")
        self.assertEqual(data["days"][0]["lessons"][0]["teacher"], "Ing. Karel Vzorový")
        self.assertEqual({key: data["hours"][1][key] for key in ("id", "caption", "begin", "end")},
                         {"id": 3, "caption": "1", "begin": "8:00", "end": "8:45"})

    def test_embedded_json_equals_the_json_model(self):
        model = PublicTimetable.from_json(ACTUAL_DATA, kind="class", target_id="2B", week="actual")
        self.assertEqual(model, self.timetable)
        self.assertEqual(self.timetable.raw["ShowTeachers"], True)


class OtherLayoutsTest(unittest.TestCase):
    def test_permanent_timetable_has_no_dates_but_week_cycles(self):
        timetable = parse_public_timetable(PERMANENT_PAGE)
        self.assertEqual((timetable.kind, timetable.target_id, timetable.week), ("teacher", "U  19", "permanent"))
        self.assertEqual([(day.day_abbrev, day.date_text, day.date) for day in timetable.days],
                         [("po", "", None), ("út", "", None)])
        self.assertEqual([lesson.cycle for lesson in timetable.days[0].lessons], ["S", "L"])
        self.assertEqual(timetable.days[0].format_summary(), "po: 2 lesson(s)")

    def test_page_without_a_selected_target_has_empty_days(self):
        timetable = parse_public_timetable(INDEX_PAGE)
        self.assertEqual((timetable.kind, timetable.target_id, timetable.week), ("", "", "actual"))
        self.assertEqual([day.lessons for day in timetable.days], [()] * 5)
        self.assertEqual([hour.id for hour in timetable.hours], list(range(8)))  # no lesson reveals a number

    def test_server_rendered_layout(self):
        timetable = parse_public_timetable(LEGACY_PAGE, kind="class", target_id="2B", week="actual")
        self.assertEqual((timetable.kind, timetable.raw), ("class", {}))
        monday, tuesday = timetable.days
        self.assertEqual((monday.day_abbrev, monday.date_text, monday.date), ("po", "16.11.", None))  # no year
        self.assertEqual((tuesday.day_off, tuesday.day_off_name, tuesday.lessons), (True, "Státní svátek", ()))
        english, maths, physics = monday.lessons  # ordered by time; the supervision guard is not a lesson
        self.assertEqual((english.hour_caption, english.begin, english.end), ("1", "8:00", "8:45"))
        self.assertEqual((english.subject, english.subject_abbrev, english.cycle), ("Anglický jazyk", "Aj", "S"))
        self.assertEqual((english.teacher, english.teacher_abbrev), ("Ing. Karel Vzorový", "Vz"))
        self.assertEqual((english.room, english.group, english.theme), ("14", "2.B Aj1", "Present simple & continuous"))
        self.assertEqual((english.hour_index, english.changed, english.raw["type"]), (None, False, "atom"))
        self.assertEqual((maths.subject, maths.teacher_abbrev, maths.group_name), ("Matematika", "Te", "2.B celá"))
        self.assertEqual((physics.atom_type, physics.change_type, physics.changed), ("removed", "Removed", True))
        self.assertEqual(physics.change_info, "Odebráno z rozvrhu (Fy, Fiktivní Oto)")
        self.assertEqual([(hour.caption, hour.begin) for hour in timetable.hours],
                         [("1", "8:00"), ("2", "8:55"), ("3", "10:00")])

    def test_server_rendered_detail_with_a_full_date(self):
        detail = json.dumps({"type": "atom", "subjecttext": "Dějepis", "day": "17.11.2026 (úterý)",
                             "time": "3 (10:00 - 10:45)", "hourIndex": 5, "changeinfo": "", "teacher": None})
        page = (f"""<div class="bk-timetable-row"><span class="bk-day-day">út</span><span class="bk-day-date">"""
                f"""17.11.</span><div class="day-item-hover" data-detail='{detail}'><div class="middle">D"""
                """<div class="change-badge">S</div><span class="teacher-name">Fi</span></div></div></div>""")
        day = parse_public_timetable(page).days[0]
        self.assertEqual(day.date, dt.date(2026, 11, 17))
        lesson = day.lessons[0]
        self.assertEqual((lesson.subject, lesson.subject_abbrev, lesson.teacher_abbrev), ("Dějepis", "D", "Fi"))
        self.assertEqual((lesson.hour_index, lesson.hour_caption, lesson.begin), (5, "3", "10:00"))

    def test_server_rendered_groups_separated_by_line_breaks(self):
        detail = json.dumps({"type": "atom", "subjecttext": "Tělesná výchova | po 16.11. | 1 (8:00 - 8:45)",
                             "group": "2.B Tv - chlapci<br/>2.C Tv - chlapci"})
        page = (f"""<div class="bk-timetable-row"><span class="bk-day-day">po</span><div class="day-item-hover" """
                f"""data-detail='{detail}'><div class="left"><div>2.B Tv<br/>2.C   Tv<br>&nbsp;</div></div>"""
                """<div class="middle">TV</div></div></div>""")
        lesson = parse_public_timetable(page).days[0].lessons[0]
        self.assertEqual((lesson.group, lesson.subject_abbrev, lesson.hour_caption), ("2.B Tv, 2.C Tv", "TV", "1"))
        self.assertEqual(lesson.group_name, "2.B Tv - chlapci, 2.C Tv - chlapci")

    def test_page_without_a_timetable(self):
        with self.assertRaises(BakalariContractError) as raised:
            parse_public_timetable(ERROR_PAGE)
        self.assertIn(REFUSED, str(raised.exception))
        broken = "<script>const timetableData = {broken;</script>"
        with self.assertRaises(BakalariContractError):
            parse_public_timetable(broken)

    def test_newer_page_whose_data_cannot_be_read_is_not_mistaken_for_server_rendered_days(self):
        # The page's template has an empty timetable row with the day-off block; it must not become a day off.
        for replacement in ("const timetableData = {broken", "const timetableData = null; const other = {"):
            page = ACTUAL_PAGE.replace("const timetableData = {", replacement)
            with self.assertRaises(BakalariContractError):
                parse_public_timetable(page)


class LenientParsingTest(unittest.TestCase):
    def test_contract_of_the_embedded_json(self):
        with self.assertRaises(BakalariContractError) as raised:
            PublicTimetable.from_json({"Days": []})
        self.assertEqual(raised.exception.problems, ["Missing list 'Hours'"])
        with self.assertRaises(BakalariContractError):
            PublicTimetable.from_json([], validate=False)
        self.assertEqual(PublicTimetable.from_json({"Days": None}, validate=False).days, ())
        page = ACTUAL_PAGE.replace('"Hours":[{"Caption"', '"HoursX":[{"Caption"')
        with self.assertRaises(BakalariContractError):
            parse_public_timetable(page)
        self.assertEqual(len(parse_public_timetable(page, validate=False).lessons), 7)

    def test_atoms_without_tooltip_or_fields_get_defaults(self):
        data = copy.deepcopy(ACTUAL_DATA)
        atoms = data["Days"][3]["Hours"][0]["Atoms"]
        atoms[0]["TooltipDetails"] = "{not json"
        atoms.append({"Begin": "13:40:00", "End": "14:25:00"})
        atoms.append({"Time": "12:45 - 13:30", "TooltipDetails": None, "Type": None})
        atoms.append("not an atom")
        thursday = PublicTimetable.from_json(data).days[3]
        painting, empty_late, empty = thursday.lessons[0], thursday.lessons[2], thursday.lessons[1]
        self.assertEqual((painting.subject, painting.hour_caption), ("Výtvarná výchova", "4"))  # caption from the slots
        self.assertEqual((empty.begin, empty.end, empty.hour_caption, empty.atom_type), ("12:45", "13:30", "6", "atom"))
        self.assertEqual((empty.hour_index, empty.subject, empty.title), (6, "", "-"))
        self.assertEqual((empty_late.begin, empty_late.hour_caption, empty_late.hour_index), ("13:40", "7", 6))

    def test_hour_numbers_continue_from_the_nearest_known_slot(self):
        # Lessons reveal hours 3 and 4 for the slots "1" and "2", then 8 for slot "5": the server skips a hidden
        # hour, so slot "6" is 9 (continuing from slot "5"), not 8 again.
        hours = [{"Caption": str(number), "BeginTime": f"{8 + number}:00", "EndTime": f"{8 + number}:45"}
                 for number in range(8)]
        atoms = [{"Begin": f"{8 + slot:02d}:00:00", "HourIndex": index} for slot, index in ((1, 3), (2, 4), (5, 8))]
        data = {"Hours": hours, "Days": [{"DayAbbrev": "po", "Hours": [{"Atoms": atoms}]}]}
        self.assertEqual([hour.id for hour in PublicTimetable.from_json(data).hours], [2, 3, 4, 5, 7, 8, 9, 10])

    def test_dates_are_resolved_only_when_the_page_determines_them(self):
        nov16, nov17, nov18 = dt.date(2026, 11, 16), dt.date(2026, 11, 17), dt.date(2026, 11, 18)
        self.assertEqual(_resolve_dates([("po", "16.11.", [nov16]), ("út", "17.11.", [])]), [nov16, nov17])
        self.assertEqual(_resolve_dates([("po", "16.11.", []), ("út", "17.11.", [])]), [None, None])
        self.assertEqual(_resolve_dates([("po", "16.11.", [nov18])]), [None])  # another day's date
        self.assertEqual(_resolve_dates([("út", "16.11.", [nov16])]), [None])  # contradicting weekday
        # Only consistent dates anchor the others.
        self.assertEqual(_resolve_dates([("út", "16.11.", [nov16]), ("st", "18.11.", [nov18]), ("čt", "19.11.", [])]),
                         [None, nov18, dt.date(2026, 11, 19)])
        self.assertEqual(_resolve_dates([("po", "", [nov16])]), [None])  # permanent timetable
        # A week across the new year: the year of each day follows from the nearest known date.
        across = _resolve_dates([("po", "28.12.", [dt.date(2026, 12, 28)]), ("pá", "1.1.", [])])
        self.assertEqual(across, [dt.date(2026, 12, 28), dt.date(2027, 1, 1)])
        self.assertEqual(_resolve_dates([("ne", "29.2.", []), ("po", "1.3.", [dt.date(2027, 3, 1)])]),
                         [None, dt.date(2027, 3, 1)])


class EndpointTest(unittest.TestCase):
    def test_targets_need_no_login(self):
        client, transport = make_client(page_response(ACTUAL_PAGE))
        targets = client.public_timetable_targets()
        call = transport.calls[0]
        self.assertEqual((call.method, call.api_path, call.query), ("GET", "/Timetable/Public", {}))
        self.assertEqual(call.headers["Accept"], "text/html")
        self.assertNotIn("Authorization", call.headers)
        self.assertEqual(len(transport.calls), 1)
        self.assertFalse(client.is_authenticated)
        self.assertEqual(len(targets.teachers), 4)

    def test_timetable_path_kind_week_and_quoted_id(self):
        client, transport = make_client(page_response(ACTUAL_PAGE), page_response(PERMANENT_PAGE),
                                        page_response(ACTUAL_PAGE))
        actual = client.public_timetable("class", "2B")
        permanent = client.public_timetable("TEACHER", "U  19", week="Permanent")
        client.public_timetable("room", "G 7", week="next")
        self.assertEqual([call.api_path for call in transport.calls], [
            "/Timetable/Public/Actual/Class/2B",
            "/Timetable/Public/Permanent/Teacher/U%20%2019",
            "/Timetable/Public/Next/Room/G%207",
        ])
        self.assertEqual((actual.kind, actual.target_id, actual.week), ("class", "2B", "actual"))
        self.assertEqual((permanent.kind, permanent.target_id, permanent.week), ("teacher", "U  19", "permanent"))
        self.assertTrue(all("Authorization" not in call.headers for call in transport.calls))

    def test_invalid_arguments_send_nothing(self):
        client, transport = make_client()
        for kind, target_id, week in (("student", "1", "actual"), ("class", " ", "actual"), ("class", "1", "last")):
            with self.assertRaises(ValueError):
                client.public_timetable(kind, target_id, week=week)
        self.assertEqual(transport.calls, [])

    def test_path_and_url(self):
        self.assertEqual(public_timetable_path("Room", "ZSQ[1]", week="NEXT"), "/Timetable/Public/Next/Room/ZSQ%5B1%5D")
        client, _ = make_client()
        self.assertEqual(client.public_timetable_url("teacher", "U  19"),
                         BASE_URL + "/Timetable/Public/Actual/Teacher/U%20%2019")

    def test_redirect_to_the_error_page_is_a_permission_error(self):
        client, _ = make_client(page_response(ERROR_PAGE, url=ERROR_URL))
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable("class", "0C")
        error = raised.exception
        self.assertEqual((error.method, error.path), ("GET", "/Timetable/Public/Actual/Class/0C"))
        self.assertEqual((error.status, error.expected, error.message), (403, 200, REFUSED))
        self.assertIsInstance(error, BakalariHTTPError)

    def test_unfollowed_redirects(self):
        error_location = page_response("", status=302, headers={"Location": "/bakaweb/next/errinfo.aspx?e=Chyba"})
        login_location = page_response("", status=302, headers={"Location": "/bakaweb/Login?ReturnUrl=%2fbakaweb"})
        elsewhere = page_response("", status=301, headers={"Location": "https://other.example/Timetable/Public"})
        client, _ = make_client(error_location, login_location, elsewhere)
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable("class", "0C")
        self.assertEqual(raised.exception.message, "Chyba")
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable_targets()
        self.assertEqual(raised.exception.message, LOGIN_REQUIRED)
        with self.assertRaises(BakalariHTTPError) as raised:
            client.public_timetable_targets()
        self.assertNotIsInstance(raised.exception, BakalariPermissionError)
        self.assertEqual(raised.exception.status, 301)
        self.assertIn("other.example", str(raised.exception))

    def test_error_and_login_pages_are_recognised_by_their_content(self):
        reason_parameter = "e=K+po%c5%beadovan%c3%a9+str%c3%a1nce+nem%c3%a1te+p%c5%99%c3%adstup.&amp;"
        bare_error = ERROR_PAGE.replace(reason_parameter, "")
        client, _ = make_client(page_response(ERROR_PAGE), page_response(bare_error), page_response(LOGIN_PAGE),
                                page_response(ERROR_PAGE.replace("K požadované stránce nemáte přístup.", "")
                                              .replace("errinfo.aspx?e=", "errinfo.aspx?x=")))
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable("class", "0C")
        self.assertEqual(raised.exception.message, REFUSED)
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable("class", "0C")
        self.assertEqual(raised.exception.message, REFUSED)  # from the page's error text
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable_targets()
        self.assertEqual(raised.exception.message, LOGIN_REQUIRED)
        with self.assertRaises(BakalariPermissionError) as raised:
            client.public_timetable("class", "0C")
        self.assertEqual(raised.exception.message, NOT_PUBLISHED)

    def test_a_target_named_like_the_login_page_is_not_a_refusal(self):
        url = BASE_URL + "/Timetable/Public/Actual/Room/login"
        client, _ = make_client(page_response(ACTUAL_PAGE, url=url))
        self.assertEqual(client.public_timetable("room", "login").target_id, "login")

    def test_http_errors_propagate(self):
        client, _ = make_client(json_response(404, {"Message": "Nenalezeno"}), json_response(500, {"Message": "x"}))
        with self.assertRaises(BakalariNotFoundError):
            client.public_timetable_targets()
        with self.assertRaises(BakalariHTTPError) as raised:
            client.public_timetable("class", "2B")
        self.assertEqual(raised.exception.status, 500)

    def test_page_charset_and_contract(self):
        legacy = HttpResponse(200, {"Content-Type": "text/html; charset=windows-1250"}, LEGACY_PAGE.encode("cp1250"))
        unknown = HttpResponse(200, {"Content-Type": "text/html; charset=x-unknown"}, ACTUAL_PAGE.encode("utf-8"))
        client, _ = make_client(legacy, unknown, page_response("<html><body>Údržba</body></html>"),
                                page_response(ERROR_PAGE.replace("errinfo", "info")))
        legacy_days = client.public_timetable("class", "2B").days  # "út" and "2.B celá" are raw cp1250 bytes
        self.assertEqual((legacy_days[1].day_abbrev, legacy_days[1].day_off_name), ("út", "Státní svátek"))
        self.assertEqual(legacy_days[0].lessons[1].group_name, "2.B celá")
        self.assertEqual(client.public_timetable("class", "2B").days[0].lessons[0].subject, "Anglický jazyk")
        with self.assertRaises(BakalariContractError):
            client.public_timetable("class", "2B")
        with self.assertRaises(BakalariContractError):
            client.public_timetable_targets()

    def test_page_charset_from_the_meta_tag(self):
        page = LEGACY_PAGE.replace('<meta charset="utf-8" />', '<meta http-equiv="Content-Type" '
                                   'content="text/html; charset=windows-1250" />')
        undeclared = HttpResponse(200, {"Content-Type": "text/html"}, page.encode("cp1250"))
        bare = HttpResponse(200, {}, LEGACY_PAGE.encode("utf-8"))
        client, _ = make_client(undeclared, bare)
        for days in (client.public_timetable("class", "2B").days, client.public_timetable("class", "2B").days):
            self.assertEqual((days[1].day_abbrev, days[1].day_off_name), ("út", "Státní svátek"))
            self.assertEqual(days[0].lessons[1].group_name, "2.B celá")

    def test_a_target_object_is_addressed_by_its_id(self):
        target = parse_public_targets(INDEX_PAGE).find("Vzorový Karel")
        self.assertEqual(str(target), "Vzorový Karel")  # str() is the name, which must not end up in the path
        client, transport = make_client(page_response(PERMANENT_PAGE))
        timetable = client.public_timetable("teacher", target, week="permanent")
        self.assertEqual(transport.calls[0].api_path, "/Timetable/Public/Permanent/Teacher/U%20%2019")
        self.assertEqual(timetable.target_id, "U  19")
        self.assertEqual(client.public_timetable_url("teacher", target),
                         BASE_URL + "/Timetable/Public/Actual/Teacher/U%20%2019")
        self.assertEqual(public_timetable_path("teacher", target), "/Timetable/Public/Actual/Teacher/U%20%2019")

    def test_validation_can_be_disabled(self):
        page = ACTUAL_PAGE.replace('"Hours":[{"Caption"', '"HoursX":[{"Caption"')
        client, _ = make_client(page_response(page), page_response(page))
        with self.assertRaises(BakalariContractError):
            client.public_timetable("class", "2B")
        self.assertEqual(client.public_timetable("class", "2B", validate=False).hours, ())


if __name__ == "__main__":
    unittest.main()
