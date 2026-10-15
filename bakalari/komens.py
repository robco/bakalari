"""Komens, the Bakaláři messaging module: message lists and details, unread counters, marking messages as read,
confirmed or hidden, deleting them, message types, sending and replying, and attachment downloads and uploads.

The lists are ``POST`` requests with an empty form body. Their objects carry a ``$type``: ``GeneralMessageReceived``
in the received list, ``SentMessageWithRecipients`` (with recipient and attachment counts) in the sent list and
``SentMessageWithRecipientsDetail`` (with the recipients and the persons involved) in the detail of a sent message.
``Text`` is HTML and reaches about 1 MB when images are embedded as base64 data; :attr:`Message.plain_text` turns it
into readable text. Message and attachment ids are opaque strings, used exactly as the server sends them.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import errno
import json
import mimetypes
import os
import re
import secrets
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, TypeVar, Union

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    compact,
    format_date,
    html_to_text,
    ident,
    mapping,
    objects,
    parse_datetime,
    quote_segment,
    require_int,
    require_mapping,
    shape_problems,
    text,
    to_bool,
    to_int,
)
from .errors import BakalariContractError, BakalariError
from .http import HttpResponse, parse_content_disposition
from .models import AttachmentInfo, Model

__all__ = [
    "DETAIL_FOLDERS",
    "MESSAGE_FOLDERS",
    "UNREAD_FOLDERS",
    "AttachmentFile",
    "KomensEndpoints",
    "Message",
    "MessagePerson",
    "MessageRecipient",
    "MessageType",
    "MessageTypes",
    "Recipient",
    "RecipientType",
    "Sender",
    "UploadSource",
    "parse_message",
    "parse_messages",
]

MESSAGE_FOLDERS = ("received", "sent", "noticeboard", "apology", "rating")
DETAIL_FOLDERS = ("received", "sent")
UNREAD_FOLDERS = ("received", "noticeboard")

UploadSource = Union[str, "os.PathLike[str]", bytes, bytearray, IO[bytes]]

_T = TypeVar("_T")
# Base64 images embedded in a message body; removing them first keeps the HTML small for the text conversion. The
# media type is optional (RFC 2397).
_DATA_URI = re.compile(
    r"data:(?:[\w.+-]+/[\w.+-]+)?(?:;[\w.+-]+=[^;,\"'\s]*)*;base64,[A-Za-z0-9+/=\r\n]*", re.IGNORECASE
)
# Control characters other than white space (which the text conversion turns into spaces and line breaks): a body may
# carry raw terminal escape sequences, backspaces or bells, which must not reach a terminal that prints plain_text.
# Character references to them decode to nothing.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")
_REPR_TEXT_LIMIT = 60
_GENERIC_CONTENT_TYPES = ("", "application/octet-stream")
_UNSAFE_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
# Control characters (C0 and C1), format characters (bidirectional overrides that disguise an extension, zero-width
# characters), lone surrogates and line or paragraph separators.
_UNSAFE_FILENAME_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))
_WINDOWS_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "0123456789\u00b9\u00b2\u00b3"]
)
_SURROGATES = re.compile(r"[\ud800-\udfff]")
_MAX_FILENAME_BYTES = 255
_PATH_SEPARATORS = tuple(separator for separator in (os.sep, os.altsep) if separator)


@dataclass(frozen=True)
class Sender(Model):
    """The sender of a message: ``type`` is the account type (``teacher``, ``administrator``, ``parents``,
    ``student``) and ``name`` the name as the web shows it."""

    id: str = ""
    type: str = ""
    name: str = ""

    def __str__(self) -> str:
        return self.name or self.id

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Sender:
        """Parses a ``Sender`` object."""
        return cls(id=ident(data.get("Id")), type=text(data.get("Type")), name=text(data.get("Name")))


@dataclass(frozen=True)
class MessageRecipient(Model):
    """A recipient in the detail of a sent message: ``id`` is the ``RecipientId`` (look the person up with
    :meth:`Message.person`) and ``user_type`` the account type. Entries of ``recipients_processed`` also carry
    ``action_date`` and the recipient's ``parent_persons`` (``ParentPersons``)."""

    id: str
    user_type: str = ""
    action_date: Optional[dt.datetime] = None
    parent_persons: Tuple[MessageRecipient, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MessageRecipient:
        """Parses an entry of ``Recipients``, ``RecipientsProcessed`` or ``ParentPersons``."""
        recipient_id = data.get("RecipientId")
        return cls(
            id=ident(data.get("Id") if recipient_id is None else recipient_id),
            user_type=text(data.get("UserType")),
            action_date=parse_datetime(data.get("ActionDate")),
            parent_persons=_recipients(data.get("ParentPersons")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class MessagePerson(Model):
    """A person involved in a sent message (its sender and recipients), from the message detail: ``id`` is the
    account id that ``Recipients`` and the sender refer to, ``person_id`` the id of the person record."""

    id: str
    user_type: str = ""
    person_id: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    degree: str = ""
    degree_behind: str = ""
    class_abbreviation: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __str__(self) -> str:
        return self.full_name or self.id

    @property
    def full_name(self) -> str:
        """The name with the degrees as Czech writes it (``Ing. Jan Novák, Ph.D.``); empty when the server sends
        no name parts."""
        name = " ".join(part for part in (self.degree, self.first_name, self.middle_name, self.last_name) if part)
        if self.degree_behind:
            return f"{name}, {self.degree_behind}" if name else self.degree_behind
        return name

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MessagePerson:
        """Parses an entry of ``Persons``; ``null`` name parts become empty strings."""
        return cls(
            id=ident(data.get("Id")),
            user_type=text(data.get("UserType")),
            person_id=ident(data.get("PersonId")),
            first_name=text(data.get("FirstName")),
            middle_name=text(data.get("MiddleName")),
            last_name=text(data.get("LastName")),
            degree=text(data.get("Degree")),
            degree_behind=text(data.get("DegreeBehind")),
            class_abbreviation=text(data.get("ClassAbbreviation")),
            raw=dict(data),
        )


@dataclass(frozen=True, repr=False)
class Message(Model):
    """A Komens message from a list or a detail request.

    ``kind`` is the server's ``$type`` (``GeneralMessageReceived``, ``SentMessageWithRecipients``,
    ``SentMessageWithRecipientsDetail``, ...), ``message_type`` the Komens type (``OBECNA`` for a general message,
    ``OMLUVENKA`` for an absence excuse, ...), ``text`` the HTML body (see :attr:`plain_text`) and ``sent`` the
    ``SentDate``. ``life_time`` is ``ToRead`` or ``ToConfirm``; ``date_from``/``date_to`` are set for messages
    about a period (an excused absence). ``relevant_name`` and ``relevant_person_type`` describe the other party
    as the web lists it: the sender of a received message, the recipient of a sent one.

    The sent list adds ``recipients_count``, ``recipients_processed_count`` and ``attachments_count`` (``None``
    elsewhere); the detail of a sent message adds ``recipients``, ``recipients_processed`` and ``persons``. The
    ``repr()`` shortens a long ``text``; ``to_dict()`` keeps it whole.
    """

    id: str
    kind: str = ""
    title: str = ""
    text: str = ""
    sent: Optional[dt.datetime] = None
    sender: Sender = field(default_factory=Sender)
    attachments: Tuple[AttachmentInfo, ...] = ()
    read: bool = False
    confirmed: bool = False
    can_confirm: bool = False
    can_answer: bool = False
    can_hide: bool = False
    can_delete: bool = False
    hidden: bool = False
    life_time: str = ""
    date_from: Optional[dt.datetime] = None
    date_to: Optional[dt.datetime] = None
    message_type: str = ""
    relevant_name: str = ""
    relevant_person_type: str = ""
    recipients_count: Optional[int] = None
    recipients_processed_count: Optional[int] = None
    attachments_count: Optional[int] = None
    recipients: Tuple[MessageRecipient, ...] = ()
    recipients_processed: Tuple[MessageRecipient, ...] = ()
    persons: Tuple[MessagePerson, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __repr__(self) -> str:
        shown = []
        for item in dataclasses.fields(self):
            if not item.repr:
                continue
            value = getattr(self, item.name)
            if item.name == "text" and isinstance(value, str) and len(value) > _REPR_TEXT_LIMIT:
                shown.append(f"text={value[:_REPR_TEXT_LIMIT]!r}... ({len(value)} characters)")
            else:
                shown.append(f"{item.name}={value!r}")
        return f"{type(self).__name__}({', '.join(shown)})"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Message:
        """Parses one message object of a list or a detail response; missing fields get their defaults."""
        return cls(
            id=ident(data.get("Id")),
            kind=text(data.get("$type")),
            title=text(data.get("Title")),
            text=text(data.get("Text")),
            sent=parse_datetime(data.get("SentDate")),
            sender=Sender.from_json(mapping(data.get("Sender"))),
            attachments=tuple(AttachmentInfo.from_json(item) for item in objects(data.get("Attachments"))),
            read=to_bool(data.get("Read")),
            confirmed=to_bool(data.get("Confirmed")),
            can_confirm=to_bool(data.get("CanConfirm")),
            can_answer=to_bool(data.get("CanAnswer")),
            can_hide=to_bool(data.get("CanHide")),
            can_delete=to_bool(data.get("CanDelete")),
            hidden=to_bool(data.get("Hidden")),
            life_time=text(data.get("LifeTime")),
            date_from=parse_datetime(data.get("DateFrom")),
            date_to=parse_datetime(data.get("DateTo")),
            message_type=text(data.get("Type")),
            relevant_name=text(data.get("RelevantName")),
            relevant_person_type=text(data.get("RelevantPersonType")),
            recipients_count=to_int(data.get("RecipientsCount")),
            recipients_processed_count=to_int(data.get("RecipientsProcessedCount")),
            attachments_count=to_int(data.get("AttachmentsCount")),
            recipients=_recipients(data.get("Recipients")),
            recipients_processed=_recipients(data.get("RecipientsProcessed")),
            persons=tuple(MessagePerson.from_json(item) for item in objects(data.get("Persons"))),
            raw=dict(data),
        )

    @property
    def plain_text(self) -> str:
        """The HTML body as readable plain text: paragraphs and ``<br>`` become line breaks, list items start
        with ``- ``, link targets follow their text. Embedded base64 images are dropped before the conversion, so
        that a body of about 1 MB converts in milliseconds; control characters (raw terminal escape sequences) are
        dropped too, so the text is safe to print."""
        if not self.text:
            return ""
        return html_to_text(_CONTROL_CHARACTERS.sub("", _DATA_URI.sub("", self.text)))

    @property
    def needs_confirmation(self) -> bool:
        """True while the message asks for a confirmation that has not been given (see
        :meth:`KomensEndpoints.confirm_message`)."""
        return self.can_confirm and not self.confirmed

    def person(self, person_id: str) -> Optional[MessagePerson]:
        """The entry of ``persons`` (message detail only) whose ``id`` or ``person_id`` is ``person_id``, e.g. a
        recipient's id or the sender's id; ``None`` when it is not listed."""
        if not person_id:
            return None
        return next((person for person in self.persons if person_id in (person.id, person.person_id)), None)


@dataclass(frozen=True)
class Recipient(Model):
    """A possible recipient of a new message: ``code`` goes into the ``recipients`` of
    :meth:`KomensEndpoints.send_message`. ``is_default`` marks the preselected recipient (e.g. the class teacher
    for an absence excuse); the school-wide ``MessageTypes.recipients`` list does not set it."""

    code: str
    name: str = ""
    display_name: str = ""
    abbreviation: str = ""
    is_default: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __str__(self) -> str:
        return self.display_name or self.name or self.code

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Recipient:
        """Parses an entry of ``Recipients``."""
        return cls(
            code=ident(data.get("Code")),
            name=text(data.get("Name")),
            display_name=text(data.get("DisplayName")),
            abbreviation=text(data.get("Abbreviation")),
            is_default=to_bool(data.get("IsDefault")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class RecipientType(Model):
    """A kind of recipient a message type can be sent to (``code`` ``U`` for one teacher, ``UV`` for all teachers,
    ...). ``selection`` (``TypeOfSelection``) is ``ONE`` (pick one of ``recipients``), ``MULTI`` (pick several) or
    ``ZERO`` (no choice: the recipients are implied). The ``show_copy_for_*`` flags say which copy options the
    official app offers."""

    code: str
    name: str = ""
    selection: str = ""
    show_copy_for_class_teacher: bool = False
    show_copy_for_director: bool = False
    show_copy_for_parent: bool = False
    show_copy_for_student: bool = False
    recipients: Tuple[Recipient, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __str__(self) -> str:
        return self.name or self.code

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RecipientType:
        """Parses an entry of ``RecipientsTypes``."""
        return cls(
            code=ident(data.get("Code")),
            name=text(data.get("Name")),
            selection=text(data.get("TypeOfSelection")),
            show_copy_for_class_teacher=to_bool(data.get("ShowCopyForClassTeacher")),
            show_copy_for_director=to_bool(data.get("ShowCopyForDirector")),
            show_copy_for_parent=to_bool(data.get("ShowCopyForParent")),
            show_copy_for_student=to_bool(data.get("ShowCopyForStudent")),
            recipients=tuple(Recipient.from_json(item) for item in objects(data.get("Recipients"))),
            raw=dict(data),
        )

    @property
    def needs_recipients(self) -> bool:
        """False for the selection ``ZERO``, whose recipients are implied and must not be listed."""
        return self.selection.upper() != "ZERO"

    @property
    def default_recipients(self) -> Tuple[Recipient, ...]:
        """The preselected recipients (``IsDefault``)."""
        return tuple(recipient for recipient in self.recipients if recipient.is_default)

    def recipient(self, key: str) -> Optional[Recipient]:
        """The recipient with the code ``key`` or, compared case-insensitively, that code, name, display name or
        abbreviation; ``None`` when there is none."""
        return _find(
            self.recipients, key, lambda item: (item.code, item.name, item.display_name, item.abbreviation)
        )


@dataclass(frozen=True)
class MessageType(Model):
    """A message type the account may send: ``code`` (``Abbreviation``: ``OBECNA``, ``OMLUVENKA``, ...) goes into
    ``message_type`` of :meth:`KomensEndpoints.send_message`. ``has_title`` says whether the message has a title,
    ``show_confirmation`` and ``show_email_notification`` whether a read confirmation and an e-mail notification
    can be requested."""

    code: str
    name: str = ""
    has_title: bool = False
    show_email_notification: bool = False
    show_confirmation: bool = False
    super_type: str = ""
    recipient_types: Tuple[RecipientType, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __str__(self) -> str:
        return self.name or self.code

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MessageType:
        """Parses an entry of ``MessageTypes``."""
        return cls(
            code=ident(data.get("Abbreviation")),
            name=text(data.get("Name")),
            has_title=to_bool(data.get("HasTitle")),
            show_email_notification=to_bool(data.get("ShowEmailNotification")),
            show_confirmation=to_bool(data.get("ShowConfirmation")),
            super_type=text(data.get("SuperType")),
            recipient_types=tuple(RecipientType.from_json(item) for item in objects(data.get("RecipientsTypes"))),
            raw=dict(data),
        )

    def recipient_type(self, key: str) -> Optional[RecipientType]:
        """The recipient type with the code ``key`` or, compared case-insensitively, that code or name."""
        return _find(self.recipient_types, key, lambda item: (item.code, item.name))


@dataclass(frozen=True)
class MessageTypes(Model):
    """What the account may send (``GET /api/3/komens/message-types``): the message ``types`` with their
    recipient types and recipients, and ``recipients``, every recipient of the school."""

    types: Tuple[MessageType, ...] = ()
    recipients: Tuple[Recipient, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> MessageTypes:
        """Parses a ``message-types`` payload. With ``validate`` (default) a missing ``MessageTypes`` list, a type
        without ``Abbreviation``, a recipient type without ``Code`` or a malformed nested list raises
        :class:`~bakalari.BakalariContractError`; without it only a non-object payload does."""
        what = "Komens message types"
        if validate:
            problems = _message_types_problems(data)
            if problems:
                raise BakalariContractError(problems, what)
        payload = require_mapping(data, what)
        return cls(
            types=tuple(MessageType.from_json(item) for item in objects(payload.get("MessageTypes"))),
            recipients=tuple(Recipient.from_json(item) for item in objects(payload.get("Recipients"))),
            raw=dict(payload),
        )

    def message_type(self, key: str) -> Optional[MessageType]:
        """The message type with the code ``key`` (e.g. ``OBECNA``) or, compared case-insensitively, that code or
        name; ``None`` when the account may not send it."""
        return _find(self.types, key, lambda item: (item.code, item.name))

    def recipient(self, key: str) -> Optional[Recipient]:
        """The school-wide recipient with the code ``key`` or, compared case-insensitively, that code, name,
        display name or abbreviation."""
        return _find(
            self.recipients, key, lambda item: (item.code, item.name, item.display_name, item.abbreviation)
        )


@dataclass(frozen=True)
class AttachmentFile(Model):
    """A downloaded attachment: ``filename`` as the server names it, ``content_type`` and the ``content`` bytes
    (left out of ``repr()``; ``to_dict()`` shows the ``size`` instead)."""

    filename: str
    content_type: str = ""
    content: bytes = field(default=b"", repr=False)
    id: str = ""

    @property
    def size(self) -> int:
        """The size of the content in bytes."""
        return len(self.content)

    @property
    def safe_filename(self) -> str:
        """``filename`` made safe to create in a directory: without directory parts, control and format characters
        (such as the bidirectional overrides that disguise an extension), characters Windows forbids, leading and
        trailing dots and white space (so never a hidden file) and Windows device names, at most 255 bytes long;
        ``attachment-<id>`` when nothing is left."""
        return _safe_filename(self.filename, f"attachment-{self.id}" if self.id else "attachment")

    def save(self, target: Union[str, os.PathLike[str]], overwrite: bool = False) -> Path:
        """Writes the content to ``target`` and returns the path written. An existing directory (or a path that
        ends with a separator) receives the file under :attr:`safe_filename`. An existing file is never replaced
        unless ``overwrite`` is true; otherwise :class:`FileExistsError` is raised and nothing is written. A new
        file whose writing fails is removed again."""
        location = os.fspath(target)
        path = Path(location)
        if location.endswith(_PATH_SEPARATORS) or path.is_dir():
            path = path / self.safe_filename
        try:
            file = open(path, "wb" if overwrite else "xb")
        except FileExistsError:
            raise FileExistsError(errno.EEXIST, "File exists; pass overwrite=True to replace it", str(path)) from None
        try:
            with file:
                file.write(self.content)
        except BaseException:
            if not overwrite:  # the file did not exist before, so a partial one must not block the next attempt
                with contextlib.suppress(OSError):
                    path.unlink()
            raise
        return path

    def to_dict(self) -> Dict[str, Any]:
        """``filename``, ``content_type``, ``id`` and ``size``; the content itself is left out."""
        return {**super().to_dict(), "size": self.size}


def parse_messages(data: Any, *, validate: bool = True) -> List[Message]:
    """Parses the payload of a message list (``{"Messages": [...]}``). With ``validate`` (default) a missing
    ``Messages`` list, an entry that is not an object or has no ``Id``, or a malformed ``Sender``, ``Attachments``,
    ``Recipients``, ``RecipientsProcessed`` or ``Persons`` raises :class:`~bakalari.BakalariContractError`;
    without it only a non-object payload does."""
    what = "Komens message list"
    if validate:
        problems = shape_problems(data, what, lists=("Messages",))
        entries = data.get("Messages") if isinstance(data, Mapping) else None
        for index, entry in enumerate(entries if isinstance(entries, list) else [], 1):
            if isinstance(entry, Mapping):
                message_id = ident(entry.get("Id"))
                problems += _message_problems(entry, f"Message {message_id!r}" if message_id else f"Message #{index}")
        if problems:
            raise BakalariContractError(problems, what)
    payload = require_mapping(data, what)
    return [Message.from_json(entry) for entry in objects(payload.get("Messages"))]


def parse_message(data: Any, *, validate: bool = True) -> Message:
    """Parses the payload of a message detail (``{"Message": {...}}``). With ``validate`` (default) a message
    without ``Id`` or with malformed nested data raises :class:`~bakalari.BakalariContractError`; a missing
    ``Message`` object always does."""
    what = "Komens message"
    if validate:
        problems = shape_problems(data, what, objects_=("Message",))
        if not problems:
            problems = _message_problems(data["Message"], "The message")
        if problems:
            raise BakalariContractError(problems, what)
    message = require_mapping(data, what).get("Message")
    if not isinstance(message, Mapping):
        raise BakalariContractError(["Missing object 'Message'"], what)
    return Message.from_json(message)


class KomensEndpoints(ClientCore):
    """Komens endpoints of :class:`~bakalari.BakalariClient` (module ``Komens``; sending needs the right
    ``SendMessages``, uploading attachments ``SendAttachments``)."""

    def messages(
        self, folder: str = "received", *, since: Optional[DateLike] = None, validate: bool = True
    ) -> List[Message]:
        """``POST /api/3/komens/messages/{folder}`` (form-encoded): the messages of the folder ``received``,
        ``sent``, ``noticeboard``, or ``apology`` and ``rating``, which need extra rights (HTTP 403,
        :class:`~bakalari.BakalariPermissionError`, otherwise). ``since`` sends the form field ``dateFrom`` so that
        only the messages from that date on come back; without it the form is empty and the server returns the
        whole folder."""
        folder = _folder(folder, MESSAGE_FOLDERS)
        form = compact({"dateFrom": format_date(since)})
        data = self.post_json(api_path("komens", "messages", folder), form=form)
        return parse_messages(data, validate=validate)

    def message(
        self, message_id: Union[str, Message], folder: str = "received", *, validate: bool = True
    ) -> Message:
        """``GET /api/3/komens/messages/{received|sent}/{id}``: one message (``message_id`` is the id or a
        :class:`Message`); the detail of a sent message adds the recipients and the persons involved. Reading the
        detail does not mark the message as read: call :meth:`mark_message_read` for that."""
        folder = _folder(folder, DETAIL_FOLDERS)
        data = self.get_json(api_path("komens", "messages", folder, quote_segment(_message_id(message_id))))
        return parse_message(data, validate=validate)

    def unread_messages_count(self, folder: str = "received") -> int:
        """``GET /api/3/komens/messages/{received|noticeboard}/unread``: the number of unread messages."""
        folder = _folder(folder, UNREAD_FOLDERS)
        data = self.get_json(api_path("komens", "messages", folder, "unread"))
        return require_int(data, "Komens unread message count")

    def mark_message_read(self, message_id: Union[str, Message]) -> None:
        """``PUT /api/3/komens/message/{id}/mark-as-read`` (no body; the server answers HTTP 204): marks a
        received message as read."""
        self._komens_put(message_id, "mark-as-read")

    def confirm_message(self, message_id: Union[str, Message]) -> None:
        """``PUT /api/3/komens/message/{id}/mark-as-confirmed`` (no body): confirms that a message was read;
        allowed when its :attr:`Message.can_confirm` is true (``life_time`` ``ToConfirm``)."""
        self._komens_put(message_id, "mark-as-confirmed")

    def hide_message(self, message_id: Union[str, Message]) -> None:
        """``PUT /api/3/komens/message/{id}/mark-as-hidden`` (no body): hides a message; allowed when its
        :attr:`Message.can_hide` is true."""
        self._komens_put(message_id, "mark-as-hidden")

    def unhide_message(self, message_id: Union[str, Message]) -> None:
        """``PUT /api/3/komens/message/{id}/mark-as-unhidden`` (no body): shows a hidden message
        (:attr:`Message.hidden`) again."""
        self._komens_put(message_id, "mark-as-unhidden")

    def delete_message(self, message_id: Union[str, Message]) -> None:
        """``DELETE /api/3/komens/message/{id}``: deletes a message; allowed when its :attr:`Message.can_delete`
        is true."""
        path = api_path("komens", "message", quote_segment(_message_id(message_id)))
        self.request("DELETE", path, expected_status=(200, 204))

    def message_types(
        self, *, reply_to: Optional[Union[str, Message]] = None, validate: bool = True
    ) -> MessageTypes:
        """``GET /api/3/komens/message-types``: the message types the account may send with their recipient types
        and recipients. With ``reply_to`` (a message or its id), ``GET /api/3/komens/message-types/reply/{id}``:
        the same shape limited to what a reply to that message allows (typically one recipient type with the
        selection ``ZERO``: the recipient follows from the original message)."""
        if reply_to is None:
            path = api_path("komens", "message-types")
        else:
            path = api_path("komens", "message-types", "reply", quote_segment(_message_id(reply_to)))
        return MessageTypes.from_json(self.get_json(path), validate=validate)

    def send_message(
        self,
        *,
        message_type: Union[str, MessageType],
        text: str,
        recipient_type: Union[str, RecipientType],
        recipients: Union[str, Recipient, Iterable[Union[str, Recipient]]] = (),
        title: str = "",
        previous_message_id: Optional[Union[str, Message]] = None,
        attachments: Union[str, Iterable[str]] = (),
        require_confirmation: bool = False,
        email_notification: bool = False,
        copy_for_class_teacher: bool = False,
        copy_for_parent: bool = False,
        send_as_director: bool = False,
        lifetime: Optional[str] = None,
        date_from: Optional[DateLike] = None,
        date_to: Optional[DateLike] = None,
        type_of_rating_id: Any = None,
        scale: Any = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """``POST /api/3/komens/message``: sends a message (right ``SendMessages``).

        The codes come from :meth:`message_types` (codes or the :class:`MessageType`, :class:`RecipientType` and
        :class:`Recipient` objects are accepted): ``message_type`` (e.g. ``OBECNA``), ``recipient_type`` and the
        ``recipients`` codes (none for the selection ``ZERO``). ``text`` is the body, HTML like the web editor
        writes it; ``attachments`` are ids from :meth:`upload_attachment`; ``previous_message_id`` makes the
        message a reply (see :meth:`reply_to_message`). ``date_from``/``date_to`` are sent as ISO strings (a date as
        ``YYYY-MM-DD``; pass a datetime for an exact time). ``extra`` adds or overrides body keys this method does
        not map. An empty code or attachment id raises :class:`ValueError` before any request; any status but
        HTTP 200 raises :class:`~bakalari.BakalariHTTPError`.
        """
        body: Dict[str, Any] = {
            "MessageType": _code(message_type, "message type"),
            "Title": title,
            "Text": text,
            "RecipientType": _code(recipient_type, "recipient type"),
            "Recipients": _recipient_codes(recipients),
            "Lifetime": lifetime,
            "DateFrom": _json_date(date_from),
            "DateTo": _json_date(date_to),
            "PreviousMessageId": None if previous_message_id is None else _message_id(previous_message_id),
            "CopyForClassTeacher": copy_for_class_teacher,
            "CopyForParent": copy_for_parent,
            "EmailNotification": email_notification,
            "SendAsDirector": send_as_director,
            "RequireConfirmation": require_confirmation,
            "TypeOfRatingId": type_of_rating_id,
            "Scale": scale,
            "Attachments": _attachment_ids(attachments),
            "DraftDate": None,
        }
        body.update(extra or {})
        self.request("POST", api_path("komens", "message"), json_body=body, expected_status=200)

    def reply_to_message(
        self,
        message: Union[Message, str],
        text: str,
        *,
        title: Optional[str] = None,
        attachments: Union[str, Iterable[str]] = (),
        require_confirmation: bool = False,
    ) -> None:
        """``GET /api/3/komens/message-types/reply/{id}``, then ``POST /api/3/komens/message``: replies to a
        received message (a :class:`Message`, or its id, in which case the detail is fetched first).

        The reply uses the first message type and the first recipient type the server allows for it (the selection
        ``ZERO`` sends no recipients, any other the original sender's id) and refers to the original through
        ``PreviousMessageId``. ``title`` defaults to ``"Re: "`` plus the original title when the reply type has a
        title. Raises :class:`~bakalari.BakalariError` when the server offers no way to reply.
        """
        original = message if isinstance(message, Message) else self.message(message)
        options = self.message_types(reply_to=original)
        if not options.types or not options.types[0].recipient_types:
            raise BakalariError(f"The Bakaláři server offers no way to reply to Komens message {original.id!r}.")
        reply_type = options.types[0]
        recipient_type = reply_type.recipient_types[0]
        recipients = [original.sender.id] if recipient_type.needs_recipients and original.sender.id else []
        if title is None:
            title = _reply_title(original.title) if reply_type.has_title else ""
        self.send_message(
            message_type=reply_type.code,
            text=text,
            recipient_type=recipient_type.code,
            recipients=recipients,
            title=title,
            previous_message_id=original.id,
            attachments=attachments,
            require_confirmation=require_confirmation,
        )

    def download_attachment(self, attachment_id: Union[str, AttachmentInfo]) -> AttachmentFile:
        """``GET /api/3/komens/attachment/{id}``: downloads a file attached to a message or to a homework
        (``attachment_id`` is the id or the :class:`~bakalari.AttachmentInfo`). The file name comes from
        ``Content-Disposition``, else from the attachment info, else it is ``attachment-<id>``; a generic
        ``application/octet-stream`` type is replaced by the type of the attachment info or the one the file name
        suggests. The server lets users download attachments of their own messages only; an unknown id answers
        HTTP 500 (:class:`~bakalari.BakalariHTTPError`)."""
        info = attachment_id if isinstance(attachment_id, AttachmentInfo) else None
        identifier = info.id if info else ident(attachment_id)
        if not identifier:
            raise ValueError("An attachment id is required")
        response = self.request(
            "GET", api_path("komens", "attachment", quote_segment(identifier)), headers={"Accept": "*/*"}
        )
        filename = parse_content_disposition(response.header("Content-Disposition")) or (
            info.name if info and info.name else f"attachment-{_replace_unsafe(identifier)}"
        )
        content_type = response.content_type
        if content_type in _GENERIC_CONTENT_TYPES:
            content_type = (info.content_type if info else "") or mimetypes.guess_type(filename)[0] or content_type
        return AttachmentFile(filename=filename, content_type=content_type, content=response.body, id=identifier)

    def upload_attachment(
        self, source: UploadSource, *, filename: Optional[str] = None, content_type: Optional[str] = None
    ) -> str:
        """``POST /api/3/komens/attachment``: uploads a file as ``multipart/form-data`` and returns its id for
        the ``attachments`` of :meth:`send_message` (right ``SendAttachments``). ``source`` is a path, a binary
        file object or the content as bytes (then ``filename`` is required); ``content_type`` defaults to the type
        the file name suggests."""
        content, name = _read_upload(source, filename)
        media_type = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        if "\r" in media_type or "\n" in media_type:
            raise ValueError("The content type must not contain line breaks")
        body, multipart_type = _multipart_body(name, media_type, content)
        path = api_path("komens", "attachment")
        response = self.request(
            "POST",
            path,
            data=body,
            headers={"Content-Type": multipart_type, "Accept": "text/plain, application/json"},
            expected_status=(200, 201),
        )
        return _uploaded_attachment_id(path, response)

    def rating_templates(self) -> Any:
        """``GET /api/3/komens/rating-templates``: the Komens rating templates as raw JSON (teacher accounts;
        others get HTTP 403, :class:`~bakalari.BakalariPermissionError`)."""
        return self.get_json(api_path("komens", "rating-templates"))

    def _komens_put(self, message_id: Union[str, Message], action: str) -> None:
        path = api_path("komens", "message", quote_segment(_message_id(message_id)), action)
        self.request("PUT", path, expected_status=(200, 204))


def _recipients(value: Any) -> Tuple[MessageRecipient, ...]:
    """Recipient entries; plain ids (the element shape of ``ParentPersons`` is not documented) become recipients
    with only an ``id``."""
    if not isinstance(value, list):
        return ()
    return tuple(
        MessageRecipient.from_json(entry) if isinstance(entry, Mapping) else MessageRecipient(id=ident(entry))
        for entry in value
        if entry is not None
    )


def _find(items: Iterable[_T], key: str, names: Callable[[_T], Tuple[str, ...]]) -> Optional[_T]:
    """The item whose first name (its code) equals ``key``, else the first whose names contain ``key`` compared
    case-insensitively."""
    if not key or not key.strip():
        return None
    candidates = tuple(items)
    exact = next((item for item in candidates if names(item)[0] == key), None)
    if exact is not None:
        return exact
    wanted = key.strip().casefold()
    return next((item for item in candidates if any(name.strip().casefold() == wanted for name in names(item))), None)


def _list_problems(container: Mapping[str, Any], name: str, label: str) -> List[str]:
    value = container.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{label}: '{name}' is not a list"]
    bad = sum(1 for entry in value if not isinstance(entry, Mapping))
    if not bad:
        return []
    if bad == 1:
        return [f"{label}: 1 entry of '{name}' is not a JSON object"]
    return [f"{label}: {bad} entries of '{name}' are not JSON objects"]


def _message_problems(message: Mapping[str, Any], label: str) -> List[str]:
    problems = [] if ident(message.get("Id")) else [f"{label} has no Id"]
    sender = message.get("Sender")
    if sender is not None and not isinstance(sender, Mapping):
        problems.append(f"{label}: 'Sender' is not a JSON object")
    for name in ("Attachments", "Recipients", "RecipientsProcessed", "Persons"):
        problems += _list_problems(message, name, label)
    return problems


def _message_types_problems(data: Any) -> List[str]:
    problems = shape_problems(data, "Komens message types", lists=("MessageTypes",))
    if not isinstance(data, Mapping):
        return problems
    entries = data.get("MessageTypes")
    for index, entry in enumerate(entries if isinstance(entries, list) else [], 1):
        if not isinstance(entry, Mapping):
            continue
        code = ident(entry.get("Abbreviation"))
        label = f"Message type {code!r}" if code else f"Message type #{index}"
        if not code:
            problems.append(f"{label} has no Abbreviation")
        problems += _list_problems(entry, "RecipientsTypes", label)
        for recipient_type in objects(entry.get("RecipientsTypes")):
            type_code = ident(recipient_type.get("Code"))
            if not type_code:
                problems.append(f"{label}: a recipient type has no Code")
            problems += _list_problems(recipient_type, "Recipients", f"{label}, recipient type {type_code!r}")
    return problems + _list_problems(data, "Recipients", "The message types")


def _folder(folder: str, allowed: Tuple[str, ...]) -> str:
    name = str(folder).strip().lower()
    if name not in allowed:
        raise ValueError(f"Unknown Komens folder {folder!r}: use {', '.join(allowed)}")
    return name


def _message_id(value: Union[str, Message]) -> str:
    message_id = value.id if isinstance(value, Message) else ident(value)
    if not message_id:
        raise ValueError("A Komens message id is required")
    return message_id


def _code(value: Union[str, MessageType, RecipientType, Recipient], what: str) -> str:
    code = value.code if isinstance(value, (MessageType, RecipientType, Recipient)) else ident(value)
    if not code.strip():
        raise ValueError(f"A {what} code is required")
    return code


def _recipient_codes(recipients: Union[str, Recipient, Iterable[Union[str, Recipient]]]) -> List[str]:
    if isinstance(recipients, (str, Recipient)):
        return [_code(recipients, "recipient")]
    return [_code(recipient, "recipient") for recipient in recipients]


def _attachment_ids(attachments: Union[str, Iterable[str]]) -> List[str]:
    ids = [ident(item) for item in ([attachments] if isinstance(attachments, str) else attachments)]
    if not all(attachment_id.strip() for attachment_id in ids):
        raise ValueError("An attachment id is required: pass the ids that upload_attachment() returns")
    return ids


def _json_date(value: Optional[DateLike]) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.date):  # also a datetime, which keeps its time and offset
        return value.isoformat()
    return str(value)


def _reply_title(title: str) -> str:
    return title if title[:3].lower() == "re:" else f"Re: {title}"


def _safe_filename(name: str, default: str) -> str:
    cleaned = _clean_filename(name) or _replace_unsafe(default) or "attachment"
    if cleaned.split(".", 1)[0].strip().upper() in _WINDOWS_DEVICE_NAMES:
        cleaned = "_" + cleaned
    if len(cleaned.encode("utf-8")) <= _MAX_FILENAME_BYTES:
        return cleaned
    stem, dot, suffix = cleaned.rpartition(".")
    if not dot or not stem or len(suffix) > 16:
        stem, suffix = cleaned, ""
    else:
        suffix = "." + suffix
    budget = _MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    # The stem starts with a character that is neither a dot nor white space, so the shortened stem is never empty
    # and the result never becomes a hidden file such as ".bashrc".
    return _trim_dots_and_spaces(stem.encode("utf-8")[:budget].decode("utf-8", "ignore")) + suffix


def _clean_filename(name: str) -> str:
    """The last path segment of ``name`` with unsafe characters replaced."""
    return _replace_unsafe(name.replace("\\", "/").rsplit("/", 1)[-1])


def _replace_unsafe(name: str) -> str:
    """``name`` with the characters that are unsafe in a file name replaced by ``_`` and without leading or trailing
    dots and white space."""
    replaced = "".join(
        "_" if char in _UNSAFE_FILENAME_CHARACTERS or unicodedata.category(char) in _UNSAFE_FILENAME_CATEGORIES
        else char
        for char in name
    )
    return _trim_dots_and_spaces(replaced)


def _trim_dots_and_spaces(name: str) -> str:
    start, end = 0, len(name)
    while start < end and (name[start] == "." or name[start].isspace()):
        start += 1
    while end > start and (name[end - 1] == "." or name[end - 1].isspace()):
        end -= 1
    return name[start:end]


def _read_upload(source: UploadSource, filename: Optional[str]) -> Tuple[bytes, str]:
    if isinstance(source, (bytes, bytearray)):
        if not filename:
            raise ValueError("Pass filename= when uploading bytes")
        return bytes(source), filename
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        return path.read_bytes(), filename or path.name
    read = getattr(source, "read", None)
    if not callable(read):
        raise TypeError(f"Cannot upload a {type(source).__name__}: pass a path, bytes or a binary file object")
    content: Any = read()
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("The file object must be opened in binary mode ('rb')")
    source_name = getattr(source, "name", None)
    name = filename or (os.path.basename(source_name) if isinstance(source_name, str) else "")
    if not name:
        raise ValueError("Pass filename= for a file object without a name")
    return bytes(content), name


def _multipart_body(filename: str, content_type: str, content: bytes) -> Tuple[bytes, str]:
    """A ``multipart/form-data`` body with one file part named ``attachment``. The file name goes into
    ``filename`` as UTF-8, as browsers and the official app send it, plus an RFC 5987 ``filename*`` when it is not
    ASCII. Undecodable bytes of a POSIX file name (surrogate escapes) become U+FFFD."""
    boundary = "bakalari-" + secrets.token_hex(16)
    while boundary.encode("ascii") in content:
        boundary = "bakalari-" + secrets.token_hex(16)
    filename = _SURROGATES.sub("\ufffd", filename)
    quoted = filename.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
    disposition = f'form-data; name="attachment"; filename="{quoted}"'
    if not filename.isascii():
        disposition += "; filename*=UTF-8''" + urllib.parse.quote(filename, safe="")
    head = f"--{boundary}\r\nContent-Disposition: {disposition}\r\nContent-Type: {content_type}\r\n\r\n"
    tail = f"\r\n--{boundary}--\r\n"
    return head.encode("utf-8") + content + tail.encode("ascii"), f"multipart/form-data; boundary={boundary}"


def _uploaded_attachment_id(path: str, response: HttpResponse) -> str:
    """The id an upload answers: a JSON string, or a plain text body (quotes removed)."""
    body = response.body.decode("utf-8-sig", errors="replace").strip()
    try:
        value: Any = json.loads(body) if body else None
    except ValueError:
        value = body.strip('"').strip()
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise BakalariContractError(
            [f"POST {path} returned no attachment id (HTTP {response.status})"], "Komens attachment upload"
        )
    return value
