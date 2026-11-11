# Unilateral Non-Disclosure Agreement.pdf: field detection

**Unilateral Non-Disclosure Agreement**: A unilateral non-disclosure agreement between a Company and a Recipient. It covers confidential information, the Recipient’s nondisclosure and nonuse obligations, survival, and governing law. The Recipient signs first and the Company countersigns.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 43 ms |
| AI latency | **16.5 s** over 1 call(s) |
| input tokens | 5360 (cached 0) |
| output tokens | 1689 (reasoning 512) |
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
| `agreement.agreement_date_year` | Agreement date: year | year | sender | yes | — | 1 | f3 |  |
| `agreement.company_legal_name` | Company legal name | party_name | sender | yes | — | 1 | f4 |  |
| `agreement.company_street_address` | Company street address | address | sender | yes | — | 1 | f5 |  |
| `agreement.company_city` | Company city | city | sender | yes | — | 1 | f6 |  |
| `agreement.company_state` | Company state | state | sender | yes | — | 1 | f7 |  |
| `recipient.party_name` | Recipient legal name | party_name | Recipient | yes | — | 1 | f8 |  |
| `recipient.address` | Recipient street address | address | Recipient | yes | — | 1 | f9 |  |
| `recipient.city` | Recipient city | city | Recipient | yes | — | 1 | f10 |  |
| `recipient.state` | Recipient state | state | Recipient | yes | — | 1 | f11 |  |
| `agreement.governing_law_state` | Governing law: state | state | sender | yes | — | 1 | f12 |  |
| `company.signature` | Company representative signature | signature | Company | yes | — | 1 | f13 |  |
| `company.date_signed` | Company signature date | date_signed | Company | yes | — | 1 | f14 |  |
| `company.full_name` | Company representative printed name | full_name | Company | yes | — | 1 | f15 |  |
| `recipient.signature` | Recipient signature | signature | Recipient | yes | — | 1 | f16 |  |
| `recipient.date_signed` | Recipient signature date | date_signed | Recipient | yes | — | 1 | f17 |  |
| `recipient.full_name` | Recipient printed name | full_name | Recipient | yes | — | 1 | f18 |  |

## Not asked

none

## Notes

none
