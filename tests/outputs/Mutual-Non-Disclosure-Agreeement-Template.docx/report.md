# Mutual-Non-Disclosure-Agreeement-Template.docx: field detection

**Mutual Non-Disclosure Agreement**: A mutual non-disclosure agreement between the first party and the second party. It covers confidential information, how it must be protected and handled, exclusions, and the agreement term. Both parties sign; no countersignature.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 41 ms |
| AI latency | **10.8 s** over 1 call(s) |
| input tokens | 4878 (cached 0) |
| output tokens | 1130 (reasoning 404) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. First Party (`first_party`), signer
2. Second Party (`second_party`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `first_party.party_name` | First party legal name | party_name | First Party | yes | — | 1 | f1 |  |
| `first_party.address` | First party mailing address | address | First Party | yes | — | 1 | f2 |  |
| `second_party.party_name` | Second party legal name | party_name | Second Party | yes | — | 1 | f3 |  |
| `second_party.address` | Second party mailing address | address | Second Party | yes | — | 1 | f4 |  |
| `agreement.confidentiality_period_in_years` | Confidentiality period in years | number | sender | yes | — | 1 | f5 |  |
| `first_party.signature` | First party signature | signature | First Party | yes | — | 1 | f6 |  |
| `first_party.full_name` | First party printed name | full_name | First Party | yes | — | 1 | f7 |  |
| `first_party.date_signed` | First party signing date | date_signed | First Party | yes | — | 1 | f8 |  |
| `second_party.signature` | Second party signature | signature | Second Party | yes | — | 1 | f9 |  |
| `second_party.full_name` | Second party printed name | full_name | Second Party | yes | — | 1 | f10 |  |
| `second_party.date_signed` | Second party signing date | date_signed | Second Party | yes | — | 1 | f11 |  |

## Not asked

none

## Notes

none
