"""label-notify: self-hosted, label-scoped GitHub notifications."""

from .config import Config, ConfigError, Delivery, Rule, load_config
from .cursor import Cursor, CursorError, load, save
from .poller import PollResult, poll_once

__version__ = "0.1.0"

__all__ = [
    "Config",
    "ConfigError",
    "Cursor",
    "CursorError",
    "Delivery",
    "PollResult",
    "Rule",
    "__version__",
    "load",
    "load_config",
    "poll_once",
    "save",
]
