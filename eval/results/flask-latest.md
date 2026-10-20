# RepoPilot evaluation — flask @ 3.1.0

Mode: **models** · models: nomic-embed-text:latest, qwen2.5-coder:1.5b, qwen2.5-coder:7b · 2026-10-20T09:50:23+00:00

| Measure | Result |
|---|---|
| Retrieval Recall@5, keyword only | 88% (25 questions) |
| Retrieval Recall@5, vector only | 80% |
| Retrieval Recall@5, hybrid (RRF) | 88% |
| Refusal accuracy | 100% (30 questions) |
| Hunks set aside as mechanical (formatting, comments, docs, import order, renames) | 61% of 252 hunks in the last 40 commits |
| Mechanical label vs hand labels, held-out set | precision 100%, recall 75% (30 hunks) |
| Mechanical label vs hand labels, tuning set | precision 100%, recall 91% (60 hunks; rules were adjusted on this set) |
| Mechanical label vs hand labels, JavaScript/TypeScript (axios, zustand) | precision 100%, recall 72% (41 hunks) |
| Model findings that cited real changed lines | 100% (4 of 4) |
| Benchmark recommendation | Use qwen2.5-coder:7b for review and code (score 0.40, median 93 s on your machine). It is slow on this hardware, but the faster models scored much lower. qwen2.5-coder:1.5b is good enough for classification. |
