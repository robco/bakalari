"""GDPR: the school's data protection officers and the consents to the processing of personal data.

The Gdpr module grants the rights ShowCommissioners, ShowOwnConsents (the consents of the logged-in person) and
ShowChildConsents (those of the children of a parent account). A consent's ``Id`` is a number, ``State`` is e.g.
``Agreed`` and ``Rights`` say whether the person may agree, disagree or ask to revoke the consent. Answering a consent
(``/api/3/gdpr/consent``) and the objection and report forms (``POST /api/3/gdpr/commissioner/send-objection`` and
``send-report``) are not wrapped because their request bodies are unknown; :meth:`~bakalari.BakalariClient.request`
reaches them.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional

from ._core import ClientCore, api_path
from ._parse import (
    check_shape,
    ident,
    mapping,
    objects,
    parse_date,
    parse_datetime,
    require_int,
    require_mapping,
    text,
    to_bool,
    to_int,
)
from .models import Model

__all__ = ["Commissioner", "Consent", "GdprEndpoints", "parse_commissioners", "parse_consents"]


@dataclass(frozen=True)
class Commissioner(Model):
    """A data protection officer (``pověřenec pro ochranu osobních údajů``) of the school and their contacts;
    ``data_box`` is the id of their Czech data box (datová schránka)."""

    id: str
    name: str
    mobile: str = ""
    phone: str = ""
    email: str = ""
    web: str = ""
    data_box: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Commissioner":
        """Parses one entry of the ``Commissioners`` list."""
        return cls(
            id=ident(data.get("Id")),
            name=text(data.get("Name")),
            mobile=text(data.get("Mobile")),
            phone=text(data.get("Phone")),
            email=text(data.get("Email")),
            web=text(data.get("Web")),
            data_box=text(data.get("DataBox")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Consent(Model):
    """A consent to the processing of personal data: what is processed (``personal_data``) and why
    (``usage_purpose``), its plain-text ``body``, its validity (the text ``validity``, ``valid_from``, ``valid_to`` and
    ``valid_years``, each empty when not set), the person's answer ``state`` (e.g. ``Agreed``) and which answers the
    person may give now. ``id`` is the server's numeric id as a string; ``person_type`` is ``parents``, ``student``,
    ..."""

    id: str
    person_type: str = ""
    person_id: str = ""
    created: Optional[dt.datetime] = None
    title: str = ""
    personal_data: str = ""
    usage_purpose: str = ""
    body: str = ""
    validity: str = ""
    valid_from: Optional[dt.date] = None
    valid_to: Optional[dt.date] = None
    valid_years: Optional[int] = None
    state: str = ""
    can_agree: bool = False
    can_disagree: bool = False
    can_revoke_request: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Consent":
        """Parses one entry of the ``PersonConsents`` list; the ``Rights`` object becomes the ``can_*`` flags."""
        rights = mapping(data.get("Rights"))
        return cls(
            id=ident(data.get("Id")),
            person_type=text(data.get("PersonType")),
            person_id=ident(data.get("PersonId")),
            created=parse_datetime(data.get("Created")),
            title=text(data.get("Title")),
            personal_data=text(data.get("PersonalData")),
            usage_purpose=text(data.get("UsagePurpose")),
            body=text(data.get("Body")),
            validity=text(data.get("Validity")),
            valid_from=parse_date(data.get("ValidFrom")),
            valid_to=parse_date(data.get("ValidTo")),
            valid_years=to_int(data.get("ValidYears")),
            state=text(data.get("State")),
            can_agree=to_bool(rights.get("CanAgree")),
            can_disagree=to_bool(rights.get("CanDisagree")),
            can_revoke_request=to_bool(rights.get("CanRevokeRequest")),
            raw=dict(data),
        )

    @property
    def is_agreed(self) -> bool:
        """True when the person has agreed to the consent (``state`` is ``Agreed``)."""
        return self.state.lower() == "agreed"


def parse_commissioners(data: Any, *, validate: bool = True) -> List[Commissioner]:
    """Parses a ``{"Commissioners": [...]}`` payload. With ``validate`` (default) a payload without that list of
    objects raises :class:`~bakalari.BakalariContractError`; a payload that is not a JSON object always raises."""
    if validate:
        payload = check_shape(data, "commissioner list", lists=("Commissioners",))
    else:
        payload = require_mapping(data, "commissioner list")
    return [Commissioner.from_json(item) for item in objects(payload.get("Commissioners"))]


def parse_consents(data: Any, *, validate: bool = True) -> List[Consent]:
    """Parses a ``{"PersonConsents": [...]}`` payload. With ``validate`` (default) a payload without that list of
    objects raises :class:`~bakalari.BakalariContractError`; a payload that is not a JSON object always raises."""
    if validate:
        payload = check_shape(data, "consent list", lists=("PersonConsents",))
    else:
        payload = require_mapping(data, "consent list")
    return [Consent.from_json(item) for item in objects(payload.get("PersonConsents"))]


class GdprEndpoints(ClientCore):
    """GDPR endpoints of :class:`~bakalari.BakalariClient`."""

    def gdpr_commissioners(self, *, validate: bool = True) -> List[Commissioner]:
        """``GET /api/3/gdpr/commissioners``: the school's data protection officers with their contacts (right
        ShowCommissioners); the list is empty when the school has entered none."""
        return parse_commissioners(self.get_json(api_path("gdpr", "commissioners")), validate=validate)

    def consents(self, *, validate: bool = True) -> List[Consent]:
        """``GET /api/3/gdpr/consents/person``: the consents of the logged-in person (right ShowOwnConsents)."""
        return parse_consents(self.get_json(api_path("gdpr", "consents", "person")), validate=validate)

    def child_consents(self, *, validate: bool = True) -> List[Consent]:
        """``GET /api/3/gdpr/consents/person/child``: the consents that concern the children of a parent account
        (right ShowChildConsents)."""
        return parse_consents(self.get_json(api_path("gdpr", "consents", "person", "child")), validate=validate)

    def new_consents_count(self) -> int:
        """``GET /api/3/gdpr/consents/person/new``: the number of new consents of the person, a counter like the
        unread messages count."""
        return require_int(self.get_json(api_path("gdpr", "consents", "person", "new")), "new consents count")
