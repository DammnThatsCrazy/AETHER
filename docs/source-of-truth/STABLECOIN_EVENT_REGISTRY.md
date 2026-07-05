# Stablecoin Event Registry

Stablecoin events preserve raw observation facts separately from derived classification. PR1 defines the canonical event taxonomy in `services/stablecoins/models.py` and the SDK parity contract in `packages/shared/stablecoin.ts`.

Finalized payment volume may only include `finalized` observations. Pending, failed, dropped, disputed, unknown, and reverted observations are excluded from finalized metrics. Reverted observations must be retained as corrections rather than deleted from history.
