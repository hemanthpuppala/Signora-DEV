# real-Unilateral Non-Disclosure Agreement.pdf: field detection

**Unilateral Non-Disclosure Agreement**: A unilateral non-disclosure agreement between a Company and a Recipient. It covers confidential information, nondisclosure and nonuse obligations, governing law, and related terms. The Recipient signs and the Company countersigns.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 306 ms |
| AI latency | **30.2 s** over 1 call(s) |
| input tokens | 7903 (cached 0) |
| output tokens | 2496 (reasoning 1180) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Recipient (`recipient`), signer
2. Company (`company`), countersigner

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.agreement_date_day` | Agreement date: day | day | sender | yes | — | 1 | f1 |  |
| `company.party_name` | Company legal name | party_name | Company | yes | — | 1 | f2 |  |
| `agreement.agreement_date_last_two_digits_of_year` | Agreement date: last two digits of year | year | sender | yes | — | 1 | f4 |  |
| `agreement.agreement_date_month` | Agreement date: month | month | sender | yes | — | 1 | f3 |  |
| `company.city` | Company city | city | Company | yes | — | 1 | f5 |  |
| `company.address` | Company address | address | Company | yes | — | 1 | f6 |  |
| `recipient.party_name` | Recipient legal name | party_name | Recipient | yes | — | 1 | f7 |  |
| `company.state` | Company state | state | Company | yes | — | 1 | f8 |  |
| `recipient.city` | Recipient city | city | Recipient | yes | — | 1 | f9 |  |
| `recipient.address` | Recipient address | address | Recipient | yes | — | 1 | f10 |  |
| `recipient.state` | Recipient state | state | Recipient | yes | — | 1 | f11 |  |
| `agreement.governing_law_state` | Governing law: state | state | sender | yes | — | 1 | f12 |  |
| `company.date_signed` | Company representative signing date | date_signed | Company | yes | — | 1 | f13 |  |
| `company.signature` | Company representative signature | signature | Company | yes | — | 1 | f14 |  |
| `company.full_name` | Company representative printed name | full_name | Company | yes | — | 1 | f15 |  |
| `recipient.date_signed` | Recipient signing date | date_signed | Recipient | yes | — | 1 | f16 |  |
| `recipient.signature` | Recipient signature | signature | Recipient | yes | — | 1 | f17 |  |
| `recipient.full_name` | Recipient printed name | full_name | Recipient | yes | — | 1 | f18 |  |

## Not asked

none

## Notes

none
