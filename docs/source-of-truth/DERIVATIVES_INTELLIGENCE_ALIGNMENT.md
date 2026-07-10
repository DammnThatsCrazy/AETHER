---
title: Derivatives Intelligence Alignment
status: draft
owner: derivatives-intelligence
source: Backend Architecture/aether-backend/services/derivatives/intelligence.py
---

# Derivatives Intelligence Alignment

Derivatives intelligence projects normalized trading facts into existing Aether graph, Profile360, Campaign360, journey, and Noesis systems without creating a second graph client, identity system, journey compiler, or campaign registry.

All projection intents are tenant-scoped, idempotent, bitemporal, evidence-backed, and observational (`execution_by_aether = false`). Actor relationship edges are explicitly classified as H2H, H2A, A2H, or A2A. Market-domain edges such as `HOLDS_POSITION`, `ON_MARKET`, and `GENERATED_PNL` are deliberately marked `DOMAIN_EXCLUDED` so they remain queryable in the universal graph without being mislabeled as actor-layer relationships.

Campaign outcome claims keep temporal sequence, attribution credit, causal support, and economic outcome as separate fields. Noesis derivatives answers classify each claim as fact, computation, inference, recommendation, or insufficient evidence.
