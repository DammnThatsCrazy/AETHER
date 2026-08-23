"""SynthesisService — public facade for grounded synthesis (ADR-008 D6, Commit 9).

The ``synthesis`` package is the answering path of the provider-neutral model
runtime. ``SynthesisService`` is the one-call entry point the API layer
consumes. It wires the engine (:class:`GroundedSynthesisEngine`) -> the
renderer (:class:`SynthesisRenderer`) into two methods:

* ``synthesize`` — async; run the grounded-synthesis pipeline with a
  caller-supplied :class:`Synthesizer` and return a :class:`SynthesisResult`.
* ``synthesize_rendered`` — async; run the pipeline and render the result as
  bounded, secret-free markdown (optionally truncating the content section).

Security posture: callers supply a :class:`Synthesizer`; Aether executes all
model calls. Every engine/render failure is normalized into a SHORT,
content-free :class:`SynthesisServiceError` (the underlying exception is
chained via ``__cause__`` for diagnostics) so the facade never surfaces prompt
content, evidence content, or secret-shaped material in the raised message,
and it never logs anything at all.
"""

from __future__ import annotations

from services.model_runtime.synthesis.engine import (
    GroundedSynthesisEngine,
    Synthesizer,
)
from services.model_runtime.synthesis.models import (
    SynthesisRequest,
    SynthesisResult,
)
from services.model_runtime.synthesis.renderer import (
    SynthesisRenderError,
    SynthesisRenderer,
)

__all__ = ["SynthesisService", "SynthesisServiceError"]


def _wrap(err: Exception) -> SynthesisServiceError:
    """Build a short, content-free service error from an underlying failure.

    Only the exception type name is surfaced: the original message may quote
    prompt/evidence content or a credential marker, so it is never copied into
    the facade's error string.
    """
    return SynthesisServiceError(f"synthesis failed closed: {type(err).__name__}")


class SynthesisServiceError(Exception):
    """Raised when grounded synthesis fails closed at any stage.

    Messages are intentionally short and carry NO prompt content, evidence
    content, or secret-shaped material. The underlying exception is preserved
    as ``__cause__`` for diagnostics; the surfaced message names only the
    failure class.
    """


class SynthesisService:
    """Provider-neutral facade. Callers supply a Synthesizer; Aether executes model calls.

    Components are injectable for testing; defaults compose the canonical
    grounded-synthesis engine (:class:`GroundedSynthesisEngine`) and renderer
    (:class:`SynthesisRenderer`).
    """

    def __init__(
        self,
        *,
        engine: GroundedSynthesisEngine | None = None,
        renderer: SynthesisRenderer | None = None,
    ) -> None:
        self._engine = engine if engine is not None else GroundedSynthesisEngine()
        self._renderer = renderer if renderer is not None else SynthesisRenderer()

    async def synthesize(
        self, request: SynthesisRequest, synthesizer: Synthesizer
    ) -> SynthesisResult:
        """Run the grounded-synthesis pipeline and return the result.

        EVERY engine failure — a fail-closed gate (grounding, plan allowlist,
        prompt guard, model-answer checks) OR an unexpected engine/synthesizer
        exception — is normalized into a short, content-free
        :class:`SynthesisServiceError`. Raw exceptions never cross the public
        facade, so callers get one consistent error contract.

        The facade never logs content or credentials, and never surfaces them
        in the raised message.
        """
        try:
            return await self._engine.run(request, synthesizer)
        except Exception as err:
            raise _wrap(err) from err

    async def synthesize_rendered(
        self,
        request: SynthesisRequest,
        synthesizer: Synthesizer,
        *,
        limit: int | None = None,
    ) -> str:
        """Run the pipeline and render the result as grounded markdown.

        ``engine.run`` -> ``renderer.render`` when ``limit`` is ``None``, or
        ``renderer.render_truncated`` when a ``limit`` is given. Render
        failures (``SynthesisRenderError``) are wrapped into the same short,
        content-free :class:`SynthesisServiceError`.
        """
        result = await self.synthesize(request, synthesizer)
        try:
            if limit is not None:
                return self._renderer.render_truncated(result, limit)
            return self._renderer.render(result)
        except SynthesisRenderError as err:
            raise _wrap(err) from err
