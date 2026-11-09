# NDA: layout text vs Markdown as the <document>

Same prompt, schema and fields table; only the <document> text differs. Inputs: each run's `02-*` file.

| | layout text | md pymupdf4llm | md docling |
|---|---|---|---|
| latency | 15.2 s | 23.6 s | 21.0 s |
| input tokens | 3592 | 3696 | 3584 |
| output tokens (reasoning) | 1871 (512) | 2676 (1300) | 2514 (1158) |
| checks | all passed | all passed | f6: depends on None, but the layout puts it under ('f7', 'Choice1') |
| roles | party_1 (signer), party_2 (signer) | party_1 (signer), party_2 (signer) | party_1 (signer), party_2 (signer) |
| description | A mutual non-disclosure agreement between two parties. It covers the purpose and period of sharing information, the confidentiality term, governing law, jurisdiction and any changes to the standard terms. Both parties sign; there is no countersignature. (253 chars) | A mutual non-disclosure agreement between two parties. It covers the purpose and term of information sharing, confidentiality duration, changes to the standard terms, governing law and jurisdiction. Both parties sign; there is no countersignature. (247 chars) | A mutual non-disclosure agreement between two parties. It covers the purpose and term of sharing Confidential Information, its confidentiality period, governing law, jurisdiction, and any changes to the standard terms. Both parties sign; there is no specified countersigner. (274 chars) |

## Fields that differ from the layout-text run

| id | what | layout text | md pymupdf4llm | md docling |
|---|---|---|---|---|
| f3 | holds | text | number | text |
| f5 | holds | text | number | text |
| f6 | depends_on | f7=Choice1 | f7=Choice1 | None |
