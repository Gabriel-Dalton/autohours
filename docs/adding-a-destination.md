# Adding a source or destination

The pipeline knows nothing about HTTP or CSV. `models.Source` and `models.Destination` are small Python protocols. `plugins.py` holds explicit factory registries. autohours ships only ActivityWatch, Clockify and CSV. There is no third-party package discovery or dynamic loading from user config yet; adding a plugin means a small code contribution.

## Destination contract

A destination receives only `Block` objects with `start`, `end`, `project`, `description` and `billable`. Times are timezone-aware UTC. No titles, URLs, regexes or raw events are in a block. `Block.minutes` is computed from elapsed seconds.

Implement:

```python
from datetime import datetime
from autohours.models import Block

class ExampleDestination:
    def check(self) -> str:
        # Validate credentials and resolve configured projects, without writing.
        return "Destination ready."

    def existing(self, start: datetime, end: datetime):
        # Fetch all overlapping intervals, including ones beginning before start.
        # Return list[tuple[datetime, datetime]], using UTC-aware datetimes.
        raise NotImplementedError

    def create(self, block: Block) -> None:
        # Serialize only the destination fields approved in Block.
        raise NotImplementedError
```

Register a factory in `DESTINATIONS` and extend destination validation in `config.py` for the new type and its allowed settings. Add environment-only credentials. The factory receives config so it can resolve project names; never serialize the config or rule patterns. Keep the adapter's outbound payload explicit. Add settings to the commented starter and example together.

`destinations.sync` handles half-open interval overlap checks for all destinations. An existing entry wins if `new.start < old.end and old.start < new.end`. It skips the whole candidate, never edits an existing entry, and invokes `create` only when `write=True`. A running timer should be represented with an open-ended maximum end time. Return every overlapping entry regardless of its project or origin. Paginate remote lists.

Use `UserError` for plain-English fixes. `JsonHTTP` uses urllib, rejects redirects to avoid credential forwarding, retries HTTP 429 a bounded number of times, and does not retry ambiguous network failures during a write. Do not include response bodies or API keys in errors. Test dry runs, pagination, partial failures, overlap boundaries and payload privacy with stubbed HTTP. No real accounts are needed.

## Source contract

Implement `check() -> str` and `fetch(start, end) -> Activity`, register a factory in `SOURCES`, then add the source selection and config validation to the CLI. The CLI currently selects ActivityWatch explicitly because it is the only implemented source.

`Activity` has `windows`, `afk` and optional `web` lists. Each `Event` has UTC-aware start/end and local-only data. Window data uses `app` and `title`; AFK data uses `status = "not-afk"`; web data can contain `title` and `url`. Clip to the requested range, include events crossing the start boundary, and provide active-time evidence. Never infer that missing AFK data means active. A future source with different activity semantics should normalize them here rather than changing destination code.

## Monthly cap accounting

The built-in destinations also implement `logged(start, end) -> list[Block]` to read project-attributed existing time clipped to the requested month range. This is required when a configured project has a monthly cap. Include manual entries regardless of billable status. Clockify uses only the signed-in user's entries. The CLI reserves these totals, skips overlapping candidates before allocating more cap, and shortens or holds back new entries before calling `sync`. Keep evidence and accepted notes out of these objects too. A new destination must support this read before allowing capped writes.
