"""Small explicit registries; importing a plugin never authorizes a write."""

from .activitywatch import ActivityWatch
from .destinations import CSV, Clockify

SOURCES = {"activitywatch": lambda config: ActivityWatch(config.activitywatch)}
DESTINATIONS = {
    "clockify": lambda config: Clockify(config.destination, config.projects),
    "csv": lambda config: CSV(config.destination, config.timezone),
}
