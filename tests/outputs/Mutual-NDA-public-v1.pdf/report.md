# Mutual-NDA-public-v1.pdf: field detection

**Mutual Non-Disclosure Agreement**: A mutual non-disclosure agreement between Party 1 and Party 2. It covers permitted use, effective date and term, confidentiality duration, governing law, jurisdiction and changes to the standard terms. Both parties sign; no countersignature.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 136 ms |
| AI latency | **18.7 s** over 1 call(s) |
| input tokens | 4644 (cached 0) |
| output tokens | 2126 (reasoning 758) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Party 1 (`party_1`), signer
2. Party 2 (`party_2`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.purpose_for_using_confidential` | Purpose for using Confidential Information | text | sender | yes | — | 1 | f1 |  |
| `agreement.effective_date` | Effective date | date | sender | yes | — | 1 | f2 |  |
| `agreement.mnda_term_duration` | MNDA term duration | text | sender | yes | agreement.period_for_sharing_confidential = Choice1 (layout) | 1 | f3 |  |
| `agreement.period_for_sharing_confidential` | Period for sharing Confidential Information | choice | sender | yes | — | 2 | f4 |  |
| `agreement.term_of_confidentiality_duration` | Term of confidentiality duration | text | sender | yes | agreement.term_of_confidentiality_option = Choice1 (layout) | 1 | f5 |  |
| `agreement.start_point_for_confidentiality_term` | Start point for confidentiality term | choice | sender | yes | agreement.term_of_confidentiality_option = Choice1 (layout) | 2 | f6 |  |
| `agreement.term_of_confidentiality_option` | Term of confidentiality option | choice | sender | yes | — | 2 | f7 |  |
| `agreement.governing_law_state` | Governing law state | state | sender | yes | — | 1 | f8 |  |
| `agreement.jurisdiction_location` | Jurisdiction location | text | sender | yes | — | 1 | f9 |  |
| `agreement.changes_to_standard_terms` | Changes to Standard Terms | text | sender | no | — | 1 | f10 |  |
| `party_1.signature` | Party 1 signature | signature | Party 1 | yes | — | 1 | f11 |  |
| `party_2.signature` | Party 2 signature | signature | Party 2 | yes | — | 1 | f12 |  |
| `party_1.full_name` | Party 1 print name | full_name | Party 1 | yes | — | 1 | f13 |  |
| `party_2.full_name` | Party 2 print name | full_name | Party 2 | yes | — | 1 | f14 |  |
| `party_1.title` | Party 1 title | title | Party 1 | no | — | 1 | f15 |  |
| `party_2.title` | Party 2 title | title | Party 2 | no | — | 1 | f16 |  |
| `party_1.company` | Party 1 company | company | Party 1 | no | — | 1 | f17 |  |
| `party_2.company` | Party 2 company | company | Party 2 | no | — | 1 | f18 |  |
| `party_1.address` | Party 1 notice address | address | Party 1 | yes | — | 1 | f19 |  |
| `party_2.address` | Party 2 notice address | address | Party 2 | yes | — | 1 | f20 |  |
| `party_1.date_signed` | Party 1 signing date | date_signed | Party 1 | yes | — | 1 | f21 |  |
| `party_2.date_signed` | Party 2 signing date | date_signed | Party 2 | yes | — | 1 | f22 |  |

## Not asked

none

## Notes

none
