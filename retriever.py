"""Hybrid retrieval: Pinecone dense search + local BM25, fused with RRF, then reranked.

    python retriever.py "Can I claim wine with dinner?" --roles employee
"""
import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date

from pinecone import Pinecone
from rank_bm25 import BM25Okapi

import config

STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i if in is it its me my of on or our "
    "should so that the their there this to was we what when where which who will with you your".split()
)
TOKEN = re.compile(r"£?[a-z0-9]+(?:[-.'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase, keep codes such as ns-expenses, new-starter and £50 whole, drop stopwords."""
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


def date_to_int(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


@dataclass
class Hit:
    id: str
    text: str
    meta: dict
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


@dataclass
class RetrievalResult:
    query: str
    filter: dict
    hits: list[Hit]  # final chunks for the prompt, best first
    candidates: list[Hit] = field(default_factory=list)  # every fused candidate, for the trace


class HybridRetriever:
    def __init__(self):
        pc = Pinecone()
        self.index = pc.Index(name=config.INDEX_NAME)
        self.inference = pc.inference
        with config.CHUNKS_FILE.open(encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f]
        self.by_id = {c["_id"]: c for c in self.chunks}

    @staticmethod
    def build_filter(roles: list[str], as_of: date, include_expired: bool = False) -> dict:
        """Pinecone metadata filter: tenant, role overlap, and (unless disabled) only policies in force on as_of."""
        conditions = [
            {"tenant_id": {"$eq": config.NAMESPACE}},
            {"acl_roles": {"$in": roles}},
        ]
        if not include_expired:
            day = date_to_int(as_of)
            conditions += [
                {"status": {"$eq": "current"}},
                {"effective_from": {"$lte": day}},
                {"effective_until": {"$gte": day}},
            ]
        return {"$and": conditions}

    @staticmethod
    def matches(chunk: dict, flt: dict) -> bool:
        """Apply the same filter locally so BM25 never sees chunks Pinecone would hide."""
        for cond in flt["$and"]:
            (key, (op, val)), = ((k, *v.items()) for k, v in cond.items())
            have = chunk.get(key)
            ok = {
                "$eq": lambda: have == val,
                "$in": lambda: bool(set(have if isinstance(have, list) else [have]) & set(val)),
                "$lte": lambda: have is not None and have <= val,
                "$gte": lambda: have is not None and have >= val,
            }[op]()
            if not ok:
                return False
        return True

    def dense(self, query: str, flt: dict, k: int) -> list[str]:
        res = self.index.search(namespace=config.NAMESPACE, top_k=k, inputs={"text": query},
                                filter=flt, fields=["heading"])
        return [h.id for h in res.result.hits]

    def bm25(self, query: str, flt: dict, k: int) -> list[str]:
        allowed = [c for c in self.chunks if self.matches(c, flt)]
        if not allowed:
            return []
        scores = BM25Okapi([tokenize(c[config.TEXT_FIELD]) for c in allowed]).get_scores(tokenize(query))
        ranked = sorted(zip(scores, (c["_id"] for c in allowed)), reverse=True)
        return [cid for score, cid in ranked[:k] if score > 0]

    def search(self, query: str, roles: list[str], as_of: date | None = None, include_expired: bool = False,
               candidates_k: int = config.CANDIDATES_K, final_k: int = config.FINAL_K,
               min_rerank_score: float = config.MIN_RERANK_SCORE) -> RetrievalResult:
        flt = self.build_filter(roles, as_of or date.today(), include_expired)

        # Stage 1: wide net for recall. Fuse the two rankings with Reciprocal Rank Fusion.
        hits: dict[str, Hit] = {}
        for source, ids in (("dense_rank", self.dense(query, flt, candidates_k)),
                            ("bm25_rank", self.bm25(query, flt, candidates_k))):
            for rank, cid in enumerate(ids, start=1):
                chunk = self.by_id.get(cid)
                if chunk is None:  # in Pinecone but not in chunks.jsonl: re-run ingest.py
                    continue
                hit = hits.setdefault(cid, Hit(cid, chunk[config.TEXT_FIELD], chunk))
                setattr(hit, source, rank)
                hit.rrf_score += 1 / (config.RRF_K + rank)
        candidates = sorted(hits.values(), key=lambda h: h.rrf_score, reverse=True)[:candidates_k]
        if not candidates:
            return RetrievalResult(query, flt, [], [])

        # Stage 2: cross-encoder rerank for precision; drop anything the reranker thinks is irrelevant.
        ranked = self.inference.rerank(model=config.RERANK_MODEL, query=query,
                                       documents=[h.text for h in candidates], return_documents=False)
        for r in ranked.data:
            candidates[r.index].rerank_score = r.score
        candidates.sort(key=lambda h: h.rerank_score, reverse=True)
        final = [h for h in candidates[:final_k] if h.rerank_score >= min_rerank_score]
        return RetrievalResult(query, flt, final, candidates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--roles", default="employee", help="comma-separated, e.g. employee,people_admin")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--include-expired", action="store_true", help="switch off the status/date filter")
    args = parser.parse_args()

    result = HybridRetriever().search(args.query, args.roles.split(","), args.as_of, args.include_expired)
    print(f"{'chunk':<48} {'dense':>5} {'bm25':>5} {'rrf':>7} {'rerank':>7}")
    final_ids = {h.id for h in result.hits}
    for h in result.candidates:
        mark = "*" if h.id in final_ids else " "
        print(f"{mark}{h.id:<47} {h.dense_rank or '-':>5} {h.bm25_rank or '-':>5} "
              f"{h.rrf_score:>7.4f} {h.rerank_score:>7.3f}")
    print(f"\n* = passed to the LLM ({len(result.hits)} chunks)")


if __name__ == "__main__":
    main()
