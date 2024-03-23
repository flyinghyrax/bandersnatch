from collections.abc import Callable
from typing import Any, TypeAlias, TypeVar

from attrs import Attribute, validators

# function compatible with 'converter' argument of 'attrs.field'
_AttrConverter: TypeAlias = Callable[[Any], Any]

# function compatible with the 'validator' argument of 'attrs.field'
_V = TypeVar("_V")
_AttrValidator: TypeAlias = Callable[[Any, Attribute, _V], _V]

# shorter, clearer (imo) alias for 'validators.min_len(1)'
not_empty: _AttrValidator = validators.min_len(1)


# Needed because attrs field default values are passed to attrs field converters.
# This wraps a converter so it isn't applied when the default value isn't a string.
def if_str(conv: _AttrConverter) -> _AttrConverter:
    def convert_if_str(value: Any) -> Any:
        if isinstance(value, str):
            return conv(value)
        else:
            return value

    return convert_if_str
