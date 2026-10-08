# VISUAL: can a library of wordless pictures be searched? (commit 7e1fe649f)

- generated 2026-10-08T00:37:50.278445+00:00
- corpus: OS-Copilot/ScreenSpot-v2 (icon instructions), 554 icon crops and 408 whole screenshots stored as separate memories, 427 crops with no OCR text
- encoder: Xenova/chinese-clip-vit-base-patch16 sha256 0fad978faa89b85f
- machine: 32 cpus, load [46.81, 44.0, 33.68]
- instructions containing Chinese: 0 (ScreenSpot-v2 is English, so this run does not test the bilingual claim)

| ask | pool | recall@1 | recall@5 | recall@10 | chance@10 | MRR | hit@10 lower 95% | p50 s | p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| words → icon crops | crops | 0.090 | 0.152 | 0.175 | 0.0181 | 0.118 | 0.146 | 0.1716 | 0.2096 |
| a sentence → icon crops (picture space) | crops | 0.081 | 0.155 | 0.208 | 0.0181 | 0.116 | 0.176 | 0.1399 | 0.1998 |
| the whole screenshot → icon crops | crops | 0.038 | 0.083 | 0.108 | 0.0181 | 0.058 | 0.085 | 0.1599 | 0.22 |
| words → whole screenshots | shots | 0.121 | 0.296 | 0.384 | 0.0245 | 0.196 | 0.345 | 0.1362 | 0.2038 |
| a sentence → whole screenshots (picture space) | shots | 0.049 | 0.146 | 0.215 | 0.0245 | 0.091 | 0.183 | 0.136 | 0.204 |
| a sentence → the icons of that one screen | own_screen | 0.827 | 1.000 | 1.000 | 1.0000 | 0.908 | 0.993 | 0.1358 | 0.1959 |

The words rows are what the product could do before any picture vector: if OCR found no words, there is nothing to match. The picture rows ask the same sentence, or the whole screenshot, of the CLIP space. The pools change the question: among every icon in the library, among whole screenshots (the granularity the store keeps), and among one screen's icons, which is the shape ScreenSpot itself poses. A number is only comparable inside its own pool, so chance is printed per row.
