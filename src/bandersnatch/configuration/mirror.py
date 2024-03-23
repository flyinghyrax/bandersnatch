from collections.abc import Callable
from configparser import NoOptionError, NoSectionError
from logging import getLogger
from pathlib import PurePath
from typing import Any

import attrs
from attrs import converters, define, field, validators

from bandersnatch.configuration.attrs_ext import if_str, not_empty
from bandersnatch.configuration.comparison import ComparisonMethod, get_comparison_value
from bandersnatch.configuration.core import (
    BandersnatchConfig,
    eval_legacy_reference,
    has_legacy_reference,
)
from bandersnatch.configuration.errors import (
    ConfigurationError,
    InvalidValueError,
    MissingOptionError,
)
from bandersnatch.simple import (
    SimpleDigest,
    SimpleFormat,
    get_digest_value,
    get_format_value,
)

logger = getLogger("bandersnatch")

_default_root_uri = "https://files.pythonhosted.org"


def _get_option_from_source(
    config: BandersnatchConfig, section_name: str, option: attrs.Attribute
) -> tuple[str, object | None]:
    option_name = option.alias or option.name

    # If an option doesn't have a default then it's a required option, and
    # it's an error for a required option to be missing from the config source
    if option.default is attrs.NOTHING and not config.has_option(
        section_name, option_name
    ):
        raise MissingOptionError.for_option(section_name, option_name)

    # From here forward if an option is missing in the config source we assume that
    # it has a default value. Reasonable to use None as a fallback here b/c its not
    # possible to specify None/null/nil in a configparser file.
    getter: Callable[..., Any]
    if option.converter is not None:
        getter = config.get
    elif option.type == bool:
        getter = config.getboolean
    elif option.type == int:
        getter = config.getint
    elif option.type == float:
        getter = config.getfloat
    elif option.type == PurePath:
        getter = config.getpath
    else:
        getter = config.get

    try:
        option_value = getter(section_name, option_name, fallback=None)
    except ValueError as exc:
        type_name = option.type.__name__ if option.type else "???"
        message = f"can't convert option '{option_name}' to expected type '{type_name}': {exc!s}"
        raise InvalidValueError.for_option(section_name, option_name, message)

    return option_name, option_value


def _check_legacy_reference(config: BandersnatchConfig, value: str) -> str | None:
    if not has_legacy_reference(value):
        return value

    logger.warning(
        "Found section reference using '{{ }}' in 'diff-file' path. "
        "Use ConfigParser's built-in extended interpolation instead, "
        "for example '${mirror:directory}/new-files'"
    )
    try:
        return eval_legacy_reference(config, value)
    except (ValueError, NoSectionError, NoOptionError) as ref_err:
        # NOTE: raise here would be a breaking change; previous impl. logged and
        # fell back to a default. Create exception anyway for consistent error messages.
        exc = InvalidValueError.for_option("mirror", "diff-file", str(ref_err))
        logger.error(str(exc))
        return None


@define(kw_only=True)
class MirrorConfiguration:
    # directory option is required - currently the only [mirror] option with no default
    directory: PurePath
    storage_backend_name: str = field(
        default="filesystem", alias="storage_backend", validator=not_empty
    )

    master_url: str = field(default="https://pypi.org", alias="master")
    proxy_url: str | None = field(default=None, alias="proxy")
    download_mirror_url: str | None = field(default=None, alias="download_mirror")
    download_mirror_no_fallback: bool = False

    save_release_files: bool = field(default=True, alias="release_files")
    save_json: bool = field(default=False, alias="json")

    simple_format: SimpleFormat = field(
        default=SimpleFormat.ALL,
        converter=if_str(get_format_value),  # type: ignore
    )

    compare_method: ComparisonMethod = field(
        default=ComparisonMethod.HASH,
        converter=if_str(get_comparison_value),  # type: ignore
    )

    digest_name: SimpleDigest = field(
        default=SimpleDigest.SHA256,
        converter=if_str(get_digest_value),  # type: ignore
    )

    # this gets a non-empty default value in post-init if save_release_files is False
    root_uri: str = ""

    hash_index: bool = False

    keep_index_versions: int = field(default=0, validator=validators.ge(0))

    # Probably better as PurePath, but str is more straightforward for handling '{{ }}'
    # style section reference syntax.
    diff_file: str | None = field(default=None)
    diff_append_epoch: bool = False

    stop_on_error: bool = False

    timeout: float = field(default=10.0, validator=validators.gt(0))

    global_timeout: float = field(default=1800.0, validator=validators.gt(0))

    workers: int = field(default=3, validator=[validators.gt(0), validators.le(10)])

    verifiers: int = field(default=3, validator=[validators.gt(0), validators.le(10)])

    log_config: PurePath | None = field(
        default=None, converter=converters.optional(PurePath)
    )

    cleanup: bool = field(default=False, metadata={"deprecated": True})

    # Called after the attrs class is constructed; useful for dynamic defaults or
    # validation where more than one option is involved.
    def __attrs_post_init__(self) -> None:
        # set dynamic default for root_uri if release-files is disabled
        if not self.save_release_files and not self.root_uri:
            logger.warning(
                (
                    "Inconsistent config: 'root_uri' should be set when "
                    "'release-files' is disabled. Please set 'root-uri' in the "
                    "[mirror] section of your config file. Using default value '%s'"
                ),
                _default_root_uri,
            )
            self.root_uri = _default_root_uri

        # set dynamic default for diff-file based on directory
        # FIXME: in previous implementation, diff-file seems theoretically optional.
        # The config validator would set the empty string if it wasn't in the config
        # file, and this dynamic default was only set if the value contained a '{{}}'
        # style section reference and that reference was invalid. In the 'mirror'
        # subcommand diff file sections where guarded by 'if diff_file' which would be
        # false for the empty string. But earlier in the mirror subcommand the value of
        # diff_file is passed to storage_plugin.PATH_BACKEND to create a path object,
        # and `bool(Path(""))` is True, so the 'if diff_file' checks always passed and
        # a diff file was always created.
        if self.diff_file is None:
            self.diff_file = str(self.directory / "mirrored-files")

    @classmethod
    def from_config_source(cls, config: BandersnatchConfig) -> "MirrorConfiguration":
        if "mirror" not in config:
            raise ConfigurationError(
                "Configuration file missing required section '[mirror]'"
            )

        kwargs: dict[str, Any] = {}

        for f in attrs.fields(cls):
            option_name, option_value = _get_option_from_source(config, "mirror", f)

            # special handling for diff-file, which supports referencing another config
            # entry via '{{ section_key }}' syntax.
            if option_name == "diff_file" and isinstance(option_value, str):
                option_value = _check_legacy_reference(config, option_value)

            # Add to constructor arguments for the configuration class
            if option_value is not None:
                kwargs[option_name] = option_value

        try:
            instance = cls(**kwargs)
        except ValueError as err:
            raise InvalidValueError.for_section("mirror", str(err)) from err
        except TypeError as err:
            raise ConfigurationError.for_section("mirror", str(err)) from err

        return instance
