"""Explicit MCP tool allowlist and its JSON schemas (no arbitrary client dispatch)."""
from __future__ import annotations

import base64
import datetime as dt
import inspect
from dataclasses import dataclass
from typing import Any, Dict, List

from .client import BakalariClient
from .schools import SchoolDirectory

MAX_ATTACHMENT_BYTES = 512 * 1024


def string(description: str = "", *choices: str) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "string", "description": description}
    if choices:
        schema["enum"] = list(choices)
    return schema


ID = {"type": "string", "minLength": 1, "description": "Exact opaque identifier from a previous result; keep spaces."}
DATE = {"type": "string", "format": "date", "description": "Calendar date in YYYY-MM-DD format."}
BOOL = {"type": "boolean"}
IDS = {"type": "array", "items": ID}


def object_schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    target: str = "client"
    method: str = ""
    write: bool = False
    idempotent: bool = True

    def definition(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description, "inputSchema": self.schema,
            "annotations": {
                "readOnlyHint": not self.write, "destructiveHint": self.write,
                "idempotentHint": self.idempotent, "openWorldHint": True,
            },
        }


def build_tools(allow_writes: bool) -> Dict[str, Tool]:
    """Build a fresh catalog; only explicitly listed methods and arguments are exposed."""
    tools: Dict[str, Tool] = {}

    def add(name: str, description: str, *, write: bool = False, idempotent: bool = True,
            target: str = "client", method: str = "", **properties: Any) -> None:
        if write and not allow_writes:
            return
        owner = SchoolDirectory if target == "directory" else BakalariClient
        parameters = inspect.signature(getattr(owner, method or name)).parameters
        required = []
        schemas = {}
        for key, schema in properties.items():
            schema = dict(schema)
            default = parameters[key].default
            if default is inspect.Parameter.empty:
                required.append(key)
            elif default is not None:
                schema["default"] = list(default) if isinstance(default, tuple) else default
            schemas[key] = schema
        tools[name] = Tool(name, description, object_schema(schemas, required), target, method or name,
                           write, idempotent)

    for name, description in {
        "api_version": "Read this school's API version. No login required.",
        "available_api_versions": "List API versions supported by this school. No login required.",
        "user_profile": "Read the account's name, role, class, school, students, modules and rights.",
        "enabled_modules": "List modules available to this account.",
        "student_at_school": "Read whether the student is at school (requires AccessSystem).",
        "web_modules": "List available school web modules.",
        "permanent_timetable": "Read the student's permanent weekly timetable.",
        "new_marks_count": "Read the new-mark counter; use marks for individual marks.",
        "final_marks": "Read certificate marks for each term.",
        "pedagogical_measures": "Read pedagogical measures and commendations.",
        "absence": "Read absence by date and subject, including the school's absence threshold.",
        "subjects": "List subjects, teachers and their contact details.",
        "active_homeworks_count": "Read the number of active homework assignments.",
        "rating_templates": "Read Komens rating templates (teacher rights required).",
        "gdpr_commissioners": "Read school data protection officer contacts.",
        "consents": "Read the account's GDPR consents without answering them.",
        "child_consents": "Read a parent's children's GDPR consents without answering them.",
        "new_consents_count": "Read the number of new GDPR consents.",
        "class_fund_summary": "Read the student's class fund balance and spending.",
        "class_fund_payment_info": "Read class fund payment instructions; does not initiate a payment.",
        "regular_payments_summary": "Read regular school payment summaries.",
        "lesson_tags": "List class-book lesson tags (teacher account required).",
        "marking_atoms": "List subjects and groups the teacher can grade (teacher account required).",
        "emergency_configuration": "Read emergency configuration (teacher account required).",
        "public_timetable_targets": "List published class, teacher and room timetable IDs. No login required.",
    }.items():
        add(name, description)
    add("actual_timetable", "Read the student's weekly timetable with changes; date defaults to this week.", date=DATE)
    add("class_timetable", "Read a whole class's timetable, including all its groups.",
        class_id=ID, date=DATE, permanent=BOOL)
    add("marks", "Read marks, averages, new/unconfirmed flags and prediction options by subject.", since=DATE)
    add("predict_marks", "Predict a subject average using hypothetical marks; does not save or change grades.",
        subject=string("Subject ID, abbreviation or name from marks."), hypothetical={
            "type": "array", "minItems": 1,
            "items": {"type": "array", "prefixItems": [string("Mark text, e.g. 1 or 2-."),
                       {"type": "integer", "minimum": 1}], "items": False, "minItems": 2, "maxItems": 2},
        })
    add("what_if", "Recompute marks from current and hypothetical mark entries; does not change grades.",
        marks={"type": "array", "minItems": 1, "items": object_schema({
            "Id": {"type": ["string", "null"]}, "MarkText": string(), "Weight": {"type": "integer"},
            "MaxPoints": {"type": "number"}, "SubjectId": ID,
        }, ["Id", "MarkText", "Weight", "MaxPoints", "SubjectId"])})
    add("subject_themes", "Read class-book themes for a subject.", subject_id=ID)
    add("homeworks", "Read homework assignments and attachment IDs in a date range.", since=DATE, until=DATE)
    add("events", "Read school events, optionally from a date and for a scope.",
        since=DATE, scope=string("Event scope.", "all", "my", "public"))
    add("substitutions", "Read two weeks of timetable substitutions from a date.", since=DATE)
    add("messages", "List Komens messages and attachment IDs. Does not mark messages as read.",
        folder=string("Folder.", "received", "sent", "noticeboard", "apology", "rating"), since=DATE)
    add("message", "Read a Komens message's body and details. Does not mark it as read.",
        message_id=ID, folder=string("Folder.", "received", "sent"))
    add("unread_messages_count", "Read the unread Komens message count.",
        folder=string("Folder.", "received", "noticeboard"))
    add("message_types", "List permitted message and recipient codes; use before sending or replying.", reply_to=ID)
    add("download_attachment", "Download an attachment as base64 (up to 512 KiB); never writes a local file.",
        attachment_id=ID)
    add("class_fund_payments", "Read class fund transactions grouped by month.",
        sort=string("Sort order.", "asc", "desc"), search={"type": "string", "minLength": 1})
    add("classbook", "Read class-book records for a date range (teacher account required).", since=DATE, until=DATE)
    for name, description in {
        "lesson_absence": "Read lesson attendance",
        "lesson_past": "Read the previous lesson theme and next record label",
        "lesson_students_timetable": "Read lesson students' timetables",
    }.items():
        add(name, description + " (teacher account required).", lesson_id=ID)
    add("marking_marks", "Read a grading sheet (teacher account required).", atom_id=ID)
    for name in ("public_timetable", "public_timetable_url"):
        add(name, "Read a published timetable" + (" URL" if name.endswith("url") else "") + ". No login required.",
            kind=string("Target type.", "class", "teacher", "room"), target_id=ID,
            week=string("Timetable week.", "actual", "next", "permanent"))
    add("school_municipalities", "List municipalities in the public school directory. No configuration required.",
        target="directory", method="municipalities")
    add("schools", "List schools in a municipality. No configuration required.",
        target="directory", method="schools", municipality=ID)
    add("find_schools", "Find schools by part of a municipality name. No configuration required.",
        target="directory", method="find", text={"type": "string", "minLength": 1},
        max_requests={"type": "integer", "minimum": 1, "maximum": 100})
    add("set_homework_done", "CHANGE DATA: mark homework finished or unfinished.",
        write=True, homework_id=ID, done=BOOL)
    add("confirm_marks", "CHANGE DATA: sign the specified marks as a parent.", write=True, mark_ids=IDS)
    for name, description in {
        "mark_message_read": "mark a received message as read",
        "confirm_message": "confirm receipt of a message",
        "hide_message": "hide a message",
        "unhide_message": "unhide a message",
        "delete_message": "delete a message",
    }.items():
        add(name, "CHANGE DATA: " + description + ".", write=True, message_id=ID)
    add("send_message", "CHANGE DATA: send a Komens message. Get exact recipient codes from message_types first.",
        write=True, idempotent=False, message_type=ID, text=string("Message body (HTML)."), recipient_type=ID,
        recipients=IDS, title=string(), previous_message_id=ID, attachments=IDS, require_confirmation=BOOL,
        email_notification=BOOL, copy_for_class_teacher=BOOL, copy_for_parent=BOOL, send_as_director=BOOL,
        lifetime=string(), date_from=DATE, date_to=DATE, type_of_rating_id={}, scale={})
    add("reply_to_message", "CHANGE DATA: reply to a received Komens message.", write=True, idempotent=False,
        message=ID, text=string("Reply body (HTML)."), title=string(), attachments=IDS, require_confirmation=BOOL)
    add("save_classbook_record", "CHANGE DATA: save a class-book request body (teacher account required).",
        write=True, record={"type": "object", "properties": {"Id": ID}, "required": ["Id"],
                            "description": "Bakaláři request body: Id, LessonId, Theme, Label, Groups, Tags, etc."})
    if allow_writes:
        tools["upload_attachment"] = Tool(
            "upload_attachment", "CHANGE DATA: upload base64 file content (up to 512 KiB); never reads local paths.",
            object_schema({"content_base64": string("RFC 4648 base64 file content."), "filename": ID,
                           "content_type": string("MIME type, e.g. application/pdf.")},
                          ["content_base64", "filename"]), write=True, idempotent=False,
        )
    return tools


