#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Manual exploratory script: verify temperature actually reaches an open model on Bedrock.

A prior fix addressed _default_bedrock_model not passing the configured
temperature to BedrockModel, with a guard that omits temperature for Claude
model families known to reject it (see factory.py's
_BEDROCK_TEMPERATURE_REJECTING_MODEL_SUBSTRINGS). The unit tests mock
BedrockModel and only assert on constructor kwargs; they can't prove
temperature actually changes real model behavior. This script drives
_default_bedrock_model exactly as the factory does, then makes real Bedrock
calls: the same prompt, repeated, at temperature=0.0 (expect identical
responses) and at temperature=1.0 (expect at least one different response).
A model that ignores temperature (or a regression that silently drops it
again) would show identical output at both settings.

Target models (both ON_DEMAND-only on Bedrock, no "us."-prefixed cross-region
inference profile -- confirmed against real Bedrock, see
gng-eval-harness/examples/agent_eval.{nemotron,gpt-oss}-repeat.yaml):
    nvidia.nemotron-super-3-120b
    openai.gpt-oss-120b-1:0

Usage:
    uv run python scripts/manual_bedrock_temperature_variance_test.py
    uv run python scripts/manual_bedrock_temperature_variance_test.py --model-id openai.gpt-oss-120b-1:0
    uv run python scripts/manual_bedrock_temperature_variance_test.py --repeats 3
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages/foundry-agent-core/src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages/foundry-strands-agent/src"))

from foundry_strands_agent.factory import _default_bedrock_model

DEFAULT_MODEL_IDS = ["nvidia.nemotron-super-3-120b", "openai.gpt-oss-120b-1:0"]

# Open-ended enough that sampling at temperature=1.0 has real room to vary,
# while a deterministic (temperature=0.0) decode should keep picking the same
# top-probability tokens run over run.
PROMPT = "Give me one interesting fact about the ocean. Answer in a single sentence."


def report(step: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {step}"
    if detail:
        line += f" — {detail}"
    print(line)


async def _invoke_once(model_id: str, temperature: float) -> str:
    from strands import Agent

    config = {"model": {"model_id": model_id, "temperature": temperature}}
    # _default_bedrock_model has no region parameter - BedrockModel resolves region from
    # AWS_REGION/boto3 session, same as the factory does in production. --region only informs
    # what this script prints; set AWS_REGION in the environment to actually change it.
    model = _default_bedrock_model(config)

    # Sanity check the guard didn't silently drop temperature for this model_id
    # (both target models are open models, not in the Claude reject-set) —
    # catches a regression in _bedrock_model_rejects_temperature itself before
    # spending an API call on it.
    actual_temperature = model.get_config().get("temperature")
    if actual_temperature != temperature:
        raise AssertionError(
            f"expected temperature={temperature} to reach BedrockModel for {model_id!r}, "
            f"got {actual_temperature!r} — the reject-set may be matching this model_id incorrectly"
        )

    agent = Agent(model=model)
    result = await agent.invoke_async(PROMPT)
    return str(result).strip()


async def run_for_model(model_id: str, repeats: int) -> bool:
    print(f"\n=== {model_id} ===")
    all_ok = True

    for temperature, expect_variation in ((0.0, False), (1.0, True)):
        print(f"\ntemperature={temperature} ({'expect variation' if expect_variation else 'expect identical'}), {repeats} repeats:")
        responses: list[str] = []
        for i in range(repeats):
            start = time.time()
            try:
                text = await _invoke_once(model_id, temperature)
            except Exception as e:  # noqa: BLE001 - surface whatever Bedrock/boto raises
                report(f"  call {i + 1}/{repeats}", False, f"{type(e).__name__}: {e}")
                all_ok = False
                responses.append(None)
                continue
            elapsed = time.time() - start
            responses.append(text)
            print(f"  [{i + 1}/{repeats}] ({elapsed:.1f}s) {text[:150]!r}")

        valid = [r for r in responses if r is not None]
        if len(valid) < 2:
            report(f"temperature={temperature} variation check", False, "fewer than 2 successful calls, can't compare")
            all_ok = False
            continue

        varies = len(set(valid)) > 1
        if expect_variation:
            ok = varies
            detail = "responses varied across repeats" if varies else "all repeats were identical — temperature may not be reaching the model"
        else:
            ok = not varies
            detail = "all repeats identical" if not varies else "responses varied — unexpected at temperature=0.0"
        report(f"temperature={temperature} variation check", ok, detail)
        all_ok = all_ok and ok

    return all_ok


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model-id",
        action="append",
        dest="model_ids",
        help=f"Bedrock model_id to test (repeatable). Default: both of {DEFAULT_MODEL_IDS}",
    )
    parser.add_argument("--repeats", type=int, default=3, help="calls per temperature setting (default: 3)")
    args = parser.parse_args()

    model_ids = args.model_ids or DEFAULT_MODEL_IDS

    print(f"Prompt: {PROMPT!r}")
    print(f"Repeats per temperature: {args.repeats}")
    print("Region: resolved from AWS_REGION / boto3 session, same as _default_bedrock_model in production")

    all_ok = True
    for model_id in model_ids:
        ok = await run_for_model(model_id, args.repeats)
        all_ok = all_ok and ok

    print()
    report("Overall", all_ok)


if __name__ == "__main__":
    asyncio.run(main())
