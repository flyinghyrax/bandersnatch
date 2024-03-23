import enum
import importlib.resources
import re
from collections.abc import Mapping
from configparser import (
    ConfigParser,
    ExtendedInterpolation,
    NoOptionError,
    NoSectionError,
)
from logging import getLogger
from pathlib import Path, PurePath
from typing import Any, Literal, Protocol, TypeAlias, TypeVar, cast, overload

from typing_extensions import Self

logger = getLogger("bandersnatch")

_T = TypeVar("_T")
_U = TypeVar("_U")


class Unset(enum.Enum):
    UNSET = enum.auto()


UNSET = Unset.UNSET
UNSET_T: TypeAlias = Literal[Unset.UNSET]


class ConfigModel(Protocol):

    @classmethod
    def from_config_source(cls, config: "BandersnatchConfig") -> Self: ...


_C = TypeVar("_C", bound=ConfigModel)


class BandersnatchConfig(ConfigParser):
    def __init__(self, defaults: Mapping[str, str] | None = None) -> None:
        super().__init__(
            defaults=defaults,
            delimiters=("=",),
            strict=True,
            interpolation=ExtendedInterpolation(),
        )

        self._validated_objects: dict[str, ConfigModel] = {}

    def optionxform(self, optionstr: str) -> str:
        return optionstr.lower().replace("-", "_")

    @overload
    def getpath(
        self,
        section: str,
        option: str,
        *,
        raw: bool = False,
        vars: Mapping[str, str] | None = None,
    ) -> PurePath: ...

    @overload
    def getpath(
        self,
        section: str,
        option: str,
        *,
        raw: bool = False,
        vars: Mapping[str, str] | None = None,
        fallback: _T,
    ) -> PurePath | _T: ...

    def getpath(
        self,
        section: str,
        option: str,
        *,
        raw: bool = False,
        vars: Mapping[str, str] | None = None,
        fallback: Any = UNSET,
    ) -> PurePath | _T:
        if fallback is UNSET:
            sval = self.get(section, option, raw=raw, vars=vars)
            return PurePath(sval)
        else:
            sval = self.get(section, option, raw=raw, vars=vars, fallback=fallback)
            return Path(sval) if isinstance(sval, str) else sval

    def load_package_defaults(self) -> None:
        with importlib.resources.open_text(
            "bandersnatch", "default.conf"
        ) as defaults_file:
            self.read_file(defaults_file)

    def load_user_config(self, config_path: Path) -> None:
        with config_path.open() as config_file:
            self.read_file(config_file)

    def get_validated(self, model: type[_C]) -> _C:
        name = model.__name__
        if name not in self._validated_objects:
            self._validated_objects[name] = model.from_config_source(self)
        return cast(_C, self._validated_objects[name])


_LEGACY_REF_RE = r".*\{\{.+\}\}.*"
_LEGACY_REF_PARTS_RE = r"""
    # capture everything from start-of-line to the opening '{{' braces into group 'pre'
    ^(?P<pre>.*)\{\{
    # restrict section names to ignore surrounding whitespace (different from
    # configparser's default SECTRE) and disallow '_' (since that's our separator)
    \s*
    (?P<section>[^_\s](?:[^_]*[^_\s]))
    # allow (but ignore) whitespace around the section-option delimiter
    \s*_\s*
    # option names ignore surrounding whitespace and can include any character, but
    # must start and end with a non-whitespace character
    (?P<option>\S(?:.*\S)?)
    \s*
    # capture from the closing '}}' braces to end-of-line into group 'post'
    \}\}(?P<post>.*)$
"""


def has_legacy_reference(value: str) -> bool:
    return re.match(_LEGACY_REF_RE, value) is not None


@overload
def eval_legacy_reference(config: ConfigParser, value: str) -> str: ...


@overload
def eval_legacy_reference(
    config: ConfigParser, value: str, *, fallback: _T = ...
) -> str | _T: ...


def eval_legacy_reference(
    config: ConfigParser, value: str, *, fallback: Any = UNSET
) -> Any:
    match_result = re.match(_LEGACY_REF_PARTS_RE, value, re.VERBOSE)
    if match_result is None:
        if fallback is UNSET:
            raise ValueError(f"Unable to parse config option reference from '{value}'")
        else:
            return fallback

    pre, sectname, optname, post = match_result.group(
        "pre", "section", "option", "post"
    )
    try:
        ref_value = config.get(sectname, optname)
        return f"{pre}{ref_value}{post}"
    except (NoSectionError, NoOptionError):
        if fallback is None:
            raise
        else:
            return fallback
