"""
Aether Backend — Reward Queue Processor

Async queue for processing eligible rewards.  Once a reward is enqueued the
processor:
    1. Calls the Oracle Signer to generate a cryptographic proof.
    2. Stores the proof alongside the queued reward so the frontend can
       trigger an on-chain claim.
    3. Retries transient failures with exponential back-off.
    4. Moves permanently failed items to a dead-letter store.

All state is held in-memory (dict-backed).  In production, swap for a
durable queue (SQS, Redis Streams, Kafka) and a persistent store
(DynamoDB / PostgreSQL).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from services.oracle.signer import OracleSigner, RewardProof
from shared.common.common import NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics

_env = os.getenv("AETHER_ENV", "local").lower()
if _env not in ("local", "test") and os.getenv("REWARD_REQUIRE_DURABLE_STORE", "false").lower() == "true":
    raise RuntimeError(
        "RewardQueue in-memory implementation is not allowed when "
        "REWARD_REQUIRE_DURABLE_STORE=true in a non-local environment. "
        "Configure a durable queue (Kafka/SQS/Redis Streams) before enabling."
    )

logger = get_logger("aether.service.rewards.queue")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class QueuedReward:
    """
    A reward item moving through the processing pipeline.

    Lifecycle:
        pending -> processing -> proved   (happy path)
                              -> failed   (after max retries; dead-lettered)
        proved  -> claimed                (set externally after on-chain tx)

    Attributes:
        id:               Unique identifier (UUID).
        user_address:     Wallet address of the reward recipient.
        action_type:      The qualifying event type.
        campaign_id:      Originating campaign.
        reward_amount_wei: Reward denominated in wei.
        chain_id:         Target EVM chain.
        status:           Current processing state.
        proof:            Populated after successful oracle signing.
        created_at:       Enqueue timestamp.
        updated_at:       Last state-change timestamp.
        retry_count:      Number of processing attempts so far.
        max_retries:      Ceiling before dead-lettering.
        error:            Last error message (if any).
    """

    id: str
    user_address: str
    action_type: str
    campaign_id: str
    reward_amount_wei: int
    chain_id: int
    status: str = "pending"
    proof: Optional[dict] = None
    created_at: datetime = field(default_factory=lambda: utc_now())
    updated_at: datetime = field(default_factory=lambda: utc_now())
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_address": self.user_address,
            "action_type": self.action_type,
            "campaign_id": self.campaign_id,
            "reward_amount_wei": self.reward_amount_wei,
            "chain_id": self.chain_id,
            "status": self.status,
            "proof": self.proof,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════════
# REWARD QUEUE
# ═══════════════════════════════════════════════════════════════════════════

class RewardQueue:
    """
    In-memory reward processing queue backed by an ``OracleSigner``.

    Stores:
        _pending:       FIFO deque of reward IDs awaiting processing.
        _rewards:       id -> ``QueuedReward``.
        _user_index:    address -> [reward IDs] for fast per-user lookups.
        _dead_letter:   Rewards that exhausted retries.
    """

    BASE_BACKOFF_S = 1.0  # first retry delay

    def __init__(self, oracle_signer: OracleSigner) -> None:
        self._oracle = oracle_signer
        self._pending: deque[str] = deque()
        self._rewards: dict[str, QueuedReward] = {}
        self._user_index: dict[str, list[str]] = {}
        self._dead_letter: list[QueuedReward] = []

    # -- enqueue ---------------------------------------------------------

    async def enqueue(
        self,
        user_address: str,
        action_type: str,
        campaign_id: str,
        reward_amount_wei: int,
        chain_id: int,
    ) -> str:
        """
        Create a new queued reward and place it in the pending queue.

        Returns:
            The generated reward ID.
        """
        reward_id = str(uuid.uuid4())
        reward = QueuedReward(
            id=reward_id,
            user_address=user_address,
            action_type=action_type,
            campaign_id=campaign_id,
            reward_amount_wei=reward_amount_wei,
            chain_id=chain_id,
        )

        self._rewards[reward_id] = reward
        self._pending.append(reward_id)
        self._user_index.setdefault(user_address.lower(), []).append(reward_id)

        logger.info(
            f"Reward enqueued: id={reward_id} user={user_address} "
            f"campaign={campaign_id} amount={reward_amount_wei} wei"
        )
        metrics.increment("rewards_enqueued", labels={"campaign": campaign_id})
        return reward_id

    # -- processing ------------------------------------------------------

    async def process_next(self) -> Optional[QueuedReward]:
        """
        Dequeue and process the next pending reward.

        On success the reward transitions to ``proved`` with the oracle
        proof attached.  On failure the reward is retried up to
        ``max_retries`` times (exponential back-off) before being moved
        to the dead-letter store.
        """
        if not self._pending:
            return None

        reward_id = self._pending.popleft()
        reward = self._rewards.get(reward_id)
        if reward is None:
            return None

        reward.status = "processing"
        reward.updated_at = utc_now()

        try:
            proof: RewardProof = await self._oracle.generate_proof(
                user=reward.user_address,
                action_type=reward.action_type,
                amount_wei=reward.reward_amount_wei,
            )
            reward.proof = proof.to_dict()
            reward.status = "proved"
            reward.error = None
            reward.updated_at = utc_now()

            logger.info(f"Reward proved: id={reward_id} user={reward.user_address}")
            metrics.increment("rewards_proved", labels={"campaign": reward.campaign_id})

        except Exception as exc:
            reward.retry_count += 1
            reward.error = str(exc)
            reward.updated_at = utc_now()

            if reward.retry_count >= reward.max_retries:
                reward.status = "failed"
                self._dead_letter.append(reward)
                logger.error(
                    f"Reward dead-lettered: id={reward_id} error={exc} "
                    f"retries={reward.retry_count}"
                )
                metrics.increment("rewards_dead_lettered", labels={"campaign": reward.campaign_id})
            else:
                # Re-enqueue with back-off
                backoff = self.BASE_BACKOFF_S * (2 ** (reward.retry_count - 1))
                logger.warning(
                    f"Reward processing failed, retrying: id={reward_id} "
                    f"attempt={reward.retry_count}/{reward.max_retries} "
                    f"backoff={backoff}s error={exc}"
                )
                await asyncio.sleep(backoff)
                reward.status = "pending"
                self._pending.append(reward_id)

        return reward

    async def process_all(self) -> list[QueuedReward]:
        """Process every pending reward in the queue (in order)."""
        results: list[QueuedReward] = []
        while self._pending:
            result = await self.process_next()
            if result is not None:
                results.append(result)
        return results

    # -- queries ---------------------------------------------------------

    def get_reward(self, reward_id: str) -> QueuedReward:
        """Retrieve a reward by ID or raise ``NotFoundError``."""
        reward = self._rewards.get(reward_id)
        if reward is None:
            raise NotFoundError("Reward")
        return reward

    def get_user_rewards(self, address: str) -> list[QueuedReward]:
        """Return all rewards (any status) for a wallet address."""
        ids = self._user_index.get(address.lower(), [])
        return [self._rewards[rid] for rid in ids if rid in self._rewards]

    def get_pending_count(self) -> int:
        return len(self._pending)

    def get_stats(self) -> dict:
        """Aggregate queue statistics."""
        statuses: dict[str, int] = {}
        total_wei = 0
        for reward in self._rewards.values():
            statuses[reward.status] = statuses.get(reward.status, 0) + 1
            total_wei += reward.reward_amount_wei

        return {
            "total_rewards": len(self._rewards),
            "pending": self.get_pending_count(),
            "statuses": statuses,
            "dead_letter_count": len(self._dead_letter),
            "total_reward_wei": total_wei,
            "unique_users": len(self._user_index),
        }
