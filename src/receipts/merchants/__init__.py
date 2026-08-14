"""Merchant identity: recognise a merchant, and remember what it is called.

`registry` is the only module in the codebase that writes the `merchants`
table. Nothing here trusts a pre-extraction guess: a guess may retrieve a
merchant, but only an extracted `tax_id` may create or rename one.
"""

from .registry import confirm, few_shots_for, increment, lookup, register

__all__ = ["confirm", "few_shots_for", "increment", "lookup", "register"]
