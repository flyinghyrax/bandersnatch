from configparser import ConfigParser, NoOptionError, NoSectionError
from logging import getLogger
from pathlib import PurePath
from typing import Any

from attrs import NOTHING, Factory, converters, define, field, fields, validators

from bandersnatch.configuration.comparison import ComparisonMethod, get_comparison_value
from bandersnatch.configuration.converter import (
    convert_by_annotation,
    if_str,
    not_empty,
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


def _default_diff_file(obj: "MirrorConfiguration") -> PurePath:
    if hasattr(obj, "directory"):
        return obj.directory / "mirrored-files"
    else:
        return PurePath("mirrored-files")


def _has_legacy_section_reference(value: str) -> bool:
    return "{{" in value and "}}" in value


def _eval_legacy_section_reference(config: ConfigParser, value: str) -> str | None:
    raw_ref = value.replace("{{", "").replace("}}", "")
    ref_section, _, ref_key = raw_ref.partition("_")
    ref_section = ref_section.strip()
    ref_key = ref_key.strip()
    try:
        return config.get(ref_section, ref_key)
    except (NoSectionError, NoOptionError):
        logger.error(
            "Invalid section reference in 'diff-file'. "
            "Saving diff files in the base mirror directory."
        )
        # setting to None and the attrs initializer should use the field's default value
        return None


# FIXME: diff-file was theoretically optional; the configuration validator would use
# the empty string for it if the option wasn't present. But in the implementation of the
# mirror subcommand that string was passed to 'storage_plugin.PATH_BACKEND' to create a
# path object, and `bool(Path(""))` is True, so all the `if diff_file` checks in the
# mirror function always evaluated to True, so in practice a diff file was always
# created.
# If we want diff_file to be optional then it should be changed here to have type
# `PurePath | None` and a default value of None. The dynamic default of
# '${directory}/mirrored-files' was only used if a "{{ }}"-style reference evaluation
# failed, not if the option was unset.
@define(
    kw_only=True,
    field_transformer=convert_by_annotation(
        {
            bool: converters.to_bool,
            int: int,
            float: float,
            PurePath: PurePath,
        }
    ),
)
class MirrorConfiguration:
    # directory option is required - currently the only [mirror] option with no default
    directory: PurePath

    storage_backend_name: str = field(
        default="filesystem", alias="storage_backend", validator=not_empty
    )

    master_url: str = field(
        default="https://pypi.org", alias="master", validator=not_empty
    )

    proxy_url: str | None = field(
        default=None,
        alias="proxy",
        validator=validators.optional(not_empty),
    )

    download_mirror_url: str | None = field(
        default=None,
        alias="download_mirror",
        validator=validators.optional(not_empty),
    )
    download_mirror_no_fallback: bool = False

    simple_format: SimpleFormat = field(
        default=SimpleFormat.ALL,
        converter=if_str(get_format_value),  # type: ignore
    )

    save_release_files: bool = field(default=True, alias="release_files")

    save_json: bool = field(default=False, alias="json")

    # this gets a non-empty default value in post-init if save_release_files is False
    root_uri: str = ""

    hash_index: bool = False

    keep_index_versions: int = field(default=0, validator=validators.ge(0))

    # default value is computed based on the value of 'directory'
    diff_file: PurePath = field(default=Factory(_default_diff_file, takes_self=True))

    diff_append_epoch: bool = False

    stop_on_error: bool = False

    timeout: float = field(default=10.0, validator=validators.gt(0))

    global_timeout: float = field(default=1800.0, validator=validators.gt(0))

    workers: int = field(default=3, validator=[validators.gt(0), validators.le(10)])

    verifiers: int = field(default=3, validator=[validators.gt(0), validators.le(10)])

    compare_method: ComparisonMethod = field(
        default=ComparisonMethod.HASH,
        converter=if_str(get_comparison_value),  # type: ignore
    )

    digest_name: SimpleDigest = field(
        default=SimpleDigest.SHA256,
        converter=if_str(get_digest_value),  # type: ignore
    )

    log_config: PurePath | None = field(
        default=None, converter=converters.optional(PurePath)
    )

    cleanup: bool = False

    # Called after the attrs class is constructed; useful for dynamic defaults or
    # validation where more than one option is involved.
    def __attrs_post_init__(self) -> None:
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

    # Create an instance with values from a ConfigParser. Iterates over the attrs fields
    # defined on the class and uses a field's alias (if defined) or name (otherwise) as
    # the key to lookup a value in the configparser section. Those keys and values are
    # collected into a keyword-arguments dict, which is passed to the attrs-generated
    # initializer. The generated initializer applies defined defaults, converters, and
    # validators per field.
    # Two config options don't 'fit the mold':
    # - root_uri only gets a default if release_files is False. We can't specify this
    #   at the field level but it fits ok in attrs' post-init hook.
    # - diff_file supports a non-standard syntax for referencing the value of another
    #   configparser option. It is preferred to use configparser's built-in support for
    #   value interpolation, but removing the custom reference syntax would be a
    #   breaking regression. The reference - if any - is evaluated prior to the attrs
    #   initializer so any converters or validators are applied to the evaluated value.
    @classmethod
    def from_config_parser(cls, config: ConfigParser) -> "MirrorConfiguration":
        try:
            source = config["mirror"]
        except (KeyError, NoSectionError):
            raise ConfigurationError(
                "Configuration file missing required section '[mirror]'"
            )

        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            key = f.alias or f.name
            value = source.get(key)

            # if the configuration field doesn't have a default value, then it's a
            # required field and the configuration is invalid if there's no value for
            # it in the section. If the config file format allows empty values then we
            # may see an empty string here instead of None.
            if f.default is NOTHING and not value:
                raise MissingOptionError.for_option("mirror", key)

            # special handling for diff-file, which supports referencing another config
            # entry via '{{ section_key }}' syntax.
            if (
                key == "diff_file"
                and value is not None
                and _has_legacy_section_reference(value)
            ):
                logger.warning(
                    "Found section reference using '{{ }}' in 'diff-file' path. "
                    "Use ConfigParser's built-in interpolation instead, for example "
                    "'${mirror.directory}/new-files'"
                )
                value = _eval_legacy_section_reference(config, value)

            if value is not None:
                kwargs[key] = value

        try:
            instance = cls(**kwargs)
        except ValueError as err:
            raise InvalidValueError.for_section("mirror", str(err)) from err
        except TypeError as err:
            raise ConfigurationError.for_section("mirror", str(err)) from err

        return instance
