# Mutual-Non-Disclosure-Agreeement-Template.pdf: field detection

**Mutual Non-Disclosure Agreement**: A mutual non-disclosure agreement between two parties. It covers confidential information, restrictions on disclosure, and the protection period. Both parties sign; there is no countersignature.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 47 ms |
| AI latency | **12.4 s** over 1 call(s) |
| input tokens | 5131 (cached 3365) |
| output tokens | 1308 (reasoning 565) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Party 1 (`party_1`), signer
2. Party 2 (`party_2`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `party_1.party_name` | 1st Party name | party_name | Party 1 | yes | — | 1 | f1 |  |
| `party_1.address` | 1st Party mailing address | address | Party 1 | yes | — | 1 | f2 |  |
| `party_2.party_name` | 2nd Party name | party_name | Party 2 | yes | — | 1 | f3 |  |
| `party_2.address` | 2nd Party mailing address | address | Party 2 | yes | — | 1 | f4 |  |
| `agreement.confidentiality_period_in_years` | Confidentiality period in years | number | sender | yes | — | 1 | f5 |  |
| `party_1.signature` | 1st Party signature | signature | Party 1 | yes | — | 1 | f6 |  |
| `party_1.full_name` | 1st Party printed name | full_name | Party 1 | yes | — | 1 | f7 |  |
| `party_1.date_signed` | 1st Party signing date | date_signed | Party 1 | yes | — | 1 | f8 |  |
| `party_2.signature` | 2nd Party signature | signature | Party 2 | yes | — | 1 | f9 |  |
| `party_2.full_name` | 2nd Party printed name | full_name | Party 2 | yes | — | 1 | f10 |  |
| `party_2.date_signed` | 2nd Party signing date | date_signed | Party 2 | yes | — | 1 | f11 |  |

## Not asked

none

## Notes

none
