"""Pattern Discovery & Unstructured Evidence Intelligence.

A governed discovery plane that sits *beside* the canonical graph, never inside
it. It reads raw and semi-structured evidence (analytics events with arbitrary
``properties`` payloads, free-text fields such as error messages, notes and
agent transcripts, and optional graph edges), interprets it schema-on-read into
*candidate* observations, mines patterns that were never defined in advance,
and emits versioned, evidence-backed :data:`pattern candidates <contracts>`.

Pipeline::

    raw evidence
      -> extraction (schema-on-read, PII hashed)        extraction.py
      -> event frame + field profiles                   engine.py
      -> baselines (tenant history, decayed)            baselines.py
      -> unknown-pattern detectors                      detectors/
      -> cross-domain correlation                       detectors/cross_domain.py
      -> scoring + analyst-feedback calibration         scoring.py
      -> pattern registry (versioned lifecycle)         registry.py
      -> human review -> promotion (Risk360 signals)    service.py / projections.py

Non-negotiable rules (enforced in code and tests):

* Extraction is never truth: every candidate observation is ``inferred`` and
  carries its extractor and confidence.
* A discovered pattern never merges identities, never marks an agent malicious,
  never denies a transaction and never writes canonical graph facts.
* Confidence is capped per pattern kind; only a human verdict moves a pattern
  out of the candidate funnel, and a verdict is valid only for the evidence it
  was made on (evidence fingerprint).
* Promotion is an explicit reviewer action and produces *attributed* Risk360
  signals, never ``verified`` ones.
"""
