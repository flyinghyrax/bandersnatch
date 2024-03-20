from configparser import ConfigParser, ExtendedInterpolation
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

from typing_extensions import Self


class ConfigModel(Protocol):

    @classmethod
    def from_config_parser(cls, config: ConfigParser) -> Self: ...


class Singleton(type):  # pragma: no cover
    _instances: dict["Singleton", type] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> type:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


def create_config_parser() -> ConfigParser:
    parser = ConfigParser(
        delimiters=("=",),
        interpolation=ExtendedInterpolation(),
    )

    def normalize_option_name(optionstr: str) -> str:
        return optionstr.lower().replace("-", "_")

    # mypy dislikes assignment to methods
    parser.optionxform = normalize_option_name  # type: ignore
    return parser


_C = TypeVar("_C", bound=ConfigModel)


class BandersnatchConfig(metaclass=Singleton):
    def __init__(self, config_parser: ConfigParser | None = None) -> None:
        self.config_parser = (
            config_parser if config_parser is not None else create_config_parser()
        )
        # Cache loaded config objects by name; requesting the same config
        # class more than once should only load and validate once
        self._typed_configs: dict[str, ConfigModel] = {}
        # Track usage of deprecated options, and use a flag to ensure we only
        # display them once per run
        self._found_deprecations: list[str] = []
        self._shown_deprecations = False

    def get_typed(self, model: type[_C]) -> _C:
        name = model.__qualname__
        # not using dict.setdefault b/c that would re-evaluate model.populate every time
        if name not in self._typed_configs:
            self._typed_configs[name] = model.from_config_parser(self.config_parser)
        return cast(_C, self._typed_configs[name])

    def load_file(self, config_file: Path) -> None:
        with config_file.open() as file:
            self.config_parser.read_file(file)
