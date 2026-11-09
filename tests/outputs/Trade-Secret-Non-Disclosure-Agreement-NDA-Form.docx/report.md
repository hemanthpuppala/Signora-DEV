# Trade-Secret-Non-Disclosure-Agreement-NDA-Form.docx: field detection

**Trade Secret Non-Disclosure Agreement**: A trade secret non-disclosure agreement between a Company and a Recipient. It covers confidential information, confidentiality and non-use obligations, exclusions, indemnification, governing law and other terms. The Recipient signs first, and the Company countersigns.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 59 ms |
| AI latency | **8.6 s** over 1 call(s) |
| input tokens | 7203 (cached 0) |
| output tokens | 1044 (reasoning 285) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Recipient (`recipient`), signer
2. Company (`company`), countersigner

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.company_legal_name` | Company legal name | party_name | sender | yes | — | 1 | f1 |  |
| `agreement.company_mailing_address` | Company mailing address | address | sender | yes | — | 1 | f2 |  |
| `recipient.party_name` | Recipient legal name | party_name | Recipient | yes | — | 1 | f3 |  |
| `recipient.address` | Recipient mailing address | address | Recipient | yes | — | 1 | f4 |  |
| `agreement.effective_date_of_agreement` | Effective date of agreement | date | sender | yes | — | 1 | f5 |  |
| `agreement.governing_law_state` | Governing law state | state | sender | yes | — | 1 | f6 |  |
| `recipient.signature` | Recipient signature | signature | Recipient | yes | — | 1 | f7 |  |
| `recipient.date_signed` | Recipient signing date | date_signed | Recipient | yes | — | 1 | f8 |  |
| `recipient.full_name` | Recipient printed name | full_name | Recipient | yes | — | 1 | f9 |  |
| `company.signature` | Company signature | signature | Company | yes | — | 1 | f10 |  |
| `company.date_signed` | Company signing date | date_signed | Company | yes | — | 1 | f11 |  |
| `company.full_name` | Company representative printed name | full_name | Company | yes | — | 1 | f12 |  |

## Not asked

none

## Notes

none
