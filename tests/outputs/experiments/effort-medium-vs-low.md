# Reasoning effort: medium vs low

Same code, prompt, schema and documents; only `reasoning_effort` differs. Medium: `tests/outputs/<doc>/`; low: `tests/outputs/<doc>/variants/effort-low/`.

| document | fields | latency medium → low | output tokens (reasoning) medium → low | checks medium / low | answers that differ |
|---|---|---|---|---|---|
| Mutual-NDA-public-v1 | 22 | 26.5 s → **12.3 s** | 3119 (886) → 1515 (151) | passed (after retry) / passed | 6 |
| Mutual-Non-Disclosure-Agreeement-Template | 11 | 11.7 s → **7.3 s** | 1273 (524) → 896 (156) | passed / passed | 0 |
| Trade-Secret-Non-Disclosure-Agreement-NDA-Form | 12 | 10.7 s → **9.3 s** | 1205 (448) → 970 (215) | passed / passed | 4 |
| Trade-Secret-NDA-Extended | 65 | 44.5 s → **24.4 s** | 5325 (1609) → 2899 (451) | passed / passed | 15 |
| Trade-Secret-NDA-Extended-fillable | 64 | 45.4 s → **22.5 s** | 5905 (2307) → 2932 (518) | passed / passed | 20 |

Total latency: medium 138.8 s, low 75.8 s.

## Answers that differ

### Mutual-NDA-public-v1

| field | what | medium | low |
|---|---|---|---|
| f1 | key | agreement.purpose | agreement.purpose_of_disclosure |
| f3 | key | agreement.mnda_term_duration | agreement.mnda_term |
| f4 | key | agreement.mnda_term | agreement.period_for_sharing_confidential |
| f5 | key | agreement.term_of_confidentiality_duration | agreement.term_of_confidentiality |
| f7 | key | agreement.term_of_confidentiality | agreement.confidentiality_term_option |
| f10 | key | agreement.changes_to_standard_terms | agreement.modifications_to_standard_terms |

### Trade-Secret-Non-Disclosure-Agreement-NDA-Form

| field | what | medium | low |
|---|---|---|---|
| f2 | required | False | True |
| f4 | required | False | True |
| f5 | key | agreement.effective_date_of_agreement | agreement.effective_date |
| f6 | holds | text | state |

### Trade-Secret-NDA-Extended

| field | what | medium | low |
|---|---|---|---|
| f1 | filled_by | company | sender |
| f1 | key | company.party_name | agreement.company_legal_name |
| f2 | filled_by | company | sender |
| f2 | key | company.address | agreement.company_mailing_address |
| f16 | holds | amount_in_words | currency |
| f17 | key | agreement.consideration_amount_detail | agreement.consideration_payment_term |
| f19 | filled_by | company | sender |
| f19 | key | company.email | agreement.company_notices_email |
| f41 | depends_on | f33=checked | None |
| f42 | required | False | True |
| f44 | required | False | True |
| f45 | depends_on | f34=checked | None |
| f46 | depends_on | f34=checked | None |
| f51 | key | agreement.total_for_the_first_year | agreement.total_for_first_year |
| f61 | key | recipient.prior_knowledge_of_subject_matter | recipient.acknowledges_disclosure_of_prior |

### Trade-Secret-NDA-Extended-fillable

| field | what | medium | low |
|---|---|---|---|
| f16 | key | agreement.consideration_amount_in_dollars | agreement.consideration_amount |
| f17 | holds | number | text |
| f17 | key | agreement.consideration_amount_in_cents | agreement.consideration_payment_detail |
| f33 | required | False | True |
| f34 | required | False | True |
| f41 | depends_on | f33=checked | None |
| f42 | required | False | True |
| f45 | depends_on | f34=checked | None |
| f46 | depends_on | f34=checked | None |
| f52 | filled_by | sender | recipient |
| f52 | required | False | True |
| f52 | key | agreement.payment_method | recipient.payment_method |
| f53 | filled_by | sender | recipient |
| f53 | required | False | True |
| f53 | key | agreement.payment_method | recipient.payment_method |
| f54 | required | False | True |
| f55 | required | False | True |
| f56 | required | False | True |
| f59 | key | recipient.acknowledges_receipt_and_reading_of_comp | recipient.acknowledges_receipt_and_reading_of |
| f61 | key | recipient.disclosed_prior_knowledge_of_the_subject | recipient.acknowledges_prior_knowledge_disclosure |

