"""Package guards: the public exports, the version and the endpoint methods of BakalariClient."""
import ast
import importlib
import inspect
import pkgutil
import re
import types
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

import bakalari
from bakalari import BakalariClient, BakalariError, Model, errors

PACKAGE_DIR = Path(bakalari.__file__).parent

# PEP 440, appendix B: a version in canonical form (as PyPI shows it; no local version segment).
CANONICAL_VERSION = re.compile(
    r"^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?"
    r"(\.dev(0|[1-9][0-9]*))?$"
)

# Every public attribute of BakalariClient and its constructor, by the class that defines it, with the parameters
# after self or cls written like a signature: the positional ones in order, then "*" and the keyword-only ones; a
# trailing "=" marks a parameter callers may leave out. Removing, renaming or reordering one, or dropping its
# default, breaks callers, so a change here is an API change.
CLIENT_METHODS: Dict[str, Dict[str, str]] = {
    "UserEndpoints": {
        "user_profile": "*, validate=",
        "enabled_modules": "",
        "student_at_school": "",
        "web_modules": "*, validate=",
        "login_token": "",
        "web_login_url": "return_url=",
        "register_notification": "token",
    },
    "TimetableEndpoints": {
        "timetable_json": "kind=, date=, *, class_id=",
        "actual_timetable": "date=, *, validate=",
        "permanent_timetable": "*, validate=",
        "class_timetable": "class_id, date=, *, permanent=, validate=",
    },
    "MarksEndpoints": {
        "marks": "*, since=, validate=",
        "new_marks_count": "",
        "final_marks": "*, validate=",
        "pedagogical_measures": "*, validate=",
        "what_if": "marks, *, validate=",
        "predict_marks": "subject, hypothetical, *, marks=, validate=",
        "confirm_marks": "mark_ids",
    },
    "AbsenceEndpoints": {
        "absence": "*, validate=",
    },
    "SubjectsEndpoints": {
        "subjects": "*, validate=",
        "subject_themes": "subject_id, *, validate=",
    },
    "HomeworksEndpoints": {
        "homeworks": "since=, until=, *, validate=",
        "active_homeworks_count": "",
        "set_homework_done": "homework_id, done=",
    },
    "EventsEndpoints": {
        "events": "since=, *, scope=, validate=",
    },
    "SubstitutionsEndpoints": {
        "substitutions": "since=, *, validate=",
    },
    "KomensEndpoints": {
        "messages": "folder=, *, since=, validate=",
        "message": "message_id, folder=, *, validate=",
        "unread_messages_count": "folder=",
        "mark_message_read": "message_id",
        "confirm_message": "message_id",
        "hide_message": "message_id",
        "unhide_message": "message_id",
        "delete_message": "message_id",
        "message_types": "*, reply_to=, validate=",
        "send_message": (
            "*, message_type, text, recipient_type, recipients=, title=, previous_message_id=, attachments=, "
            "require_confirmation=, email_notification=, copy_for_class_teacher=, copy_for_parent=, "
            "send_as_director=, lifetime=, date_from=, date_to=, type_of_rating_id=, scale=, extra="
        ),
        "reply_to_message": "message, text, *, title=, attachments=, require_confirmation=",
        "download_attachment": "attachment_id",
        "upload_attachment": "source, *, filename=, content_type=",
        "rating_templates": "",
    },
    "GdprEndpoints": {
        "gdpr_commissioners": "*, validate=",
        "consents": "*, validate=",
        "child_consents": "*, validate=",
        "new_consents_count": "",
    },
    "PaymentsEndpoints": {
        "class_fund_summary": "",
        "class_fund_payments": "*, sort=, search=, validate=",
        "class_fund_payment_info": "",
        "regular_payments_summary": "",
    },
    "TeacherEndpoints": {
        "classbook": "since, until, *, validate=",
        "save_classbook_record": "record, *, validate=",
        "lesson_tags": "",
        "lesson_absence": "lesson_id",
        "lesson_past": "lesson_id",
        "lesson_students_timetable": "lesson_id",
        "marking_atoms": "*, validate=",
        "marking_marks": "atom_id, *, validate=",
        "emergency_configuration": "",
    },
    "PublicTimetableEndpoints": {
        "public_timetable_targets": "",
        "public_timetable": "kind, target_id, *, week=, validate=",
        "public_timetable_url": "kind, target_id, *, week=",
    },
    "ClientCore": {
        "__init__": (
            "base_url, username=, password=, *, refresh_token=, client_id=, timeout=, renew_margin=, retries=, "
            "retry_backoff=, ssl_context=, transport=, clock=, sleep=, on_session_update=, user_agent="
        ),
        "from_env": "*, username_env=, password_env=, base_url=, environ=, **kwargs",
        "is_authenticated": "property",
        "token_info": "property",
        "available_api_versions": "",
        "api_version": "",
        "login": "username=, password=",
        "refresh": "",
        "ensure_token": "",
        "logout": "",
        "export_session": "",
        "import_session": "state",
        "request": (
            "method, path, *, params=, form=, json_body=, data=, headers=, authorized=, access_token=, "
            "expected_status="
        ),
        "get_json": "path, params=, *, authorized=",
        "post_json": "path, *, params=, form=, json_body=, expected_status=",
    },
}

_POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_BY_KEYWORD = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
_VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


def submodules() -> List[types.ModuleType]:
    """Every module of the package but ``__main__``, imported."""
    names = sorted(info.name for info in pkgutil.iter_modules(bakalari.__path__) if info.name != "__main__")
    return [importlib.import_module(f"bakalari.{name}") for name in names]


def library_modules() -> List[types.ModuleType]:
    """The public modules of the library: neither the private ones nor the command line application."""
    return [
        module for module in submodules()
        if not module.__name__.rpartition(".")[2].startswith("_") and module.__name__ != "bakalari.cli"
    ]


def public_names(module: types.ModuleType) -> Set[str]:
    """The module's ``__all__``, or its names without a leading underscore when it defines none."""
    names = getattr(module, "__all__", None)
    return set(names) if names is not None else {name for name in vars(module) if not name.startswith("_")}


def duplicates(names: List[str]) -> List[str]:
    return sorted(name for name, count in Counter(names).items() if count > 1)


def own_docstring(value: Any) -> str:
    """The docstring an object defines itself: not inherited, and not the signature a dataclass generates."""
    doc = (vars(value).get("__doc__") if inspect.isclass(value) else getattr(value, "__doc__", None)) or ""
    if inspect.isclass(value) and doc.startswith(f"{value.__name__}("):
        return ""
    return doc.strip()


def unwrap(attribute: Any) -> Any:
    """The function behind a classmethod, staticmethod or property."""
    if isinstance(attribute, (classmethod, staticmethod)):
        return attribute.__func__
    if isinstance(attribute, property):
        return attribute.fget
    return attribute


def signature_problems(function: Any, expected: str) -> List[str]:
    """How the parameters of ``function`` after self or cls break calls written for ``expected`` (see
    ``CLIENT_METHODS``): a positional parameter renamed or moved, a listed parameter gone, positional-only or
    without its default, or a new parameter without a default."""
    tokens = [token.strip() for token in expected.split(",") if token.strip()]
    star = tokens.index("*") if "*" in tokens else len(tokens)
    positional = [token.rstrip("=") for token in tokens[:star]]
    keywords = [token.rstrip("=") for token in tokens[star + 1:]]
    optional = {token.rstrip("=") for token in tokens if token.endswith("=")}
    parameters = list(inspect.signature(function).parameters.values())[1:]
    by_name = {parameter.name: parameter for parameter in parameters}
    actual = [parameter.name for parameter in parameters if parameter.kind in _POSITIONAL]
    problems = []
    if actual[: len(positional)] != positional:
        problems.append(f"the positional parameters are {actual}, expected {positional} first")
    for name in positional + keywords:
        if name == "**kwargs":
            if not any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
                problems.append("**kwargs is gone")
            continue
        parameter = by_name.get(name)
        if parameter is None:
            problems.append(f"the parameter {name!r} is gone")
        elif parameter.kind not in _BY_KEYWORD:
            problems.append(f"the parameter {name!r} can no longer be passed by keyword")
        elif name in optional and parameter.default is inspect.Parameter.empty:
            problems.append(f"the parameter {name!r} lost its default")
    for parameter in parameters:
        new = parameter.name not in positional and parameter.name not in keywords
        if new and parameter.kind not in _VARIADIC and parameter.default is inspect.Parameter.empty:
            problems.append(f"the new parameter {parameter.name!r} has no default")
    return problems


