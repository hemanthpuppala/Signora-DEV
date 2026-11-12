# scan-Basic Non-Disclosure Agreement.pdf: field detection

**Basic Non-Disclosure Agreement**: A mutual nondisclosure agreement between a disclosing party and a receiving party. It covers confidential information, exclusions, handling and duration of confidentiality, and related terms. Both parties sign; neither is identified as the sender, so there is no designated countersignature.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 247 ms |
| AI latency | **12.7 s** over 1 call(s) |
| input tokens | 7641 (cached 0) |
| output tokens | 1412 (reasoning 508) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Disclosing Party (`disclosing_party`), signer
2. Receiving Party (`receiving_party`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.agreement_date` | Agreement date | date | sender | yes | — | 1 | f1 |  |
| `disclosing_party.party_name` | Disclosing Party name | party_name | Disclosing Party | yes | — | 1 | f2 |  |
| `disclosing_party.address` | Disclosing Party mailing address | address | Disclosing Party | yes | — | 1 | f3 |  |
| `receiving_party.party_name` | Receiving Party name | party_name | Receiving Party | yes | — | 1 | f4 |  |
| `receiving_party.address` | Receiving Party mailing address | address | Receiving Party | yes | — | 1 | f5 |  |
| `disclosing_party.signature` | Disclosing Party signature | signature | Disclosing Party | yes | — | 1 | f6 |  |
| `disclosing_party.full_name` | Disclosing Party typed or printed name | full_name | Disclosing Party | yes | — | 1 | f7 |  |
| `disclosing_party.date_signed` | Disclosing Party signing date | date_signed | Disclosing Party | yes | — | 1 | f8 |  |
| `receiving_party.signature` | Receiving Party signature | signature | Receiving Party | yes | — | 1 | f9 |  |
| `receiving_party.full_name` | Receiving Party typed or printed name | full_name | Receiving Party | yes | — | 1 | f10 |  |
| `receiving_party.date_signed` | Receiving Party signing date | date_signed | Receiving Party | yes | — | 1 | f11 |  |

## Not asked

none

## Notes

none
