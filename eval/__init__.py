"""Offline evaluation for the extraction pipeline (spec §16).

`metrics` holds the pure per-receipt comparisons (field accuracy, line-item F1,
critical-field gate, calibration curve); `harness` walks a golden set and
aggregates them into an :class:`~eval.metrics.EvalReport`. Nothing here touches
the network or requires real images — the pipeline is injected as a callable.
"""
