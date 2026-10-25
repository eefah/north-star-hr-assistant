# Evaluation report

On a 50-question golden set, every answer was faithful to the retrieved policies, 40 of 50 answers were fully correct, and no restricted or expired document reached a user who shouldn't see it. The main weaknesses are answers that drop secondary conditions, and questions that quote outdated numbers.

## Setup

| Item | Value |
| --- | --- |
| Run date / evaluation date | 25 Oct 2026 / policies in force on 18 Oct 2026 |
| Corpus | Northstar synthetic demo 2.0: 10 policies, 51 chunks (plus 1 expired policy for the stale test) |
| Parsing and chunking | One chunk per `##` section; 250-word windows with 40-word overlap only for longer sections (none were longer; max 66 words); title and heading prepended; word counts, not tokens |
| Embedding / vector store | `llama-text-embed-v2` (1024-d, cosine), Pinecone serverless, AWS us-east-1 |
| Retriever | Dense top 20 + BM25 top 20, RRF (k = 60), `bge-reranker-v2-m3`, top 5 with rerank score >= 0.01 |
| Filters | tenant, role overlap, `status = current`, effective dates covering the evaluation date |
| Generation | `openai/gpt-oss-120b` on Groq, temperature 0, max 600 tokens, system prompt in `rag.py` |
| Judge | `qwen/qwen3.8-27b` on Groq, temperature 0, prompt in `eval_answers.py` |
| Ground truth | Author-written synthetic references; not reviewed by an HR subject matter expert |

Scripts: `eval_retrieval.py` (retrieval only, no LLM) and `eval_answers.py` (end-to-end with the judge). Per-question results are in `results.csv`, and raw answers with judge verdicts are in `answers_raw.json`.

## Results

| Metric | Result | Denominator |
| --- | --- | --- |
| Faithfulness (every claim supported by retrieved excerpts) | **100%** | 50 |
| Answers fully correct (score 2) | **80%** (40) | 50 |
| Answer score, mean | 1.78 / 2 | 50 |
| Citation score, mean | 2.00 / 2 | 42 (8 N/A: refusals and clarifying questions) |
| Retrieval score, mean | 1.81 / 2 | 43 (7 N/A: no required evidence) |
| Recall@5 (expected chunks reaching the prompt) | 0.91 | 43 |
| MRR | 0.95 | 43 |
| Forbidden documents retrieved | **0** | 50 |
| Latency, median / p90 / max | 4.2 s / 7.6 s / 9.1 s | 50 |

Answer score distribution: 40 scored 2, 9 scored 1 and 1 scored 0.

| Category | Fully correct |
| --- | --- |
| Direct | 13 / 16 |
| Exception | 9 / 10 |
| Multi-document | 4 / 7 |
| Access-allowed | 4 / 5 |
| Access-denied | 3 / 3 |
| Keyword | 2 / 2 |
| Ambiguous (clarifying question expected) | 2 / 2 |
| Unanswerable, missing policy | 2 / 2 |
| Unanswerable, live data | 1 / 1 |
| Outdated premise | 0 / 2 |

All 8 questions that should get a refusal or a clarifying question got one: 3 access-denied, 2 ambiguous, 2 missing policy and 1 live data.

**Latency.** Retrieval took a median of 0.6 s. Generation took about 0.5 s for the first 10 questions, then about 3.5 s for the rest of the run. This pattern looks like Groq free-tier throttling under back-to-back requests, but I haven't confirmed it. Single questions in the app return in 1 to 3 s. The 5-second target is met at the median but missed at p90 under evaluation load.

### Stale-policy challenge

I indexed the expired expenses policy (60-day deadline, £40 dinner cap) alongside the current one (30 days, £30). Then I asked the three questions that touch it, with the filter on and with it off.

| Question | Filter on: expired doc retrieved? | Filter off: expired doc retrieved? | Filter off: stale rule presented as current? |
| --- | --- | --- | --- |
| Q06 "60 days and £40?" | No | Yes | No. It said the 60 days came from an expired version |
| Q21 "deadline for expenses?" | No | Yes | No. It answered 30 days from the current policy |
| Q40 "60 days and £40, is that right?" | No | Yes | No. It said these were the expired rules, replaced on 1 Oct 2026 |

The metadata filter is the real control: with it on, the expired policy never reaches the prompt. With it off, the model still didn't pass off stale rules as current. Each excerpt carries `status="expired"`, and the model used that label. This is a useful second layer, but it isn't something to rely on.

## Failure analysis

