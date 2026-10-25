# RAG demonstration pack

## What this is
Eight synthetic enterprise policies for Northstar Studio, a fictional UK employer. All rules, people and contacts are invented. This is a demonstration corpus, not employment or legal guidance. The .example email addresses cannot receive messages.

The assignment asks for real enterprise documents. This synthetic pack is useful for development and demonstration, but does not satisfy that requirement on its own. Confirm whether a synthetic corpus is acceptable, or replace it with authorised real documents before submission. Do not describe these policies as HSBC documents.

## Start here
1. Extract this ZIP. Copy the eight Markdown files in data/ into your project's data/ folder.
2. Ingest only data/*.md. Keep evaluation/, negative_examples/, this guide and the printable PDF outside the knowledge index. Otherwise expected answers can leak into retrieval.
3. Parse headings and preserve each heading with its section. For an initial trial, use recursive splitting at roughly 400 tokens with 60-token overlap. Count with your chosen model's tokenizer; characters are not tokens. Short sections may stay together, so overlap is a target, not a requirement for every chunk.
4. Assign chunk_id after splitting; keep source_uri, parent_doc_id, heading, version, updated_at, status, tenant_id and acl_roles with each chunk. Use the original policy ID for parent_doc_id. Metadata written in a document is not automatically a database filter: extract it explicitly.
5. Embed and index the chunks using your selected starter. Dense vectors are created during ingestion; this pack does not contain embeddings or a BM25 index. Add BM25/hybrid retrieval only if your implementation supports it. Record the actual embedding model and retrieval settings used.
6. Ask the bot to answer only from retrieved sources, cite filenames and sections, ask for clarification where needed, and admit when evidence is missing. This is guidance, not a substitute for access controls.
7. Run all 15 questions in evaluation/golden_15.json. Keep answers and retrieved evidence in results_template.csv. Do not fill scores until you run the bot.
8. Record the demo and save the completed evaluation report with your repository link or ZIP.

## Optional outdated-document test
The expired expenses policy is isolated in negative_examples/. First build the normal index without it. For the adversarial run, deliberately add that file with status=expired and its dates as structured metadata. Apply current-status, effective-date, tenant and access-role filters before ranking, then run Q06 again. Log whether the stale text was retrieved or used. For repeatability, use 18 October 2026 as the evaluation date. Never move the expired file into the baseline corpus by accident.

## Golden set and scope
The main assignment requests 15 questions; a later specification requests 50-200 QA samples. This pack contains 15, so it meets the question count in the main brief only. Expand to at least 50 if the later specification is mandatory. The references use exact passages rather than fabricated chunk IDs. Map passages to your actual chunk IDs after ingestion. Expected answers are checked against this synthetic corpus by its author, not verified by a subject matter expert. Seek SME review if required.

## Scoring each run
Retrieval: 2 = all required evidence retrieved; 1 = some required evidence; 0 = none or only misleading evidence. Use N/A for Q08 and Q15, which have no required evidence, and assess clarification or abstention using answer quality. For Q14, score retrieval against the passage explicitly saying live balances are absent.
Answer: 2 = correct, complete and grounded, or appropriate clarification/abstention; 1 = partly correct or incomplete without a material invented fact; 0 = wrong, invented, or fails a critical exception.
Citations: 2 = all substantive policy claims cite supporting current sources; 1 = partial support; 0 = unsupported or wrong citations. Use N/A for pure clarification or no-answer responses making no policy claim. Report mean scores with denominators and exclude N/A. Also report evidence coverage: required source documents retrieved / required source documents, and keep the top-k and retrieval settings fixed.
Analyse failures separately: parsing, chunk boundaries, retrieval, stale metadata, missing multi-document evidence, generation, ambiguous intent, or absent source information. An honest refusal for absent information is a success, not a retrieval failure.

## Security demonstration limits
The original eight policies use tenant_id=northstar_demo and acl_roles=[employee, people_admin]. Two restricted documents were added for role filtering: data/pay_and_salary_bands.md (people_admin only) and data/disciplinary_procedure.md (line_manager, people_admin). Test users hold role sets [employee], [employee, line_manager] or [employee, people_admin]; a chunk is visible if it shares at least one role with the user. evaluation/golden_50.json records the role set for every question (the access-allowed and access-denied categories test this). The corpus is still single-tenant, so it cannot demonstrate tenant isolation. Role filtering here is simulated with chosen role sets, not authenticated users.

## Submission checklist
- Working bot and reproducible setup instructions, dependency versions and model/settings record.
- Demo recording showing an ordinary answer, a multi-document answer, the stale-policy challenge, clarification and an unanswered question.
- Completed evaluation report with actual results, scores, source evidence, failures and proposed improvements.
- GitHub link or project ZIP. This pack supplies documents and evaluation scaffolding; it does not supply a running bot or measured results.

## Printing
Open RAG_Printable_Pack.pdf and print on A4, portrait, at actual size. It contains the eight current policies and the evaluation reference. The expired policy remains a separate Markdown file for controlled testing.
