"""Exceptions related to reading the configuration file.

The error messages generated by factory methods are intended to be user-consumable,
and always include a config section name and option name in the error message.
"""


class ConfigurationError(Exception):
    """An error reading or validating the configuration file"""

    pass


class MissingRequiredOptionError(ConfigurationError):
    """No value was found for a required option"""

    @classmethod
    def for_option(
        cls, section_name: str, option_name: str
    ) -> "MissingRequiredOptionError":
        return cls(
            f"Config section '[{section_name}]' missing required option '{option_name}'"
        )


class OptionValidationError(ConfigurationError):
    """The value given for an option was not valid"""

    @classmethod
    def for_option(
        cls, section_name: str, option_name: str, problem: str
    ) -> "OptionValidationError":
        msg = f"Config section '[{section_name}]' option '{option_name}': {problem}"
        return cls(msg)

    @classmethod
    def must_not_be_empty(
        cls, section_name: str, option_name: str
    ) -> "OptionValidationError":
        return cls.for_option(section_name, option_name, "must have a value")

    @classmethod
    def must_be_convertible(
        cls, section_name: str, option_name: str, target_type: str
    ) -> "OptionValidationError":
        return cls.for_option(
            section_name, option_name, f"must be convertible to {target_type}"
        )
