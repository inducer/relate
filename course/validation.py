from __future__ import annotations


__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


import dataclasses
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Concatenate,
    ParamSpec,
    Self,
    TypeAlias,
    TypeVar,
    cast,
    dataclass_transform,
)

from annotated_types import Ge, Le
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext as _
from pydantic import (
    AfterValidator,
    AllowInfNan,
    ConfigDict,
    Field,
    NonNegativeFloat,
    StringConstraints,
    TypeAdapter,
    model_validator,
)
from typing_extensions import override

from course.constants import (
    ATTRIBUTES_FILENAME,
    DEFAULT_ACCESS_KINDS,
    MAX_EXTRA_CREDIT_FACTOR,
    ParticipationPermission as PPerm,
)
from course.repo import Blob_ish, Tree_ish, get_repo_tree
from relate.utils import string_concat


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence
    from pathlib import Path

    from pydantic import ValidationInfo

    from course.content import FlowDesc
    from course.models import Course
    from course.repo import FileSystemFakeRepo, Repo_ish


__doc__ = """
.. autoclass:: ValidationContext

Stub Docs
=========

.. class:: Course
.. class:: Repo_ish
"""

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


# {{{ validation tools

@dataclass_transform(
    kw_only_default=True,
    frozen_default=True,
    field_specifiers=(dataclasses.field, Field),
    )
def content_dataclass() -> Callable[[type[T]], type[T]]:
    def map_cls(cls: type[T]) -> type[T]:
        from pydantic.dataclasses import dataclass
        return cast("type[T]", dataclass(
                              frozen=True,
                              kw_only=True,
                              config=ConfigDict(
                                        use_enum_values=True,
                                        extra="forbid"))(cls))

    return map_cls


class ValidationError(RuntimeError):
    pass

# }}}


def dump_python_json(ta: TypeAdapter[T], obj: T) -> dict[str, object]:
    """I.e. dump to Python, but with JSON type limitations,
    e.g. no ``frozenset`` etc."""
    from json import loads
    return loads(ta.dump_json(obj))


@dataclass(frozen=True)
class ValidationWarning:
    location: str | None
    text: str


@dataclass(frozen=True)
class ValidationContext:
    """
    .. autoattribute:: repo
    .. autoattribute:: commit_sha
    .. autoattribute:: course
    """

    repo: Repo_ish | FileSystemFakeRepo
    commit_sha: bytes
    course: Course | None = None
    _location: str | None = None

    warnings: list[ValidationWarning] = field(default_factory=list)

    def replace_location(self, s: str) -> Self:
        return replace(self, _location=s)

    def with_location(self, s: str) -> Self:
        if self._location is None:
            return replace(self, _location=s)
        else:
            return replace(self, _location=f"{self._location}: {s}")

    def with_class(self, tp: type) -> Self:
        return self.with_location(tp.__name__)

    def with_vinfo(self, info: ValidationInfo):
        if info.field_name:
            return self.with_location(info.field_name)
        return self

    def add_warning(self, text: str) -> None:
        self.warnings.append(ValidationWarning(self._location, text))

    def annotate_errors(self,
            f: Callable[Concatenate[ValidationContext, P], R],
            *args: P.args,
            **kwargs: P.kwargs):
        try:
            return f(self, *args, **kwargs)
        except Exception as e:
            raise ValidationError(
                    f"{self._location}: {type(e).__name__}: {e!s}") from e

    def annotate_errors_except(self,
            pass_exc_classes: Collection[type[Exception]],
            f: Callable[Concatenate[ValidationContext, P], R],
            *args: P.args,
            **kwargs: P.kwargs):
        try:
            return f(self, *args, **kwargs)
        except Exception as e:
            if any(isinstance(e, cls) for cls in pass_exc_classes):
                raise
            raise ValidationError(
                    f"{self._location}: {type(e).__name__}: {e!s}") from e


def validate_nonempty(value: list[T]) -> list[T]:
    if not value:
        raise ValueError("may not be empty")
    return value


def get_validation_context(info: ValidationInfo) -> ValidationContext:
    vctx = info.context
    if not isinstance(vctx, ValidationContext):
        raise RuntimeError("no context in pydantic validation")
    return vctx.with_vinfo(info)

# }}}


# {{{ base data types

NonemptyStr: Annotated[str, StringConstraints(min_length=1)]


