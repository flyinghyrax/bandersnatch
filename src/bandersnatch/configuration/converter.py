from collections.abc import Callable, Mapping
from typing import Any, ParamSpec, TypeAlias, TypeVar

from attrs import Attribute, validators

# function compatible with 'converter' argument of 'attrs.field'
_AttrConverter: TypeAlias = Callable[[Any], Any]

# function compatible with the 'validator' argument of 'attrs.field'
_V = TypeVar("_V")
_AttrValidator: TypeAlias = Callable[[Any, Attribute, _V], _V]

# function compatible with the 'field_transformer' argument of 'attrs.define'
_AttrFieldTransformer: TypeAlias = Callable[[type, list[Attribute]], list[Attribute]]

# shorter, clearer (imo) alias for 'validators.min_len(1)'
not_empty: _AttrValidator = validators.min_len(1)


_Ps = ParamSpec("_Ps")


def with_message(
    wrapped: Callable[_Ps, Any], msg: str | Callable[[Exception], str]
) -> Callable[_Ps, Any]:
    def wrapper(*args: _Ps.args, **kwargs: _Ps.kwargs) -> Any:
        try:
            return wrapped(*args, **kwargs)
        except ValueError as err:
            msg_ = msg(err) if callable(msg) else msg
            raise ValueError(msg_) from err

    return wrapper


def converter_for_type(t: Any, f: str, inner: _AttrConverter) -> _AttrConverter:
    def convert(v: Any) -> Any:
        try:
            return inner(v)
        except ValueError as err:
            raise ValueError(
                f"can't convert option '{f}' to expected type '{t.__name__}': {err!s}"
            ) from err

    return convert


def convert_by_annotation(
    converters: Mapping[Any, _AttrConverter],
) -> _AttrFieldTransformer:
    def try_add_converter(field: Attribute) -> Attribute:
        if (
            field.converter is None
            and field.type is not None
            and field.type in converters
        ):
            return field.evolve(
                converter=converter_for_type(
                    field.type, field.alias or field.name, converters[field.type]
                )
            )
        else:
            return field

    def transform(_cls: type, fields: list[Attribute]) -> list[Attribute]:
        return [try_add_converter(f) for f in fields]

    return transform


def if_str(conv: _AttrConverter) -> _AttrConverter:
    def convert_if_str(value: Any) -> Any:
        if isinstance(value, str):
            return conv(value)
        else:
            return value

    return convert_if_str