def validate(value: Any, schema: Dict[str, Any], path: str = "arguments") -> None:
    """Validate the JSON Schema subset used by this fixed catalog, without echoing user values."""
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
        "boolean": isinstance(value, bool), "integer": type(value) is int,
        "number": type(value) in (int, float), "null": value is None, None: True,
    }
    if not any(matches[k] for k in kinds):
        raise ValueError(f"{path}: unexpected value type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: choose one of the advertised enum values")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise ValueError(f"{path}: missing required argument")
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError(f"{path}: unknown argument")
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"{path}: invalid number of items")
        prefix = schema.get("prefixItems", [])
        for index, item in enumerate(value):
            item_schema = prefix[index] if index < len(prefix) else schema.get("items", {})
            if item_schema is False:
                raise ValueError(f"{path}: too many items")
            validate(item, item_schema, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{path}: value must not be empty")
        if schema.get("format") == "date":
            try:
                if len(value) != 10 or dt.date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{path}: use a valid YYYY-MM-DD date") from None
    elif type(value) in (int, float):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError(f"{path}: value outside the allowed range")


def upload(client: BakalariClient, arguments: Dict[str, Any]) -> str:
    """Decode bytes explicitly: a model-supplied string can never become a filesystem path."""
    try:
        content = base64.b64decode(arguments["content_base64"], validate=True)
    except ValueError:
        raise ValueError("content_base64 must be valid base64") from None
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment exceeds the 512 KiB limit")
    return client.upload_attachment(content, filename=arguments["filename"], content_type=arguments.get("content_type"))