PointCount: TypeAlias = Annotated[
        float,
        AllowInfNan(False),
        Ge(0), Le(MAX_EXTRA_CREDIT_FACTOR)]


def _pydantic_validate_markup(
            text: str,
            info: ValidationInfo
        ) -> str:
    vctx = get_validation_context(info)

    def reverse_func(s: str) -> str:
        return s

    from course.content import markup_to_html
    try:
        markup_to_html(
                course=vctx.course,
                repo=vctx.repo,
                commit_sha=vctx.commit_sha,
                text=text,
                reverse_func=reverse_func,
                validate_only=True)
    except Exception as e:
        # from traceback import print_exc
        # print_exc()

        raise ValueError(f"{type(e).__name__}: {e!s}") from e

    return text


Markup: TypeAlias = Annotated[str, AfterValidator(_pydantic_validate_markup)]


ID_RE = re.compile(r"^[a-zA-Z_]\w*$")


IdentifierStr: TypeAlias = Annotated[str, StringConstraints(pattern=ID_RE)]


DOTTED_ID_RE = re.compile(r"^[\w]+(\.[\w]+)*$")


DottedIdentifierStr: TypeAlias = Annotated[
        str,
        StringConstraints(pattern=DOTTED_ID_RE)]


def _pydantic_validate_role(role: str, info: ValidationInfo):
    if role == "in_exam":
        return role

    if not ID_RE.match(role):
        raise ValueError("must be an identifier")

    vctx = get_validation_context(info)
    if vctx.course is not None:
        from course.models import ParticipationRole
        roles = ParticipationRole.objects.filter(course=vctx.course).values_list(
                "identifier", flat=True)

        if role not in roles:
            raise ValueError(_("invalid role '{}'").format(role))

    return role


ParticipationRoleStr: TypeAlias = Annotated[
        str,
        AfterValidator(_pydantic_validate_role)]


def _pydantic_validate_participation_tag(ptag: str, info: ValidationInfo):
    vctx = get_validation_context(info)
    if vctx.course is not None:
        from pytools import memoize_in

        @memoize_in(vctx, "available_participation_tags")
        def get_ptag_list() -> list[str]:
            from course.models import ParticipationTag
            return list(
                ParticipationTag.objects.filter(course=vctx.course)
                .values_list("name", flat=True))

        ptag_list = get_ptag_list()
        if ptag not in ptag_list:
            vctx.add_warning(
                _(
                    "Name of participation tag not recognized: '%(ptag_name)s'. "
                    "Known participation tag names: '%(known_ptag_names)s'")
                % {
                    "ptag_name": ptag,
                    "known_ptag_names": ", ".join(ptag_list),
                })


ParticipationTagStr: TypeAlias = Annotated[
        str,
        AfterValidator(_pydantic_validate_participation_tag)]


def _pydantic_validate_facility(
            facility: str,
            info: ValidationInfo,
        ) -> str:
    vctx = get_validation_context(info).with_vinfo(info)

    from course.utils import get_facilities_config
    facilities = get_facilities_config()
    if facilities is not None:
        if facility not in facilities:
            vctx.add_warning(_(
                "Name of facility not recognized: '%(fac_name)s'. "
                "Known facility names: '%(known_fac_names)s'")
                % {
                    "fac_name": facility,
                    "known_fac_names": ", ".join(facilities),
                    })

    return facility


FacilityStr: TypeAlias = Annotated[
        str,
        StringConstraints(min_length=1),
        AfterValidator(_pydantic_validate_facility)]


def _pydantic_validate_event_str(evt_str: str) -> str:
    # FIXME
    return evt_str


EventStr: TypeAlias = Annotated[
        str,
        AfterValidator(_pydantic_validate_event_str)]


def _pydantic_validate_repo_path_str(file_str: str, info: ValidationInfo) -> str:
    vctx = get_validation_context(info)

    # Do not globalize this import; this function gets mocked in testing.
    from course.repo import get_repo_blob
    try:
        get_repo_blob(vctx.repo, file_str, vctx.commit_sha)
    except ObjectDoesNotExist:
        raise ValueError(
                _("file '{}' not found in course repository")
                .format(file_str))

    return file_str


RepoPathStr: TypeAlias = Annotated[
        str,
        AfterValidator(_pydantic_validate_repo_path_str)]


