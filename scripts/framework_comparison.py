"""Exercise 3.4 — Compare RAGAS vs DeepEval on the same 8 cases from the golden
dataset + actual_answers.json artifact. Not part of the required core; this is
a standalone bonus script and is NOT covered by the pytest suite.

Usage:
    python scripts/framework_comparison.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CASE_IDS = ["E01", "E03", "M02", "M06", "H01", "H05", "A01", "A02"]


def load_cases() -> list[dict]:
    golden = json.load(open("golden_dataset.json"))
    actual = json.load(open("artifacts/actual_answers.json"))
    g_by_id = {qa["id"]: qa for qa in golden["qa_pairs"]}
    a_by_id = {a["id"]: a for a in actual["answers"]}

    cases = []
    for cid in CASE_IDS:
        g, a = g_by_id[cid], a_by_id[cid]
        cases.append(
            {
                "id": cid,
                "difficulty": g["difficulty"],
                "question": g["question"],
                "expected_answer": g["expected_answer"],
                "actual_answer": a["actual_answer"],
                "retrieved_contexts": [c["text"] for c in a["retrieved_contexts"]],
            }
        )
    return cases


async def run_ragas(cases: list[dict]) -> dict[str, dict[str, float]]:
    from ragas.llms import llm_factory
    from ragas.embeddings import embedding_factory
    from ragas.metrics.collections import (
        Faithfulness,
        ContextPrecision,
        ContextRecall,
        AnswerRelevancy,
    )
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    llm = llm_factory(model, client=client)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)

    faithfulness = Faithfulness(llm=llm)
    precision = ContextPrecision(llm=llm)
    recall = ContextRecall(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)

    results: dict[str, dict[str, float]] = {}
    for c in cases:
        print(f"[ragas] {c['id']} ...", flush=True)
        try:
            f_res = await faithfulness.ascore(
                user_input=c["question"],
                response=c["actual_answer"],
                retrieved_contexts=c["retrieved_contexts"],
            )
            p_res = await precision.ascore(
                user_input=c["question"],
                reference=c["expected_answer"],
                retrieved_contexts=c["retrieved_contexts"],
            )
            r_res = await recall.ascore(
                user_input=c["question"],
                retrieved_contexts=c["retrieved_contexts"],
                reference=c["expected_answer"],
            )
            rel_res = await relevancy.ascore(
                user_input=c["question"],
                response=c["actual_answer"],
            )
            results[c["id"]] = {
                "faithfulness": float(f_res.value),
                "context_precision": float(p_res.value),
                "context_recall": float(r_res.value),
                "answer_relevancy": float(rel_res.value),
            }
        except Exception as e:  # pragma: no cover - diagnostic path
            results[c["id"]] = {"error": str(e)}
    return results


def run_deepeval(cases: list[dict]) -> dict[str, dict[str, float]]:
    from deepeval.test_case import LLMTestCase
    from deepeval.metrics import (
        FaithfulnessMetric,
        AnswerRelevancyMetric,
        ContextualRecallMetric,
        ContextualPrecisionMetric,
    )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    faithfulness = FaithfulnessMetric(model=model, include_reason=False, async_mode=False)
    relevancy = AnswerRelevancyMetric(model=model, include_reason=False, async_mode=False)
    recall = ContextualRecallMetric(model=model, include_reason=False, async_mode=False)
    precision = ContextualPrecisionMetric(model=model, include_reason=False, async_mode=False)

    results: dict[str, dict[str, float]] = {}
    for c in cases:
        print(f"[deepeval] {c['id']} ...", flush=True)
        tc = LLMTestCase(
            input=c["question"],
            actual_output=c["actual_answer"],
            expected_output=c["expected_answer"],
            context=c["retrieved_contexts"],
            retrieval_context=c["retrieved_contexts"],
        )
        try:
            faithfulness.measure(tc)
            relevancy.measure(tc)
            recall.measure(tc)
            precision.measure(tc)
            results[c["id"]] = {
                "faithfulness": faithfulness.score,
                "answer_relevancy": relevancy.score,
                "context_recall": recall.score,
                "context_precision": precision.score,
            }
        except Exception as e:  # pragma: no cover - diagnostic path
            results[c["id"]] = {"error": str(e)}
    return results


def main() -> None:
    cases = load_cases()

    t0 = time.time()
    ragas_results = asyncio.run(run_ragas(cases))
    ragas_elapsed = time.time() - t0

    t0 = time.time()
    deepeval_results = run_deepeval(cases)
    deepeval_elapsed = time.time() - t0

    out = {
        "cases": {c["id"]: c["difficulty"] for c in cases},
        "ragas": ragas_results,
        "ragas_elapsed_sec": round(ragas_elapsed, 1),
        "deepeval": deepeval_results,
        "deepeval_elapsed_sec": round(deepeval_elapsed, 1),
    }
    Path("artifacts").mkdir(exist_ok=True)
    with open("artifacts/framework_comparison.json", "w") as f:
        json.dump(out, f, indent=2)

    print("\n=== RAGAS ===")
    print(json.dumps(ragas_results, indent=2))
    print(f"elapsed: {ragas_elapsed:.1f}s")
    print("\n=== DeepEval ===")
    print(json.dumps(deepeval_results, indent=2))
    print(f"elapsed: {deepeval_elapsed:.1f}s")


if __name__ == "__main__":
    main()
