"""Retrieval evaluation on the golden set, with no LLM involved.

For questions with expected passages: Recall@k (share of expected chunks retrieved) and MRR.
For questions that should retrieve nothing (access-denied, unanswerable, ambiguous): how often
retrieval correctly comes back empty. For every question: leaks of forbidden documents
(restricted or expired files listed under negative_examples).

    python eval_retrieval.py                         # stage-1 and stage-2 metrics + threshold sweep
    python eval_retrieval.py --include-expired       # adversarial run (index must include expired docs)
"""
import argparse
import csv
import json
from datetime import date
from pathlib import Path

import config
from ingest import slugify
from retriever import HybridRetriever

GOLDEN = config.PROJECT_DIR / "evaluation" / "golden_50.json"
OUT = config.PROJECT_DIR / "evaluation" / "retrieval_results.csv"
RAW = config.PROJECT_DIR / "evaluation" / "retrieval_raw.json"  # every candidate's scores, for offline analysis
EVAL_DATE = date(2026, 10, 18)  # fixed evaluation date from the README, for repeatable runs
THRESHOLDS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1]


def chunk_id(source_uri: str, heading: str) -> str:
    return f"{Path(source_uri).stem}#{slugify(heading)}"


def metrics(expected: set[str], retrieved: list[str]) -> tuple[float, float]:
    recall = len(expected & set(retrieved)) / len(expected)
    rr = next((1 / i for i, cid in enumerate(retrieved, start=1) if cid in expected), 0.0)
    return recall, rr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-expired", action="store_true", help="switch off the status/date filter")
    args = parser.parse_args()

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    retriever = HybridRetriever()
    rows = []
    for q in golden:
        res = retriever.search(q["question"], q["user_roles"], EVAL_DATE, args.include_expired, min_rerank_score=0.0,
                               final_k=config.CANDIDATES_K * 2)
        rows.append((q, res.candidates))  # candidates are sorted by rerank score
        print(f"{q['id']} done", end="\r")
    RAW.write_text(json.dumps({q["id"]: [vars(h) | {"meta": None} for h in c] for q, c in rows}, indent=1),
                   encoding="utf-8")

    def score(threshold: float, final_k: int) -> dict:
        answerable, empty_ok, leaks, recalls, rrs = 0, 0, 0, [], []
        should_be_empty = 0
        for q, cands in rows:
            final = [h.id for h in cands[:final_k] if h.rerank_score >= threshold]
            forbidden = {Path(n["source_uri"]).stem for n in q["negative_examples"]}
            leaks += any(cid.split("#")[0] in forbidden for cid in final)
            expected = {chunk_id(p["source_uri"], p["heading"]) for p in q["relevant_passages"]}
            if q["category"].startswith("unanswerable-live") or not expected:
                # Q14-style questions point at a 'no live data' passage; treat both kinds as "no answer here".
                if not expected:
                    should_be_empty += 1
                    empty_ok += not final
                    continue
            answerable += 1
            r, rr = metrics(expected, final)
            recalls.append(r)
            rrs.append(rr)
        return {"recall": sum(recalls) / answerable, "mrr": sum(rrs) / answerable,
                "empty_ok": f"{empty_ok}/{should_be_empty}", "leaks": leaks, "n": answerable}

    stage1 = [metrics({chunk_id(p["source_uri"], p["heading"]) for p in q["relevant_passages"]},
                      [h.id for h in sorted(c, key=lambda h: h.rrf_score, reverse=True)])
              for q, c in rows if q["relevant_passages"]]
    print(f"\nStage 1 (hybrid, fused top-{config.CANDIDATES_K}): "
          f"Recall@{config.CANDIDATES_K} = {sum(r for r, _ in stage1) / len(stage1):.3f} over {len(stage1)} questions")

    print(f"\nStage 2 (reranked, top-{config.FINAL_K}) by minimum rerank score:")
    print(f"{'threshold':>9} {'Recall@5':>9} {'MRR':>6} {'empty when expected':>20} {'leaks':>6}")
    for t in THRESHOLDS:
        s = score(t, config.FINAL_K)
        mark = "  <- current" if t == config.MIN_RERANK_SCORE else ""
        print(f"{t:>9} {s['recall']:>9.3f} {s['mrr']:>6.3f} {s['empty_ok']:>20} {s['leaks']:>6}{mark}")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "category", "user_roles", "expected_chunks", "retrieved_chunks_with_rerank_score",
                    "recall_at_5", "reciprocal_rank", "forbidden_leak"])
        for q, cands in rows:
            final = [h for h in cands[:config.FINAL_K] if h.rerank_score >= config.MIN_RERANK_SCORE]
            expected = {chunk_id(p["source_uri"], p["heading"]) for p in q["relevant_passages"]}
            forbidden = {Path(n["source_uri"]).stem for n in q["negative_examples"]}
            r, rr = metrics(expected, [h.id for h in final]) if expected else ("", "")
            w.writerow([q["id"], q["category"], ";".join(q["user_roles"]), ";".join(sorted(expected)),
                        ";".join(f"{h.id}={h.rerank_score:.3f}" for h in final), r, rr,
                        any(h.id.split("#")[0] in forbidden for h in final)])
    print(f"\nPer-question results at threshold {config.MIN_RERANK_SCORE}: {OUT.relative_to(config.PROJECT_DIR)}")


if __name__ == "__main__":
    main()
