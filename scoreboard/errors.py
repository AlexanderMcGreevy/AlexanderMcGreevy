"""Error types shared across the scoreboard package.

Messages must never contain tokens, repo names, or other account detail.
"""


class TransientError(Exception):
    """A failure worth retrying (rate limit, 5xx, network trouble)."""


class PersistentError(Exception):
    """A failure that retrying will not fix (bad token, missing scope)."""