10 answers scored below 2. None contained an invented fact.

| ID | Expected evidence | Retrieved | What went wrong | Cause (from the trace) |
| --- | --- | --- | --- | --- |
| Q02 | carry-over | carry-over | Gave the 5-day limit, but left out the 15 Dec approval and 31 Mar use-by dates | Generation: evidence present, conditions dropped |
| Q07 | partner-benefit, eligibility | both | Left out "one block within 6 months" | Generation |
| Q34 | before-day-one | before-day-one | Left out "at least 5 working days before start" | Generation |
| Q38 | how-to-request | how-to-request | Left out the expected date and leave dates to provide | Generation |
| Q50 | appeals | appeals | Left out who hears the appeal | Generation |
| Q35 | first-month, equipment | both | Left out "hybrid only after the first 4 weeks" | Generation |
| Q05 | eligibility-and-submission, equipment | equipment only | Left out the 30-day deadline and itemised receipt | Retrieval: needed chunk reranked to 0.005, below the 0.01 threshold |
| Q09 | 4 chunks incl. sickness evidence | 3 of 4 | Left out the self-certification and fit-note rules | Retrieval: evidence chunk ranked 7th (score 0.002) |
| Q06 | eligibility-and-submission, travel-and-meals | travel-and-meals only | Corrected the £40 to £30, but said the deadline wasn't covered | Retrieval: deadline chunk scored 0.003 |
| Q40 | same as Q06 | nothing | Refused entirely | Retrieval: dense and BM25 both ranked the right chunk 1st, but the reranker scored it 0.003, so the refusal gate fired |

**Pattern 1: concise answers drop conditions (6 questions).** In every case the evidence was in the prompt. Rule 10 of the system prompt ("answer first in one or two sentences") pushes the model to stop after the headline fact. *Change to test:* reword rule 10 to "always include the conditions, deadlines and exceptions that apply". *Rerun:* not yet run.

**Pattern 2: the reranker penalises questions that contradict the policy (Q06, Q40).** A question quoting outdated numbers ("60 days, £40") is a poor match for the chunk that says "30 days, £30". The cross-encoder scores that pair as irrelevant, even though both first-stage retrievers ranked it first. *Change to test:* keep a chunk that both dense and BM25 rank first, even when it falls below the rerank threshold. Alternatively, rewrite the query to strip the user's numbers before reranking. *Rerun:* not yet run.

**Pattern 3: multi-document recall (Q05, Q09).** The second policy's chunk ranks just below the threshold. *Change to test:* lower the threshold to 0.002 for chunks from a document that is already retrieved, or decompose multi-part questions. *Rerun:* not yet run.

### Issues the judge missed

- **Malformed citations.** In Q38 the model put a zero-width character inside the citation (`[ parent​al_leave#how-to-request ]`). In Q37 it dropped the document prefix (`[partner-benefit]`). The app's citation check didn't parse either one, so neither was flagged, yet the judge gave both answers full citation marks. *Fix:* strip Unicode spacing characters before parsing, and flag any bracketed token that isn't a retrieved ID.
- **Judge variance.** Q21 scored 2 in the baseline run and 1 in the stale-test runs, for almost identical answers. A single judge pass has roughly one point of noise on borderline answers.
- **Retrieval scored 0 but answered correctly (Q14).** The expected passage ("live balances are not held here") wasn't retrieved. The model still refused correctly, because rule 7 of the prompt covers personal data.

## Limitations

- The policies are synthetic, and the references haven't been reviewed by an HR subject matter expert.
- The corpus has a single tenant, so tenant isolation isn't demonstrated.
- Roles are picked in the UI, not taken from an authenticated login.
- The LLM judge is a single pass with no human calibration. Judge scores should be read as approximate (see Judge variance above).
- Latency was measured on Groq's free tier.
- With 51 short chunks, dense search alone reaches Recall@5 of 1.00, so this corpus is too small to show the benefit of hybrid retrieval.

## Conclusion and next steps

The system is faithful and safe on this corpus. It never invented a fact, never leaked a restricted or expired document, and refused or asked for clarification whenever it should. Its answers are sometimes incomplete. Next steps, in order of expected impact:

1. Reword prompt rule 10 to keep conditions and exceptions, then rerun all 50 questions.
2. Rescue chunks that both retrievers rank first from the rerank threshold, then rerun Q05, Q06, Q09 and Q40.
3. Harden citation parsing and flag malformed IDs.
4. Calibrate the judge against a hand-scored sample of 10 answers.
