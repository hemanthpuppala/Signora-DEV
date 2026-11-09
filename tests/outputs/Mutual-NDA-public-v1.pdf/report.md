# Mutual-NDA-public-v1.pdf: field detection

**Mutual Non-Disclosure Agreement**: A mutual non-disclosure agreement between two parties. It covers the purpose and term of sharing information, confidentiality duration, governing law, jurisdiction and changes to the standard terms. Both parties sign; no countersignature.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 150 ms |
| AI latency | **17.6 s** over 1 call(s) |
| input tokens | 4467 (cached 0) |
| output tokens | 2130 (reasoning 758) |
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
| `agreement.confidentiality_term_duration` | Confidentiality term duration | text | sender | yes | agreement.term_of_confidentiality = Choice1 (layout) | 1 | f5 |  |
| `agreement.confidentiality_term_starts_from` | Confidentiality term starts from | choice | sender | yes | agreement.term_of_confidentiality = Choice1 (layout) | 2 | f6 |  |
| `agreement.term_of_confidentiality` | Term of confidentiality | choice | sender | yes | — | 2 | f7 |  |
| `agreement.governing_law_state` | Governing law state | state | sender | yes | — | 1 | f8 |  |
| `agreement.jurisdiction_state_and_or_county` | Jurisdiction state and/or county | text | sender | yes | — | 1 | f9 |  |
| `agreement.changes_to_standard_terms` | Changes to Standard Terms | text | sender | no | — | 1 | f10 |  |
| `party_1.signature` | Party 1 signature | signature | Party 1 | yes | — | 1 | f11 |  |
| `party_2.signature` | Party 2 signature | signature | Party 2 | yes | — | 1 | f12 |  |
| `party_1.full_name` | Party 1 print name | full_name | Party 1 | yes | — | 1 | f13 |  |
| `party_2.full_name` | Party 2 print name | full_name | Party 2 | yes | — | 1 | f14 |  |
| `party_1.title` | Party 1 title | title | Party 1 | no | — | 1 | f15 |  |
| `party_2.title` | Party 2 title | title | Party 2 | no | — | 1 | f16 |  |
| `party_1.company` | Party 1 company | company | Party 1 | no | — | 1 | f17 |  |
| `party_2.company` | Party 2 company | company | Party 2 | no | — | 1 | f18 |  |
| `party_1.notice_address_or_email` | Party 1 notice address or email | text | Party 1 | yes | — | 1 | f19 |  |
| `party_2.notice_address_or_email` | Party 2 notice address or email | text | Party 2 | yes | — | 1 | f20 |  |
| `party_1.date_signed` | Party 1 signing date | date_signed | Party 1 | yes | — | 1 | f21 |  |
| `party_2.date_signed` | Party 2 signing date | date_signed | Party 2 | yes | — | 1 | f22 |  |

## Not asked

none

## Notes

none
