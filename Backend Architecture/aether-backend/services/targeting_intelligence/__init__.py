"""Cluster Targeting Intelligence — observation-first targeting.

Aether observes whether intended cluster targeting happened, whether it
worked, whether exclusions leaked, and what journey differences emerged.
It never executes campaigns; execution stays in the tenant's external
platforms (``executionByAether`` is hard-false everywhere).
"""