class CSSUnit(StrEnum):
    PT = "pt"
    CM = "cm"
    MM = "mm"
    IN = "in"
    PERCENT = "%"
    EM = "em"
    EN = "en"
    EX = "ex"


@content_dataclass()
class CSSDimension:
    dimension: NonNegativeFloat
    unit: CSSUnit

    @override
    def __str__(self):
        return f"{self.dimension} {self.unit}"

    _width_unit_re: ClassVar[re.Pattern[str]]  = re.compile(
                                        r"^(\d*\.\d+|\d+)\s*(.*)$")

    @model_validator(mode="before")
    @classmethod
    def normalize_to_dict(cls, data: Any, info: ValidationInfo) -> Any:
        if isinstance(data, str):
            match = cls._width_unit_re.match(data)
            if match:
                return {"dimension": float(match.group(1)), "unit": match.group(2)}
            else:
                try:
                    data = float(data)
                except Exception:
                    pass

        if isinstance(data, (int, float)):
            vctx = get_validation_context(info)
            vctx.add_warning(_("CSS dimension without unit, assuming em. "
                             "This is deprecated and will stop working in 2027."))
            return {"dimension": data, "unit": "em"}

        return data


@dataclass(frozen=True)
class CSSDimensionMax:
    terms: Sequence[CSSDimension | CSSDimensionSum]

    @override
    def __str__(self):
        return f"max({', '.join(str(t) for t in self.terms)})"


@dataclass(frozen=True)
class CSSDimensionSum:
    terms: Sequence[CSSDimension]

    @override
    def __str__(self):
        # https://drafts.csswg.org/css-values-3/#calc-syntax
        # white space is required
        return f"calc({' + '.join(str(t) for t in self.terms)})"


@content_dataclass()
class AttributesFile:
    access_if_has_role: dict[ParticipationRoleStr, list[str]]

    @model_validator(mode="before")
    @classmethod
    def normalize_to_access_if_has_role_attr(cls,
                data: Any,
                info: ValidationInfo
            ) -> Any:
        vctx = get_validation_context(info)
        if isinstance(data, dict) and "access_if_has_role" not in data:
            vctx.add_warning(_(".attributes.yml without 'access_if_has_role' "
                               "at the top level. This is deprecated and will "
                               "stop working in 2026."))

            return {"access_if_has_role": data}

        return data


attributes_file_ta = TypeAdapter(AttributesFile)

# }}}


def check_attributes_yml(
        vctx: ValidationContext,
        repo: Repo_ish,
        path: str, tree: Tree_ish,
        access_kinds: Collection[str]) -> None:
    """
    This function reads the .attributes.yml file and checks
    that each item for each header is a string

    Example::

        # this validates
        unenrolled:
            - test1.pdf
        student:
            - test2.pdf

        # this does not validate
        unenrolled:
            - test1.pdf
        student:
            - test2.pdf
            - 42
    """
    from course.repo import get_true_repo_and_path
    true_repo, path = get_true_repo_and_path(repo, path)

    # {{{ analyze attributes file

    try:
        _dummy, attr_blob_sha = tree[ATTRIBUTES_FILENAME.encode()]
    except KeyError:
        # no .attributes.yml here
        pass
    except ValueError:
        # the path root only contains a directory
        pass
    else:
        from yaml import safe_load as load_yaml
        yaml_blob = true_repo[attr_blob_sha]  # pyright: ignore[reportArgumentType]
        if not isinstance(yaml_blob, Blob_ish):
            raise RuntimeError(
                    _("{}/{} is not a file/blob")
                    .format(path, ATTRIBUTES_FILENAME))
        yaml_data = load_yaml(yaml_blob.data)

        if path:
            loc = path + "/" + ATTRIBUTES_FILENAME
        else:
            loc = ATTRIBUTES_FILENAME

        vctx.with_location(loc).annotate_errors(
            lambda vctx, data: attributes_file_ta.validate_python(data, context=vctx),
            yaml_data)

    # }}}

    # {{{ analyze gitignore

    gitignore_lines: list[str] = []

    try:
        _dummy, gitignore_sha = tree[b".gitignore"]
    except KeyError:
        # no .gitignore here
        pass
    except ValueError:
        # the path root only contains a directory
        pass
    else:
        gitignore_blob = true_repo[gitignore_sha]  # pyright: ignore[reportArgumentType]
        if not isinstance(gitignore_blob, Blob_ish):
            raise ValueError(".gitignore is not a file/blob")
        gitignore_lines = gitignore_blob.data.decode("utf-8").split("\n")

    # }}}

    import stat
    from fnmatch import fnmatchcase

    for entry in tree.items():
        entry_name = entry.path.decode("utf-8")
        if any(fnmatchcase(entry_name, line) for line in gitignore_lines):
            continue

        if path:
            subpath = path+"/"+entry_name
        else:
            subpath = entry_name

        if stat.S_ISDIR(entry.mode):
            _dummy, blob_sha = tree[entry.path]
            subtree = true_repo[blob_sha]  # pyright: ignore[reportArgumentType]
            assert isinstance(subtree, Tree_ish)
            check_attributes_yml(vctx, true_repo, subpath, subtree, access_kinds)


