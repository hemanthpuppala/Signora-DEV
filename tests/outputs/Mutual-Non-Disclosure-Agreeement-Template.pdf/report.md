# Mutual-Non-Disclosure-Agreeement-Template.pdf: field detection

**Mutual Non-Disclosure Agreement**: A mutual non-disclosure agreement between two parties. It covers identifying the parties, handling confidential information, exclusions, and the period of confidentiality. Both parties sign; there is no countersignature.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 101 ms |
| AI latency | **15.3 s** over 1 call(s) |
| input tokens | 4954 (cached 0) |
| output tokens | 1480 (reasoning 753) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. First Party (`first_party`), signer
2. Second Party (`second_party`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `first_party.party_name` | First Party legal name | party_name | First Party | yes | — | 1 | f1 |  |
| `first_party.address` | First Party mailing address | address | First Party | yes | — | 1 | f2 |  |
| `second_party.party_name` | Second Party legal name | party_name | Second Party | yes | — | 1 | f3 |  |
| `second_party.address` | Second Party mailing address | address | Second Party | yes | — | 1 | f4 |  |
| `agreement.confidentiality_period_in_years` | Confidentiality period in years | number | sender | yes | — | 1 | f5 |  |
| `first_party.signature` | First Party signature | signature | First Party | yes | — | 1 | f6 |  |
| `first_party.full_name` | First Party print name | full_name | First Party | yes | — | 1 | f7 |  |
| `first_party.date_signed` | First Party signing date | date_signed | First Party | yes | — | 1 | f8 |  |
| `second_party.signature` | Second Party signature | signature | Second Party | yes | — | 1 | f9 |  |
| `second_party.full_name` | Second Party print name | full_name | Second Party | yes | — | 1 | f10 |  |
| `second_party.date_signed` | Second Party signing date | date_signed | Second Party | yes | — | 1 | f11 |  |

## Not asked

none

## Notes

none
