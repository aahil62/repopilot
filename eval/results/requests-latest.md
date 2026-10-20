# RepoPilot evaluation — requests @ v2.32.3

Mode: **models** · models: nomic-embed-text:latest, qwen2.5-coder:1.5b, qwen2.5-coder:7b · 2026-10-20T10:58:24+00:00

| Measure | Result |
|---|---|
| Retrieval Recall@5, keyword only | 88% (25 questions) |
| Retrieval Recall@5, vector only | 92% |
| Retrieval Recall@5, hybrid (RRF) | 96% |
| Refusal accuracy | 93% (30 questions) |
| Hunks set aside as mechanical (formatting, comments, docs, import order, renames) | 24% of 128 hunks in the last 40 commits |
| Mechanical label vs hand labels, held-out set | precision 100%, recall 75% (30 hunks) |
| Mechanical label vs hand labels, tuning set | precision 100%, recall 91% (60 hunks; rules were adjusted on this set) |
| Mechanical label vs hand labels, JavaScript/TypeScript (axios, zustand) | precision 100%, recall 72% (41 hunks) |
| Model findings that cited real changed lines | 100% (1 of 1) |
