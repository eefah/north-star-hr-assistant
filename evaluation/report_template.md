# Evaluation report - complete after running the bot

Status: NOT RUN. No performance results have been measured.

## Setup
Run date / evaluation date:
Corpus version: Northstar synthetic demo 2.0
Parser / chunk size / overlap / tokenizer:
Embedding model / vector store:
Retriever / top-k / filters / reranker:
Generation model / prompt version:
Source of ground truth: author-written synthetic policies; SME review pending if required.

## Results
Attach completed results_template.csv. Report total questions, retrieval mean and denominator, answer mean and denominator, citation mean and denominator, source-document coverage, and clarification/abstention outcomes. Show baseline and stale-document challenge results separately. Leave fields blank until measured.

## Failure analysis
For each failed or partial answer record: question ID; expected evidence; actual retrieved chunks; actual answer; cause supported by the trace; change to test; rerun result. Distinguish missing evidence from a model ignoring evidence it received.

## Limitations
Only 15 questions; synthetic rather than real enterprise documents; no SME verification; one tenant and one shared access group. Add findings from the actual implementation.

## Conclusion and next steps
Complete after measurement. Do not claim improvements without a comparable rerun.
