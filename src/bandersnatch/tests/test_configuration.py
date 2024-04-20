import configparser
import importlib.resources
import os
import unittest
from tempfile import TemporaryDirectory
from unittest import TestCase

from bandersnatch.config.diff_file_reference import eval_legacy_config_ref
from bandersnatch.configuration import (
    BandersnatchConfig,
    SetConfigValues,
    validate_config_values,
)
from bandersnatch.simple import SimpleFormat


class TestBandersnatchConf(TestCase):
    """
    Tests for the BandersnatchConf singleton class
    """

    tempdir = None
    cwd = None

    def setUp(self) -> None:
        self.cwd = os.getcwd()
        self.tempdir = TemporaryDirectory()
        os.chdir(self.tempdir.name)

    def tearDown(self) -> None:
        if self.tempdir:
            assert self.cwd
            os.chdir(self.cwd)
            self.tempdir.cleanup()
            self.tempdir = None

    def test_single_config__default__all_sections_present(self) -> None:
        config_content = (
            importlib.resources.files("bandersnatch") / "unittest.conf"
        ).read_text()
        instance = BandersnatchConfig()
        instance.read_string(config_content)
        # All default values should at least be present and be the write types
        for section in ["mirror", "plugins", "blocklist"]:
            self.assertIn(section, instance.sections())

    def test_single_config__default__mirror__setting_attributes(self) -> None:
        instance = BandersnatchConfig()
        instance.read_defaults_file()
        options = [option for option in instance["mirror"]]
        options.sort()
        self.assertListEqual(
            options,
            [
                "cleanup",
                "compare_method",
                "directory",
                "global_timeout",
                "hash_index",
                "json",
                "master",
                "release_files",
                "simple_format",
                "stop_on_error",
                "storage_backend",
                "timeout",
                "verifiers",
                "workers",
            ],
        )

    def test_single_config__default__mirror__setting__types(self) -> None:
        """
        Make sure all default mirror settings will cast to the correct types
        """
        instance = BandersnatchConfig()
        instance.read_defaults_file()
        for option, option_type in [
            ("directory", str),
            ("hash-index", bool),
            ("json", bool),
            ("master", str),
            ("stop-on-error", bool),
            ("storage-backend", str),
            ("timeout", int),
            ("global-timeout", int),
            ("workers", int),
            ("compare-method", str),
        ]:
            self.assertIsInstance(
                option_type(instance["mirror"].get(option)), option_type
            )

    def test_single_config_custom_setting_boolean(self) -> None:
        with open("test.conf", "w") as testconfig_handle:
            testconfig_handle.write("[mirror]\nhash-index=false\n")
        instance = BandersnatchConfig.from_path("test.conf", with_defaults=False)
        self.assertFalse(instance["mirror"].getboolean("hash-index"))

    def test_single_config_custom_setting_int(self) -> None:
        with open("test.conf", "w") as testconfig_handle:
            testconfig_handle.write("[mirror]\ntimeout=999\n")
        instance = BandersnatchConfig.from_path("test.conf", with_defaults=False)
        self.assertEqual(int(instance["mirror"]["timeout"]), 999)

    def test_single_config_custom_setting_str(self) -> None:
        with open("test.conf", "w") as testconfig_handle:
            testconfig_handle.write("[mirror]\nmaster=https://foo.bar.baz\n")
        instance = BandersnatchConfig.from_path("test.conf", with_defaults=False)
        self.assertEqual(instance["mirror"]["master"], "https://foo.bar.baz")

    def test_validate_config_values(self) -> None:
        default_values = SetConfigValues(
            False,
            "",
            "",
            False,
            "sha256",
            "filesystem",
            False,
            True,
            "hash",
            "",
            False,
            SimpleFormat.ALL,
        )
        no_options_configparser = configparser.ConfigParser()
        no_options_configparser["mirror"] = {}
        self.assertEqual(
            default_values, validate_config_values(no_options_configparser)
        )

    def test_validate_config_values_release_files_false_sets_root_uri(self) -> None:
        default_values = SetConfigValues(
            False,
            "https://files.pythonhosted.org",
            "",
            False,
            "sha256",
            "filesystem",
            False,
            False,
            "hash",
            "",
            False,
            SimpleFormat.ALL,
        )
        release_files_false_configparser = configparser.ConfigParser()
        release_files_false_configparser["mirror"] = {"release-files": "false"}
        self.assertEqual(
            default_values, validate_config_values(release_files_false_configparser)
        )

    def test_validate_config_values_download_mirror_false_sets_no_fallback(
        self,
    ) -> None:
        default_values = SetConfigValues(
            False,
            "",
            "",
            False,
            "sha256",
            "filesystem",
            False,
            True,
            "hash",
            "",
            False,
            SimpleFormat.ALL,
        )
        release_files_false_configparser = configparser.ConfigParser()
        release_files_false_configparser["mirror"] = {
            "download-mirror-no-fallback": "true",
        }
        self.assertEqual(
            default_values, validate_config_values(release_files_false_configparser)
        )

    def test_validate_config_diff_file_reference(self) -> None:
        diff_file_test_cases = [
            (
                {
                    "mirror": {
                        "directory": "/test",
                        "diff-file": r"{{mirror_directory}}",
                    }
                },
                "/test",
            ),
            (
                {
                    "mirror": {
                        "directory": "/test",
                        "diff-file": r"{{ mirror_directory }}",
                    }
                },
                "/test",
            ),
            (
                {
                    "mirror": {
                        "directory": "/test",
                        "diff-file": r"{{ mirror_directory }}/diffs/new-files",
                    }
                },
                "/test/diffs/new-files",
            ),
            (
                {
                    "strings": {"test": "TESTING"},
                    "mirror": {"diff-file": r"/var/log/{{ strings_test }}"},
                },
                "/var/log/TESTING",
            ),
            (
                {
                    "strings": {"test": "TESTING"},
                    "mirror": {"diff-file": r"/var/log/{{ strings_test }}/diffs"},
                },
                "/var/log/TESTING/diffs",
            ),
        ]

        for cfg_data, expected in diff_file_test_cases:
            with self.subTest(
                diff_file=cfg_data["mirror"]["diff-file"],
                expected=expected,
                cfg_data=cfg_data,
            ):
                cfg = configparser.ConfigParser()
                cfg.read_dict(cfg_data)
                config_values = validate_config_values(cfg)
                self.assertIsInstance(config_values.diff_file_path, str)
                self.assertEqual(config_values.diff_file_path, expected)

    def test_invalid_diff_file_reference_throws_exception(self) -> None:
        invalid_diff_file_cases = [
            (
                r"{{ missing.underscore }}/foo",
                "Unable to parse config option reference",
            ),
            (r"/var/{{ mirror_woops }}/foo", "No option 'woops' in section: 'mirror'"),
        ]

        for diff_file_val, expected_error in invalid_diff_file_cases:
            with self.subTest(diff_file=diff_file_val, expected_error=expected_error):
                cfg = configparser.ConfigParser()
                cfg.read_dict({"mirror": {"diff-file": diff_file_val}})
                self.assertRaisesRegex(
                    ValueError,
                    expected_error,
                    eval_legacy_config_ref,
                    cfg,
                    diff_file_val,
                )


if __name__ == "__main__":
    unittest.main()
