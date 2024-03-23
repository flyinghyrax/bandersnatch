import sys
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import attrs
import pytest

import bandersnatch.configuration.original as og
from bandersnatch.configuration.comparison import ComparisonMethod
from bandersnatch.configuration.core import BandersnatchConfig
from bandersnatch.configuration.errors import (
    ConfigurationError,
    InvalidValueError,
    MissingOptionError,
)
from bandersnatch.configuration.mirror import MirrorConfiguration
from bandersnatch.simple import SimpleDigest


def load_config_str(content: str) -> BandersnatchConfig:
    cfg = BandersnatchConfig()
    cfg.read_string(content)
    return cfg


def test_empty_config() -> None:
    cfg = BandersnatchConfig()
    with pytest.raises(ConfigurationError, match="missing required section"):
        _ = cfg.get_validated(MirrorConfiguration)


def test_empty_section() -> None:
    cfg = load_config_str("[mirror]\n")
    with pytest.raises(MissingOptionError, match="missing required option"):
        _ = cfg.get_validated(MirrorConfiguration)


def test_reuse_typed_configs() -> None:
    content = """\
    [mirror]
    directory = /test
    """
    cfg = load_config_str(content)
    opts1 = cfg.get_validated(MirrorConfiguration)
    opts2 = cfg.get_validated(MirrorConfiguration)
    assert opts1 is opts2


def test_minimal_mirror_config() -> None:
    test_path = "/usr/share/mirror"
    content = f"""\
    [mirror]
    directory = {test_path}
    """

    cfg = load_config_str(content)
    loaded_config = cfg.get_validated(MirrorConfiguration)
    direct_config = MirrorConfiguration(directory=Path(test_path))
    # excessive? maybe
    assert isinstance(loaded_config, MirrorConfiguration)
    # these should be equivalent
    assert loaded_config == direct_config


@pytest.mark.parametrize(
    "keep_index_versions_key",
    [
        "keep_index_versions",
        "keep-index-versions",
        "Keep-Index-Versions",
        "KEEP_INDEX_VERSIONS",
    ],
)
def test_option_name_normalization(
    keep_index_versions_key: str,
) -> None:
    content = f"""\
    [mirror]
    directory = /test
    ; any non-default value
    {keep_index_versions_key} = 3
    """
    cfg = load_config_str(content)
    mirror_opts = cfg.get_validated(MirrorConfiguration)
    assert mirror_opts.keep_index_versions == 3


@pytest.mark.parametrize(
    ("directory_value", "expected_diff_file"),
    [
        ("/", "/mirrored-files"),
        ("/opt/mirror", "/opt/mirror/mirrored-files"),
        ("D:\\", "D:\\mirrored-files"),
        ("D:\\mirror\\pypi", "D:\\mirror\\pypi\\mirrored-files"),
    ],
)
def test_default_diff_file(
    directory_value: str,
    expected_diff_file: str,
) -> None:
    content = f"""\
    [mirror]
    directory = {directory_value}
    """
    manager = load_config_str(content)
    mirror_opts = manager.get_validated(MirrorConfiguration)
    assert mirror_opts.diff_file == str(Path(expected_diff_file))


def test_diff_file_interpolation() -> None:
    content = """\
    [test]
    example = /opt/mirror

    [mirror]
    directory = ${test:example}
    diff-file = ${directory}/diff.txt
    """
    cfg = load_config_str(content)
    mirror_opts = cfg.get_validated(MirrorConfiguration)
    assert mirror_opts.diff_file == "/opt/mirror/diff.txt"


def test_diff_file_legacy_ref() -> None:
    content = """\
    [test]
    example = /var/log

    [mirror]
    directory = /test
    diff-file = {{ test_example }}/bandersnatch
    """
    cfg = load_config_str(content)
    mirror_opts = cfg.get_validated(MirrorConfiguration)
    assert mirror_opts.diff_file == "/var/log/bandersnatch"


@pytest.mark.parametrize(
    ("release_files_option", "expected_root_uri"),
    [
        ("", ""),
        ("release-files = true", ""),
        ("release-files = false", "https://files.pythonhosted.org"),
    ],
)
def test_default_root_uri(
    release_files_option: str,
    expected_root_uri: str,
) -> None:
    config = f"""\
    [mirror]
    directory = /test
    {release_files_option}
    """
    manager = load_config_str(config)
    mirror_opts = manager.get_validated(MirrorConfiguration)
    assert mirror_opts.root_uri == expected_root_uri


def permutate_case(*texts: str) -> Iterable[str]:
    for t in texts:
        yield t
        yield t.upper()
        yield t.capitalize()


@pytest.mark.parametrize(
    ("config_value", "expected"),
    [
        *((v, True) for v in permutate_case("on", "yes", "true")),
        *((v, False) for v in permutate_case("no", "off", "false")),
    ],
)
def test_boolean_conversion(config_value: str, expected: bool) -> None:
    content = f"""\
    [mirror]
    directory = /test
    diff-append-epoch = {config_value}
    """
    manager = load_config_str(content)
    mirror_opts = manager.get_validated(MirrorConfiguration)
    assert mirror_opts.diff_append_epoch == expected