class ExportsTest(unittest.TestCase):
    def test_package_has_a_docstring(self):
        self.assertTrue((bakalari.__doc__ or "").strip())

    def test_every_exported_name_imports(self):
        self.assertTrue(all(isinstance(name, str) for name in bakalari.__all__))
        self.assertEqual([name for name in bakalari.__all__ if not hasattr(bakalari, name)], [])
        namespace: Dict[str, Any] = {}
        exec("from bakalari import *", namespace)
        self.assertEqual(sorted(set(bakalari.__all__) - set(namespace)), [])

    def test_exported_names_are_unique(self):
        self.assertEqual(duplicates(bakalari.__all__), [])

    def test_all_lists_exactly_the_public_names_of_the_package(self):
        public = {
            name
            for name, value in vars(bakalari).items()
            if not name.startswith("_") and not isinstance(value, types.ModuleType)
        }
        self.assertEqual(sorted(public - set(bakalari.__all__)), [], "public, but missing from __all__")
        self.assertEqual(sorted(set(bakalari.__all__) - public - {"__version__"}), [], "in __all__, but not public")

    def test_exported_names_are_public_names_of_their_modules(self):
        modules = library_modules()
        for name in bakalari.__all__:
            if name == "__version__":
                continue
            with self.subTest(name=name):
                self.assertFalse(name.startswith("_"))
                homes = [module for module in modules if name in public_names(module)]
                self.assertTrue(homes, "no public module of the package lists it")
                for module in homes:
                    self.assertIs(getattr(module, name), getattr(bakalari, name), module.__name__)

    def test_client_errors_and_models_of_every_module_are_exported(self):
        exported = set(bakalari.__all__)
        self.assertEqual(sorted(set(bakalari.client.__all__) - exported), [])
        error_classes = {
            name
            for name, value in vars(errors).items()
            if inspect.isclass(value) and issubclass(value, BakalariError) and value.__module__ == errors.__name__
        }
        self.assertEqual(sorted(error_classes - exported), [])
        models = {
            name
            for module in library_modules()
            for name, value in vars(module).items()
            if not name.startswith("_") and inspect.isclass(value) and issubclass(value, Model)
            and value.__module__ == module.__name__
        }
        self.assertTrue({"Model", "Item", "AttachmentInfo", "Timetable", "Marks", "Message"} <= models)
        self.assertEqual(sorted(models - exported), [])

    def test_exported_classes_and_functions_have_a_docstring(self):
        undocumented = [
            name
            for name in bakalari.__all__
            if (inspect.isclass(getattr(bakalari, name)) or inspect.isfunction(getattr(bakalari, name)))
            and not own_docstring(getattr(bakalari, name))
        ]
        self.assertEqual(undocumented, [])

    def test_module_all_lists_only_existing_names(self):
        for module in submodules():
            names = getattr(module, "__all__", None)
            if names is None:
                continue
            with self.subTest(module=module.__name__):
                self.assertEqual([name for name in names if not hasattr(module, name)], [])
                self.assertEqual([name for name in names if name.startswith("_")], [])
                self.assertEqual(duplicates(list(names)), [])

    def test_modules_never_import_from_the_package_root(self):
        # The package root imports every module, so a module importing a name from the root would form a cycle.
        module_names = {info.name for info in pkgutil.iter_modules(bakalari.__path__)}
        problems = []
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            if path.name == "__init__.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names if alias.name == "bakalari"]
                elif isinstance(node, ast.ImportFrom) and (node.level, node.module) in ((1, None), (0, "bakalari")):
                    names = [alias.name for alias in node.names if alias.name not in module_names]
                else:
                    continue
                problems += [f"{path.name}:{node.lineno} imports {name}" for name in names]
        self.assertEqual(problems, [])


