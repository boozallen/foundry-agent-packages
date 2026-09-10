#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Manual exploratory script: push a query/context past the old 8,192-char bound.

A prior fix addressed a short-circuit where foundry-agent-core's raised
_MAX_QUERY_LEN was silently overridden by unraised duplicate literals in
foundry-agent-fastapi and foundry-strands-agent. This script
drives a query/context sized above the *old* bound through every checkpoint
in the pipeline and reports where (if anywhere) it gets rejected.

Usage:
    uv run python scripts/manual_large_query_test.py [--tokens N] [--marker TEXT]

Example:
    uv run python scripts/manual_large_query_test.py --tokens 32000
    uv run python scripts/manual_large_query_test.py --tokens 500000 --marker "CANARY-42"
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "packages/foundry-agent-core/src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages/foundry-agent-fastapi/src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages/foundry-strands-agent/src"))

from pydantic import ValidationError

from foundry_agent_core import _MAX_DICT_BYTES, _MAX_QUERY_LEN, AgentRequest
from foundry_agent_fastapi.models.requests import QueryAPIRequest
from foundry_strands_agent.config.models import StrandsAgentConfig
from foundry_strands_agent.orchestrator import QueryOrchestrator
from foundry_strands_agent.types import QueryRequest

CHARS_PER_TOKEN = 4  # same ~4:1 approximation used throughout the codebase


_FILLER_SENTENCES = [
    "The quarterly infrastructure review covered capacity planning for the new data center. ",
    "Documentation updates are scheduled for release alongside the next minor version bump. ",
    "The engineering team discussed migration strategies for the legacy billing system. ",
    "Customer feedback indicated a preference for faster response times over new features. ",
    "The onboarding guide was revised to include updated screenshots and clearer steps. ",
    "Weekly standups now include a brief retrospective on completed sprint items. ",
    "The support ticket backlog decreased after the new triage process was adopted. ",
    "A follow-up meeting was scheduled to review the proposed architecture changes. ",
    "The test suite runtime improved after parallelizing the integration test stage. ",
    "Release notes summarized the bug fixes and minor improvements from this cycle. ",
]


def _filler_text(n_chars: int) -> str:
    """Natural-language filler (varied benign sentences, cycled deterministically)
    instead of a raw repeated character run or a single repeated sentence — both
    of which some Bedrock guardrails flag as anomalous/repetitive content."""
    out: list[str] = []
    total = 0
    i = 0
    while total < n_chars:
        sentence = _FILLER_SENTENCES[i % len(_FILLER_SENTENCES)]
        out.append(sentence)
        total += len(sentence)
        i += 1
    return "".join(out)[:n_chars]


def build_query(n_chars: int, marker: str) -> str:
    """Build an n_chars-long query with a marker stuffed in the middle, to prove
    the payload survives byte-for-byte through every layer, not just that the
    length check passes."""
    filler_len = max(0, n_chars - len(marker))
    half = filler_len // 2
    return _filler_text(half) + marker + _filler_text(filler_len - half)


def build_context(n_bytes: int, marker: str) -> dict:
    """Build a context dict whose serialized JSON is roughly n_bytes, with a
    marker value stuffed in."""
    filler_len = max(0, n_bytes - len(marker) - 20)  # ~20 bytes of JSON overhead
    return {"marker": marker, "filler": _filler_text(filler_len)}