@pytest.mark.parametrize(
    ("timeout_value", "expected_timeout"),
    [
        ("-1", pytest.raises(InvalidValueError)),
        ("0", pytest.raises(InvalidValueError)),
        ("1.9", nullcontext(1.9)),
        ("1000.0", nullcontext(1000.0)),
    ],
)
def test_reject_non_positive_timeouts(
    timeout_value: str, expected_timeout: Any
) -> None:
    content = f"""\
    [mirror]
    directory = /test
    timeout = {timeout_value}
    """
    manager = load_config_str(content)
    with expected_timeout as e:
        mirror_opts = manager.get_validated(MirrorConfiguration)
        assert mirror_opts.timeout == pytest.approx(e)


@pytest.mark.parametrize(
    ("workers_value", "expected_workers"),
    [
        ("-1", pytest.raises(InvalidValueError)),
        ("0", pytest.raises(InvalidValueError)),
        ("1", nullcontext(1)),
        ("10", nullcontext(10)),
        ("11", pytest.raises(InvalidValueError)),
    ],
)
def test_reject_out_of_range_worker_counts(
    workers_value: str, expected_workers: Any
) -> None:
    content = f"""\
    [mirror]
    directory = /test
    workers = {workers_value}
    """
    manager = load_config_str(content)
    with expected_workers as e:
        mirror_opts = manager.get_validated(MirrorConfiguration)
        assert mirror_opts.workers == e


_int_convert_error_pattern = r"can't convert option .+ to expected type 'int'"


@pytest.mark.parametrize(
    ("workers_value", "expected_workers"),
    [
        ("1", nullcontext(1)),
        ("01", nullcontext(1)),
        ("0_1", nullcontext(1)),
        ("1_", pytest.raises(InvalidValueError, match=_int_convert_error_pattern)),
        (
            "fooey",
            pytest.raises(InvalidValueError, match=_int_convert_error_pattern),
        ),
        (
            "no",
            pytest.raises(InvalidValueError, match=_int_convert_error_pattern),
        ),
    ],
)
def test_option_type_conversion(
    workers_value: str,
    expected_workers: Any,
) -> None:
    content = f"""\
    [mirror]
    directory = /test
    workers = {workers_value}
    """
    with expected_workers as e:
        cfg = load_config_str(content)
        mirror_opts = cfg.get_validated(MirrorConfiguration)
        assert mirror_opts.workers == e


@pytest.mark.skipif(
    sys.gettrace() is None, reason="This is only really useful with a breakpoint"
)
@pytest.mark.parametrize(
    "content",
    [
        """\
        [mirror]
        directory =
        """,
        """\
        [mirror]
        directory = /test
        workers = foo
        """,
        """\
        [mirror]
        directory = /test
        timeout = 0
        """,
        """\
        [mirror]
        directory = /test
        release-files = nope
        """,
    ],
)
def test_inspect_error_messages(
    content: str,
) -> None:
    try:
        cfg = load_config_str(content)
        _ = cfg.get_validated(MirrorConfiguration)
        pytest.fail("The statement above this should have thrown an exception")
    except Exception as exc:
        exc_str = str(exc)
        exc_repr = repr(exc)
        print(exc_str, exc_repr, sep="\n", end="\n\n")


@attrs.frozen
class OptionMapping:
    original_name: str
    updated_name: str | None = None
    converter: Callable[[Any], Any] | None = None

    def assert_same(self, original_options: Any, updated_options: Any) -> None:
        name_in_original = self.original_name
        original_value = getattr(original_options, name_in_original)

        name_in_updated = self.updated_name or name_in_original
        updated_value = getattr(updated_options, name_in_updated)

        if self.converter:
            original_value = self.converter(original_value)

        rep = f"<original>.{name_in_original} ~ <updated>.{name_in_updated}"
        assert original_value == updated_value, rep


# Compare refactored MirrorConfiguration interface to the original SetConfigValues
# interface - values should be identical, +/- slightly different field names or a
# straightforward type change.
# In fancy v&v speak this is using the original implementation as a "test oracle" for
# the new implementation.
def test_new_same_as_original(tmp_path: Path) -> None:
    # create a configuration file to read from
    content = """\
    [mirror]
    directory = /src/pypi
    storage-backend = filesystem
    master = https://pypi.org
    release-files = yes
    json = no
    simple-format = HTML
    hash-index = no
    timeout = 20
    workers = 2
    verifiers = 4
    stop-on-error = no
    diff-file = {{mirror_directory}}/new-files.txt
    compare-method = stat
    """
    config_path = tmp_path / "test.conf"
    config_path.write_text(content)
    # explicitly reset singletons
    og.BandersnatchConfig._instances = {}
    # read config with original config manager
    oracle = og.BandersnatchConfig(config_file=config_path.as_posix())
    oracle_opts = og.validate_config_values(oracle.config)
    # read config with new config manager
    sut = BandersnatchConfig()
    sut.load_user_config(config_path)
    sut_opts = sut.get_validated(MirrorConfiguration)

    option_mappings = [
        OptionMapping("storage_backend_name"),
        OptionMapping("root_uri"),
        OptionMapping("simple_format"),
        OptionMapping("diff_append_epoch"),
        OptionMapping("cleanup"),
        OptionMapping("json_save", "save_json"),
        OptionMapping("release_files_save", "save_release_files"),
        OptionMapping("diff_file_path", "diff_file"),
        # str -> str | None
        OptionMapping(
            "download_mirror",
            "download_mirror_url",
            lambda url: url if len(url) > 0 else None,
        ),
        # str -> SimpleDigest
        OptionMapping("digest_name", None, SimpleDigest),
        # str -> ComparisonMethod
        OptionMapping("compare_method", None, ComparisonMethod),
        # str -> Path
    ]

    for opt in option_mappings:
        opt.assert_same(oracle_opts, sut_opts)
