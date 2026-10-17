from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Pattern, Protocol


class UserError(Exception):
    """An actionable error that can be shown without a traceback."""


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Project:
    name: str
    destination_project: str
    description: str
    billable: bool
    rules: dict[str, list[Pattern]] = field(default_factory=dict)
    agreement: dict | None = None


@dataclass
class Event:
    start: datetime
    end: datetime
    data: dict


@dataclass
class Activity:
    windows: list[Event]
    afk: list[Event]
    web: list[Event] = field(default_factory=list)


@dataclass
class Block:
    """Only these approved fields are handed to destinations."""

    start: datetime
    end: datetime
    project: str
    description: str
    billable: bool

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


class Source(Protocol):
    def check(self) -> str: ...
    def fetch(self, start: datetime, end: datetime) -> Activity: ...


class Destination(Protocol):
    def check(self) -> str: ...
    def existing(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...
    def create(self, block: Block) -> None: ...
