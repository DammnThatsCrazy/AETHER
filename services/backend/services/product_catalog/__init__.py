"""Product Catalog & Instrumentation Registry (Unified Intelligence Plane).

Tenant-scoped catalog of products, product areas, features, surfaces, and
controls, plus deterministic mapping rules that bind raw instrumentation
(routes, selectors, event names, agent tools, ...) to catalog targets.
Flag-gated by ``settings.product_intelligence.catalog_enabled`` — zero
startup cost when off (routes are lazily imported in main.py).
"""