class VersionTest(unittest.TestCase):
    def test_version_is_a_canonical_pep_440_version(self):
        self.assertIsInstance(bakalari.__version__, str)
        self.assertRegex(bakalari.__version__, CANONICAL_VERSION)

    def test_version_is_the_literal_in_the_version_file(self):
        # A plain string literal, which setuptools reads without importing the package (pyproject.toml).
        values = []
        for node in ast.parse((PACKAGE_DIR / "_version.py").read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            if [getattr(target, "id", None) for target in targets] == ["__version__"]:
                values.append(ast.literal_eval(node.value))
        self.assertEqual(values, [bakalari.__version__])


class ClientMethodsTest(unittest.TestCase):
    def test_client_exposes_every_endpoint_method(self):
        bases = {base.__name__: base for base in BakalariClient.__mro__}
        for owner_name, methods in CLIENT_METHODS.items():
            self.assertIn(owner_name, bases, "BakalariClient no longer combines this class")
            owner = bases[owner_name]
            for name, parameters in methods.items():
                with self.subTest(method=f"{owner_name}.{name}"):
                    self.assertIn(name, vars(owner), "the method is gone")
                    found = inspect.getattr_static(BakalariClient, name)
                    self.assertIs(found, vars(owner)[name], "another base class of BakalariClient shadows it")
                    if parameters == "property":
                        self.assertIsInstance(found, property)
                        continue
                    function = found.__func__ if isinstance(found, classmethod) else found
                    self.assertTrue(inspect.isfunction(function), "not a method")
                    self.assertEqual(signature_problems(function, parameters), [])

    def test_every_public_client_method_is_listed(self):
        listed = [name for methods in CLIENT_METHODS.values() for name in methods]
        self.assertEqual(duplicates(listed), [])
        public = {name for name in dir(BakalariClient) if not name.startswith("_")}
        self.assertEqual(sorted(public - set(listed)), [], "add the new public methods to CLIENT_METHODS")

    def test_no_base_class_shadows_another(self):
        owners: Dict[str, List[str]] = {}
        for base in BakalariClient.__mro__:
            for name in vars(base):
                if not name.startswith("_"):
                    owners.setdefault(name, []).append(base.__name__)
        self.assertEqual({name: classes for name, classes in owners.items() if len(classes) > 1}, {})

    def test_every_public_client_method_has_a_docstring(self):
        self.assertTrue(own_docstring(BakalariClient))
        undocumented = [
            name
            for name in dir(BakalariClient)
            if not name.startswith("_")
            and not own_docstring(unwrap(inspect.getattr_static(BakalariClient, name)))
        ]
        self.assertEqual(undocumented, [])

    def test_the_signature_check_detects_incompatible_changes(self):
        def method(self, kind, date=None, *, validate=True, extra=None):
            """A stand-in endpoint method: ``extra`` is a new optional parameter."""

        def positional_only(self, kind, /, date=None):
            """A stand-in endpoint method whose ``kind`` became positional-only."""

        self.assertEqual(signature_problems(method, "kind, date=, *, validate="), [])
        self.assertEqual(signature_problems(method, "kind, *, date=, validate="), [])  # keyword-only before: fine
        self.assertEqual(signature_problems(method, "kind=, date=, *, validate="), [
            "the parameter 'kind' lost its default",
        ])
        self.assertEqual(signature_problems(method, "date=, kind, *, validate="), [
            "the positional parameters are ['kind', 'date'], expected ['date', 'kind'] first",
        ])
        self.assertEqual(signature_problems(method, "kind, date=, *, since="), ["the parameter 'since' is gone"])
        self.assertEqual(signature_problems(method, "*, validate="), ["the new parameter 'kind' has no default"])
        self.assertEqual(signature_problems(positional_only, "kind, date="), [
            "the parameter 'kind' can no longer be passed by keyword",
        ])


if __name__ == "__main__":
    unittest.main()
