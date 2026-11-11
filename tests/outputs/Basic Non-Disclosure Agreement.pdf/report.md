# Basic Non-Disclosure Agreement.pdf: field detection

**Basic Non-Disclosure Agreement**: A non-disclosure agreement between a disclosing party and a receiving party. It covers confidential information, permitted exclusions, confidentiality obligations and the duration of those obligations. Both parties sign; no countersignature is specified.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 72 ms |
| AI latency | **14.3 s** over 1 call(s) |
| input tokens | 5501 (cached 0) |
| output tokens | 1402 (reasoning 512) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Disclosing Party (`disclosing_party`), signer
2. Receiving Party (`receiving_party`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.agreement_date` | Agreement date | date | sender | yes | — | 1 | f1 |  |
| `disclosing_party.party_name` | Disclosing party name | party_name | Disclosing Party | yes | — | 1 | f2 |  |
| `disclosing_party.address` | Disclosing party mailing address | address | Disclosing Party | yes | — | 1 | f3 |  |
| `receiving_party.party_name` | Receiving party name | party_name | Receiving Party | yes | — | 1 | f4 |  |
| `receiving_party.address` | Receiving party mailing address | address | Receiving Party | yes | — | 1 | f5 |  |
| `disclosing_party.signature` | Disclosing party signature | signature | Disclosing Party | yes | — | 1 | f6 |  |
| `disclosing_party.full_name` | Disclosing party printed name | full_name | Disclosing Party | yes | — | 1 | f7 |  |
| `disclosing_party.date_signed` | Disclosing party signing date | date_signed | Disclosing Party | yes | — | 1 | f8 |  |
| `receiving_party.signature` | Receiving party signature | signature | Receiving Party | yes | — | 1 | f9 |  |
| `receiving_party.full_name` | Receiving party printed name | full_name | Receiving Party | yes | — | 1 | f10 |  |
| `receiving_party.date_signed` | Receiving party signing date | date_signed | Receiving Party | yes | — | 1 | f11 |  |

## Not asked

none

## Notes

none
