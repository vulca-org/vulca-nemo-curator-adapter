from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Iterable, Optional, Type, Union

from pydantic import BaseModel


PlainObject = Union[BaseModel, dict]


def _to_plain_object(item: PlainObject) -> dict:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def write_jsonl(path: Path, items: Iterable[PlainObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(_to_plain_object(item), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


class JsonlStreamWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def __enter__(self) -> "JsonlStreamWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def write(self, item: PlainObject) -> None:
        if self._handle is None:
            raise RuntimeError("JsonlStreamWriter must be used as a context manager")
        self._handle.write(json.dumps(_to_plain_object(item), ensure_ascii=False, sort_keys=True))
        self._handle.write("\n")
