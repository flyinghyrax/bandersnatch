import logging
import re
from re import Pattern
from typing import Any

from bandersnatch.filter import FilterProjectPlugin, FilterReleasePlugin

app_logger = logging.getLogger("bandersnatch")


class RegexReleaseFilter(FilterReleasePlugin):
    """
    Filters releases based on regex patters defined by the user.
    """

    name = "regex_release"
    # Has to be iterable to ensure it works with any()
    patterns: list[Pattern] = []

    def initialize_plugin(self) -> None:
        """
        Initialize the plugin reading patterns from the config.
        """
        # TODO: should retrieving the plugin's config be part of the base class?
        try:
            config = self.configuration["filter_regex"]["releases"]
        except KeyError:
            return
        else:
            if not self.patterns:
                pattern_strings = [pattern for pattern in config.split("\n") if pattern]
                self.patterns = [
                    re.compile(pattern_string) for pattern_string in pattern_strings
                ]

                app_logger.info(
                    f"Initialized regex release plugin with {self.patterns}"
                )

    def filter(self, metadata: dict) -> bool:
        """
        Returns False if version fails the filter, i.e. follows a regex pattern
        """
        version = metadata["version"]
        for pattern in self.patterns:
            if pattern.match(version):
                self.filter_logger.info(
                    "Rejecting: release %s==%s version matches pattern %r",
                    metadata["info"]["name"],
                    version,
                    pattern.pattern,
                )
                return False
        return True


class RegexProjectFilter(FilterProjectPlugin):
    """
    Filters projects based on regex patters defined by the user.
    """

    name = "regex_project"
    # Has to be iterable to ensure it works with any()
    patterns: list[Pattern] = []

    def initialize_plugin(self) -> None:
        """
        Initialize the plugin reading patterns from the config.
        """
        try:
            config = self.configuration["filter_regex"]["packages"]
        except KeyError:
            return
        else:
            if not self.patterns:
                pattern_strings = [pattern for pattern in config.split("\n") if pattern]
                self.patterns = [
                    re.compile(pattern_string) for pattern_string in pattern_strings
                ]
                app_logger.info(
                    f"Initialized regex release plugin with {self.patterns}"
                )

    def filter(self, metadata: dict) -> bool:
        return not self.check_match(name=metadata["info"]["name"])

    def check_match(self, **kwargs: Any) -> bool:
        """
        Check if a release version matches any of the specified patterns.

        Parameters
        ==========
        name: str
            Release name

        Returns
        =======
        bool:
            True if it matches, False otherwise.
        """
        if "name" not in kwargs:
            raise ValueError(
                "No name argument supplied to RegexProjectFilter.check_match"
            )
        name = kwargs["name"]
        for pattern in self.patterns:
            if pattern.match(name):
                self.filter_logger.info(
                    "Rejecting: project name %s matches pattern %r",
                    name,
                    pattern.pattern,
                )
                return True
        return False