# {{{ check whether flow grade identifiers were changed in sketchy ways

def check_grade_identifier_link(
            vctx: ValidationContext,  # pyright: ignore[reportUnusedParameter]
            course: Course,
            flow_id: str,
            flow_grade_identifier: str):

    from course.models import GradingOpportunity
    for bad_gopp in (
            GradingOpportunity.objects
            .filter(
                course=course,
                identifier=flow_grade_identifier)
            .exclude(flow_id=flow_id)):
        # 0 or 1 trips through this loop because of uniqueness

        raise ValidationError(
                _(
                    "{location}: existing grading opportunity with identifier "
                    "'{grade_identifier}' refers to flow '{other_flow_id}', however "
                    "flow code in this flow ('{new_flow_id}') specifies the same "
                    "grade identifier. "
                    "(Have you renamed the flow? If so, edit the grading "
                    "opportunity to match.)")
                .format(
                    grade_identifier=flow_grade_identifier,
                    other_flow_id=bad_gopp.flow_id,
                    new_flow_id=flow_id,
                    new_grade_identifier=flow_grade_identifier))

# }}}


# {{{ check whether page types were changed

def check_for_page_type_changes(
            course: Course,
            flow_id: str,
            flow_desc: FlowDesc):

    from course.models import FlowPageData
    for grp in flow_desc.groups:
        for page_desc in grp.pages:
            fpd_with_mismatched_page_types = list(
                    FlowPageData.objects
                    .filter(
                        flow_session__course=course,
                        flow_session__flow_id=flow_id,
                        group_id=grp.id,
                        page_id=page_desc.id)
                    .exclude(page_type=None)
                    .exclude(page_type=page_desc.type)
                    [0:1])

            if fpd_with_mismatched_page_types:
                mismatched_fpd, = fpd_with_mismatched_page_types
                raise ValueError(
                        _("Flow %(flow_id)s, group '%(group)s', page '%(page)s': "
                            "page type ('%(type_new)s') differs from "
                            "type used in database ('%(type_old)s'). "
                            "You must change the question ID if you change the "
                            "question type.")
                        % {"flow_id": flow_id, "group": grp.id,
                            "page": page_desc.id,
                            "type_new": page_desc.type,
                            "type_old": mismatched_fpd.page_type})

# }}}


def validate_flow_id(vctx: ValidationContext, location: str, flow_id: str) -> None:

    from course.constants import FLOW_ID_REGEX
    match = re.match("^" + FLOW_ID_REGEX + "$", flow_id)
    if match is None:
        raise ValidationError(
            string_concat("%s: ",
                          _("invalid flow name. "
                            "Flow names may only contain (roman) "
                            "letters, numbers, "
                            "dashes and underscores."))
            % location)


def validate_static_page_name(
        vctx: ValidationContext, location: str, page_name: str) -> None:
    from course.constants import STATICPAGE_PATH_REGEX
    match = re.match("^" + STATICPAGE_PATH_REGEX + "$", page_name)
    if match is None:
        raise ValidationError(
            string_concat("%s: ",
                          _(
                              "invalid page name. "
                              "Page names may only contain "
                              "alphanumeric characters (any language) "
                              "and hyphens."
                          ))
            % location)