def report(step: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {step}"
    if detail:
        line += f" — {detail}"
    print(line)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokens", type=int, default=32_000, help="target query size in tokens (default: 32000)")
    parser.add_argument("--marker", default="CANARY-STUFFED-VALUE", help="marker string to embed and verify intact")
    parser.add_argument(
        "--real-bedrock",
        action="store_true",
        help="also invoke a real Bedrock model (checkpoint 5) instead of stopping after preprocessing",
    )
    parser.add_argument(
        "--model-id",
        default="us.anthropic.claude-sonnet-5",
        help="Bedrock model ID/inference-profile to call with --real-bedrock (default: us.anthropic.claude-sonnet-5)",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region for the Bedrock call (default: us-east-1)")
    args = parser.parse_args()

    n_chars = args.tokens * CHARS_PER_TOKEN
    print(f"Target: {args.tokens:,} tokens (~{n_chars:,} chars, ~{n_chars:,} bytes of context)")
    print(f"Canonical bounds: _MAX_QUERY_LEN={_MAX_QUERY_LEN:,} chars, _MAX_DICT_BYTES={_MAX_DICT_BYTES:,} bytes")
    print("Old bound at every layer was 8,192 chars / 16,384 bytes.")
    print()

    query = build_query(n_chars, args.marker)
    context = build_context(n_chars, args.marker)

    # --- Checkpoint 1: foundry-agent-fastapi HTTP request model ---
    try:
        api_req = QueryAPIRequest(query=query, context=context)
        assert args.marker in api_req.query
        assert api_req.context["marker"] == args.marker
        report("1. QueryAPIRequest (fastapi HTTP entry)", True, f"{len(api_req.query):,} chars accepted")
    except ValidationError as e:
        report("1. QueryAPIRequest (fastapi HTTP entry)", False, str(e)[:200])
        return

    # --- Checkpoint 2: foundry-agent-core domain model ---
    try:
        core_req = AgentRequest(query=api_req.query, context=api_req.context)
        assert args.marker in core_req.query
        report("2. AgentRequest (foundry-agent-core domain model)", True, f"{len(core_req.query):,} chars accepted")
    except ValidationError as e:
        report("2. AgentRequest (foundry-agent-core domain model)", False, str(e)[:200])
        return

    # --- Checkpoint 3: foundry-strands-agent internal QueryRequest ---
    try:
        internal_req = QueryRequest(query=core_req.query, context=core_req.context)
        assert args.marker in internal_req.query
        report("3. QueryRequest (strands internal model)", True, f"{len(internal_req.query):,} chars accepted")
    except ValidationError as e:
        report("3. QueryRequest (strands internal model)", False, str(e)[:200])
        return

    # --- Checkpoint 4: orchestrator runtime max_query_length check ---
    config = MagicMock(spec=StrandsAgentConfig)
    config.max_query_length = _MAX_QUERY_LEN  # operator-configured ceiling, raised to canonical bound
    config.default_similarity_threshold = 0.7
    config.max_response_time_ms = 30_000
    config.structured_output_schemas = {}

    container = MagicMock()
    container.resolve.return_value = config
    orchestrator = QueryOrchestrator(container, MagicMock(), MagicMock(), MagicMock())

    try:
        validated = await orchestrator._preprocess_query(internal_req, "manual-test-query")
        assert args.marker in validated.query
        report(
            "4. orchestrator._preprocess_query (runtime max_query_length check)",
            True,
            f"{len(validated.query):,} chars accepted, marker intact",
        )
    except Exception as e:  # noqa: BLE001 - report whatever QueryProcessingError says
        report("4. orchestrator._preprocess_query (runtime max_query_length check)", False, str(e)[:300])
        return

    print()
    print(f"All 4 checkpoints passed — payload of ~{args.tokens:,} tokens with marker {args.marker!r} survived intact.")

    if not args.real_bedrock:
        return

    # --- Checkpoint 5: real Bedrock model call, no mocking ---
    print()
    print(f"Checkpoint 5: invoking real Bedrock model {args.model_id!r} in {args.region!r} ...")
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(model_id=args.model_id, region_name=args.region, max_tokens=512)
    agent = Agent(
        model=model,
        system_prompt=(
            "You will receive a long document. Somewhere in the middle there is a short "
            "unique code word. Reply with only that code word and nothing else."
        ),
    )

    start = time.time()
    try:
        result = await agent.invoke_async(validated.query)
    except Exception as e:  # noqa: BLE001 - surface whatever Bedrock/boto raises
        report("5. Real Bedrock invoke_async", False, f"{type(e).__name__}: {e}")
        return
    elapsed = time.time() - start

    response_text = str(result)
    marker_found = args.marker in response_text
    report(
        "5. Real Bedrock invoke_async",
        True,
        f"{elapsed:.1f}s, response {len(response_text)} chars, marker echoed back: {marker_found}",
    )
    print()
    print(f"stop_reason: {result.stop_reason}")
    print(f"message: {result.message}")
    print(f"Model response: {response_text[:500]!r}")


if __name__ == "__main__":
    asyncio.run(main())
