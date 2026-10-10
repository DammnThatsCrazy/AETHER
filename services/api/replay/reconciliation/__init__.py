"""Reconciliation / data-availability surfaces.

Reports the canonical :class:`~shared.dimension_state.DimensionEnvelope` for a
profile's dimensions so a surface can say honestly why a slice is empty, stale,
or degraded rather than rendering a blank that reads as "no activity".
"""
