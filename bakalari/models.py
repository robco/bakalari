"""Building blocks shared by the response models of every module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, cast

from ._parse import ident, text, to_int, to_jsonable


class Model:
    """Base of the response models.

    The models are frozen dataclasses. ``to_dict()`` returns JSON-serialisable data with the fields shown in
    ``repr()`` (nested models become dicts, dates ISO strings); the server's own object stays available in the
    ``raw`` field of the models that have one, for fields this client does not map.
    """

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable data of the fields shown in ``repr()``: nested models become dicts, dates and times
        ISO strings, tuples lists; ``raw`` and secret fields are left out."""
        return cast(Dict[str, Any], to_jsonable(self))


@dataclass(frozen=True)
class Item(Model):
    """An id, abbreviation and name: a class, group, subject, teacher, room, week cycle, event type, ...

    ``id`` is exactly what the server sent (it may be space-padded); ``abbrev`` and ``name`` are trimmed.
    """

    id: str
    abbrev: str
    name: str

    def __str__(self) -> str:
        return self.name or self.abbrev or self.id

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Item":
        return cls(id=ident(data.get("Id")), abbrev=text(data.get("Abbrev")), name=text(data.get("Name")))

    @classmethod
    def optional(cls, data: Any) -> Optional["Item"]:
        """Parses an object that may be ``null``; an object whose id, abbreviation and name are all empty (which
        the server sends for deleted classes and rooms) is ``None`` too."""
        if not isinstance(data, Mapping):
            return None
        item = cls.from_json(data)
        return item if (item.id.strip() or item.abbrev or item.name) else None


@dataclass(frozen=True)
class AttachmentInfo(Model):
    """A file attached to a Komens message or a homework. Download it with
    :meth:`BakalariClient.download_attachment <bakalari.BakalariClient.download_attachment>` using ``id``."""

    id: str
    name: str
    content_type: str = ""
    size: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "AttachmentInfo":
        return cls(
            id=ident(data.get("Id")),
            name=text(data.get("Name")),
            content_type=text(data.get("Type")),
            size=to_int(data.get("Size")),
            raw=dict(data),
        )
