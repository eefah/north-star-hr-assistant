# HR Policy Assistant: Tech Stack and Approval Request

## Purpose

A chat assistant that answers employee questions about HR policy, using only approved policy documents. Every answer cites the policy section it came from. If no policy covers the question, the assistant says so instead of guessing.

The current build is a working prototype that runs on synthetic policies for a fictional company. This document lists the tools it uses, what data leaves our environment, and what we need approved to pilot it on real policies.

## Approval requested

| # | Item | Type | Why it's needed |
|---|---|---|---|
| 1 | **Groq API** | External SaaS (LLM inference) | Generates the answers |
| 2 | **Pinecone** | External SaaS (vector database + hosted embedding and reranking models) | Stores policy chunks and finds the relevant ones for each question |
| 3 | **Streamlit** | Open-source Python library (Apache 2.0) | Web chat interface |
| 4 | Python packages listed under [Dependencies](#dependencies) | Open-source libraries | Runtime |
| 5 | Somewhere to host it | Internal VM or container platform | Running the app for pilot users |

## Architecture

```
                      ┌──────────────────────── Our environment ────────────────────────┐
                      │                                                                 │
 Policy .md files ──► │ ingest.py ── chunks + metadata ──────────────────────────────┐  │
                      │     │                                                        │  │
                      │     └─► index/chunks.jsonl (local copy, used for keyword search)  │
                      │                                                              │  │
 Employee ──────────► │ Streamlit app (app.py)                                       │  │
  (browser)           │     │                                                        │  │
                      │     ▼                                                        │  │
                      │ retriever.py                                                 │  │
                      │   1. Build an access filter (role, tenant, policy in force)  │  │
                      │   2. Keyword search (BM25, local, in memory)                 │  │
                      │   3. Semantic search ──────────────────────────────────────┐ │  │
                      │   4. Merge results (Reciprocal Rank Fusion)                │ │  │
                      │   5. Rerank ──────────────────────────────────────────────┐│ │  │
                      │     │                                                     ││ │  │
                      │     ▼                                                     ││ │  │
                      │ rag.py: no evidence → fixed refusal, no LLM call          ││ │  │
                      │         evidence    → prompt ───────────────────────────┐ ││ │  │
                      │                       check citations ◄── answer ───────┤ ││ │  │
                      └─────────────────────────────────────────────────────────┼─┼┼─┼──┘
                                                                                │ ││ │
                                            Groq (gpt-oss-120b) ◄───────────────┘ ││ │
                                            Pinecone (search, rerank, store) ◄────┴┴─┘
```

### How a question is answered

1. **Access filter.** The user's role, the tenant and today's date become a metadata filter. Search only sees policies that are current, in force on that date and visible to that role. The same filter is applied to both keyword and semantic search.
2. **Hybrid retrieval.** The top 20 matches from semantic search (Pinecone) and the top 20 from keyword search (BM25) are merged with Reciprocal Rank Fusion. Keyword search catches exact terms such as policy codes and amounts. Semantic search catches paraphrases.
3. **Reranking.** A cross-encoder model rescores the merged candidates. The top 5 above a relevance threshold go forward.
4. **Refusal gate.** If nothing passes, the user gets a fixed "can't find this, contact the People team" reply. No LLM call is made, so there's nothing for a model to invent.
5. **Generation.** The LLM receives the excerpts with strict instructions: answer only from these excerpts, cite every claim, ask for clarification if the question is ambiguous, and ignore any instructions that appear inside documents. Temperature is set to 0.
6. **Citation check.** Citations in the answer are checked against the excerpts that were actually retrieved. The UI flags any citation that doesn't match.

## Components

| Layer | Tool | Version | Hosting | Licence or terms |
|---|---|---|---|---|
| Language | Python | 3.12.4 | Our environment | PSF |
| UI | Streamlit | 1.66.0 | Our environment | Apache 2.0 |
| LLM | `openai/gpt-oss-120b` via Groq API | Groq SDK 1.7.0 | Groq cloud | Model: open weights (Apache 2.0). Service: Groq commercial terms |
| Vector database | Pinecone serverless index `hr-policies` | Pinecone SDK 10.0.0 | Pinecone cloud | Pinecone commercial terms |
| Embeddings | `llama-text-embed-v2` (Pinecone integrated inference) | – | Pinecone cloud | Pinecone commercial terms |
| Reranker | `bge-reranker-v2-m3` (Pinecone inference) | – | Pinecone cloud | Pinecone commercial terms |
| Keyword search | rank-bm25 | 0.2.2 | Our environment, in memory | Apache 2.0 |
| Config and secrets | python-dotenv | 1.2.4 | Our environment | BSD-3-Clause |

### Dependencies

Pinned in `requirements.txt`:

```
pinecone==10.0.0
groq==1.7.0
python-dotenv==1.2.4
streamlit==1.66.0
rank-bm25==0.2.2
```

`pandas` (3.0.6) and `numpy` (2.5.4) come in through Streamlit. `app.py` imports pandas directly, so it should be pinned explicitly before a pilot.

## Data flow and residency

This section is the most important one for security review.

| Data | Where it goes | When |
|---|---|---|
| Full text of every policy chunk, plus metadata (title, version, roles, dates) | **Pinecone**, where it is stored and embedded | At ingestion |
| The employee's question | **Pinecone** (embedding and rerank) and **Groq** (generation) | Every question |
| Up to 5 policy excerpts | **Pinecone** (rerank) and **Groq** (prompt) | Every question that finds evidence |
| The generated answer | Returned to the browser. Not stored | Every question |

Things to note:
- **Policy content leaves our environment.** For confidential policies, such as pay bands and disciplinary procedures, we need data processing terms with both vendors.
- **Questions may contain personal data.** Employees will type things like "I'm off sick with X, what do I do?". The prototype doesn't filter this out before sending.
- **Nothing is persisted by the app.** Chat history lives in the browser session only. There's no database and no logging.
- **Pinecone region:** the prototype index runs on AWS us-east-1, so policy text is stored in the US. An EU region would need a new index.
- **To confirm with each vendor:** EU/UK data residency options, retention and zero-data-retention settings, whether inputs are used for training, SOC 2 / ISO 27001 reports, and DPA availability.

### Fallback if external LLM hosting isn't approved

The LLM is an open-weights model, so it isn't locked to Groq. It could run on an approved cloud provider or on internal GPUs without changing the design. Embeddings and reranking could likewise move to self-hosted models (for example `bge-m3` and `bge-reranker-v2-m3`) with a self-hosted vector store. Each swap is a change to one module.

## Security posture: what the prototype does and doesn't do

| Control | Prototype | Needed for pilot |
|---|---|---|
| Authentication | **None.** The user picks a role from a dropdown | SSO (e.g. Entra ID / Okta) in front of the app, with roles taken from identity groups |
| Role-based document access | Metadata filter applied before search, in both search paths | Keep this. Map roles to real groups |
| Stale policy exclusion | Filter on status and effective dates. Tested with a deliberately expired policy | Keep this. Document owners maintain the metadata |
| Prompt injection from documents | Instruction to treat excerpts as reference only | Only approved authors can publish to the corpus |
| Hallucination | Refusal gate, citation-only prompt, citation check | Keep this. Add human review of a sample of answers |
| Secrets | API keys in a local `.env` file (not committed) | Move to the enterprise secrets manager |
| Tenant isolation | Single tenant and single namespace. Not demonstrated | Separate namespace or index per tenant if needed |
| Audit logging | None | Log question, role, retrieved IDs and answer, with redaction and a retention policy |
| Rate limiting and cost control | None. Uses vendor account limits | Per-user limits and spend alerts |

## Quality evidence

Retrieval was evaluated on a 50-question test set covering ordinary, multi-document, ambiguous, unanswerable, access-allowed and access-denied questions (`eval_retrieval.py`):
- **Recall@5 of 0.91** at the chosen rerank threshold (0.01). This means 91% of the expected policy sections reached the LLM.
- 5 of 7 unanswerable questions correctly retrieved nothing. The other 2 rely on the LLM's instruction to say it doesn't know.
- Restricted and expired documents were checked for leakage on every question. Access control doesn't depend on the relevance threshold.

End-to-end answers were scored by an LLM judge from a different model family (`eval_answers.py`; full results in `evaluation/report.md`):
- **100% faithfulness.** All 50 answers were supported by the retrieved policies, with no invented facts.
- **80% fully correct.** The remaining 10 were incomplete, mostly answers that left out a secondary condition.
- **Stale-policy test.** With an expired policy indexed alongside the current one, the status and date filter kept it out of all related questions.

## Operating profile

- **Footprint:** a single Python process. BM25 rebuilds over the permitted chunks on every query, which is fine for hundreds of chunks. At thousands of chunks it should move to a persistent keyword index, or to Pinecone's sparse vectors.
- **Latency:** shown per question in the app's retrieval trace (split into retrieval and generation).
- **Cost drivers:** one Groq completion per answered question (capped at 600 output tokens), plus one Pinecone search and one rerank call per question. There's no LLM cost for refused questions.
- **Updating content:** run `python ingest.py`. It clears and rebuilds the namespace, so the index always matches the source files exactly.

## Suggested next steps

1. Security and procurement review of Groq and Pinecone, using the vendor questions above. Alternatively, decide on self-hosted alternatives.
2. Approve a hosting target and a secrets manager.
3. Add SSO, audit logging and per-user rate limits.
4. Replace the synthetic corpus with a small set of approved real policies. Have the People team review answers before wider rollout.
