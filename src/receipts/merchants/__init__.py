"""Merchant identity: recognise a merchant, and remember what it is called.

`registry` is the only module in the codebase that writes the `merchants`
table. Nothing here trusts a pre-extraction guess: a guess may retrieve a
merchant, but only an extracted `tax_id` may create or rename one.
"""

from .registry import lookup

__all__ = ["lookup"]