def validate_course_content(
            repo: Repo_ish | FileSystemFakeRepo,
            course_file: str,
            events_file: str,
            validate_sha: bytes,
            course: Course | None = None):
    from course.content import (
        calendar_ta,
        flow_desc_ta,
        get_model_from_repo,
        static_page_ta,
    )
    vctx = ValidationContext(
            repo=repo,
            commit_sha=validate_sha,
            course=course)

    vctx.with_location(course_file).annotate_errors(
            get_model_from_repo,
            static_page_ta, repo, course_file, validate_sha)

    try:
        vctx.with_location(events_file).annotate_errors_except(
            [ObjectDoesNotExist],
            get_model_from_repo,
            calendar_ta, repo, events_file,
            commit_sha=validate_sha, cached=False,
        )

    except ObjectDoesNotExist:
        if events_file != "events.yml":
            vctx.with_location(events_file).add_warning(
                    _("Your course repository does not have an events "
                        "file named '%s'.") % events_file)
        else:
            # That's OK--no calendar info.
            pass

    if vctx.course is not None:
        from course.models import (
            ParticipationPermission,
            ParticipationRolePermission,
        )
        access_kinds_or_nones: Collection[str | None] = frozenset(
                ParticipationPermission.objects
                .filter(
                    participation__course=vctx.course,
                    permission=PPerm.access_files_for,
                    )
                .values_list("argument", flat=True)) | frozenset(
                        ParticipationRolePermission.objects
                        .filter(
                            role__course=vctx.course,
                            permission=PPerm.access_files_for,
                            )
                        .values_list("argument", flat=True))

        access_kinds: Collection[str] = frozenset(
            k for k in access_kinds_or_nones if k is not None)

    else:
        access_kinds = DEFAULT_ACCESS_KINDS

    check_attributes_yml(
            vctx, repo, "",
            get_repo_tree(repo, "", validate_sha),
            access_kinds)

    try:
        get_repo_tree(repo, "media", validate_sha)
    except ObjectDoesNotExist:
        # That's great--no media directory.
        pass
    else:
        vctx.with_location("media/").add_warning(
                _(
                    "Your course repository has a 'media/' directory. "
                    "Linking to media files using 'media:' is discouraged. "
                    "Use the 'repo:' and 'repocur:' linkng schemes instead."))

    # {{{ flows

    try:
        flows_tree = get_repo_tree(repo, "flows", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        used_grade_identifiers: set[str] = set()

        for entry in flows_tree.items():
            entry_path = entry.path.decode("utf-8")
            if not entry_path.endswith(".yml"):
                continue

            flow_id = entry_path[:-4]
            location = entry_path
            validate_flow_id(vctx, location, flow_id)

            location = f"flows/{entry_path}"
            flow_vctx = vctx.with_location(location)
            flow_desc = flow_vctx.annotate_errors(
                get_model_from_repo,
                flow_desc_ta, repo, location, commit_sha=validate_sha)

            # {{{ check grade_identifier

            flow_grade_identifier = None
            flow_grade_identifier = flow_desc.rules.grade_identifier

            if (
                    flow_grade_identifier is not None
                    and {flow_grade_identifier} & used_grade_identifiers):
                raise ValidationError(
                        string_concat("%s: ",
                                      _("flow uses the same grade_identifier "
                                        "as another flow"))
                        % location)

            if flow_grade_identifier is not None:
                used_grade_identifiers.add(flow_grade_identifier)

            if (course is not None
                    and flow_grade_identifier is not None):
                flow_vctx.annotate_errors(check_grade_identifier_link,
                        course, flow_id, flow_grade_identifier)

            # }}}

            if course is not None:
                check_for_page_type_changes(course, flow_id, flow_desc)

    # }}}

    # {{{ static pages

    try:
        pages_tree = get_repo_tree(repo, "staticpages", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in pages_tree.items():
            entry_path = entry.path.decode("utf-8")
            if not entry_path.endswith(".yml"):
                continue

            page_name = entry_path[:-4]
            location = entry_path
            validate_static_page_name(vctx, location, page_name)

            location = f"staticpages/{entry_path}"
            vctx.with_location(location).annotate_errors(
                    get_model_from_repo,
                    static_page_ta, repo, location,
                    commit_sha=validate_sha)

    # }}}

    return vctx.warnings


def validate_course_on_filesystem(root: Path, course_file: str, events_file: str):
    from course.repo import FileSystemFakeRepo
    fake_repo = FileSystemFakeRepo(root)
    warnings = validate_course_content(
            fake_repo, course_file, events_file, validate_sha=b"", course=None)

    if warnings:
        print(_("WARNINGS: "))
        for w in warnings:
            print("***", w.location, w.text)

    return bool(warnings)

# vim: foldmethod=marker
