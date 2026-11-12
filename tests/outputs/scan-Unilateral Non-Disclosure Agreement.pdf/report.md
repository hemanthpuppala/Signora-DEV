# scan-Unilateral Non-Disclosure Agreement.pdf: field detection

**Unilateral Non-Disclosure Agreement**: A unilateral non-disclosure agreement between a Company and a Recipient. It covers confidential information, nondisclosure and nonuse obligations, survival, governing law and remedies. The Recipient signs first and the Company countersigns.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 329 ms |
| AI latency | **24.3 s** over 1 call(s) |
| input tokens | 7896 (cached 0) |
| output tokens | 2546 (reasoning 1228) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Recipient (`recipient`), signer
2. Company (`company`), countersigner

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.agreement_date_day` | Agreement date: day | day | sender | yes | — | 1 | f1 |  |
| `agreement.agreement_date_month` | Agreement date: month | month | sender | yes | — | 1 | f2 |  |
| `agreement.agreement_date_last_two_digits_of_year` | Agreement date: last two digits of year | year | sender | yes | — | 1 | f3 |  |
| `company.party_name` | Company legal name | party_name | Company | yes | — | 1 | f4 |  |
| `company.address` | Company street address | address | Company | no | — | 1 | f5 |  |
| `company.city` | Company city | city | Company | no | — | 1 | f6 |  |
| `company.state` | Company state | state | Company | no | — | 1 | f7 |  |
| `recipient.party_name` | Recipient legal name | party_name | Recipient | yes | — | 1 | f8 |  |
| `recipient.address` | Recipient street address | address | Recipient | no | — | 1 | f9 |  |
| `recipient.city` | Recipient city | city | Recipient | no | — | 1 | f10 |  |
| `recipient.state` | Recipient state | state | Recipient | no | — | 1 | f11 |  |
| `agreement.governing_law_state` | Governing law: state | state | sender | yes | — | 1 | f12 |  |
| `company.signature` | Company representative signature | signature | Company | yes | — | 1 | f13 |  |
| `company.date_signed` | Company representative signing date | date_signed | Company | yes | — | 1 | f14 |  |
| `company.full_name` | Company representative printed name | full_name | Company | no | — | 1 | f15 |  |
| `recipient.signature` | Recipient signature | signature | Recipient | yes | — | 1 | f16 |  |
| `recipient.date_signed` | Recipient signing date | date_signed | Recipient | yes | — | 1 | f17 |  |
| `recipient.full_name` | Recipient printed name | full_name | Recipient | no | — | 1 | f18 |  |

## Not asked

none

## Notes

none
