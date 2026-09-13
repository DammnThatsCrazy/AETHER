"""Relationship Fidelity — shared (pure) layer of milestone M7.

Relationship fidelity is a MULTIDIMENSIONAL vector
(``packages/shared/contracts/relationship-fidelity-vector.schema.json``), never
one universal scalar; this package never reduces it to one. It owns the pure
building blocks at the ``shared`` layer (and therefore never imports from
``services/``):

* ``evidence``     — independent-observation accounting, the declared M6
                     evidence-independence interface, and correlation damping
                     (0.4 discipline);
* ``definitions``  — canonical Computation Definitions registered on the
                     Canonical Computation Substrate (self-register, additive);
* ``scoring``      — transparent per-dimension derivation (unknown is never 0);
* ``vector``       — the schema-conformant :class:`FidelityVector` model and
                     honest assembler.

Orchestration and consume-only persistence live in the sibling service package
``services/relationship_fidelity/``.
"""
