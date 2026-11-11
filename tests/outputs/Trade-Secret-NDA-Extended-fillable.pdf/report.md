# Trade-Secret-NDA-Extended-fillable.pdf: field detection

**Trade Secret Non-Disclosure Agreement**: A trade-secret nondisclosure agreement between Company and Recipient. It covers permitted use, confidentiality, fees, non-solicitation, security, notices, payment details and acknowledgements. Recipient signs with a witness, and Company countersigns.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 166 ms |
| AI latency | **68.0 s** over 1 call(s) |
| input tokens | 10795 (cached 10792) |
| output tokens | 6655 (reasoning 1721) |
| problems left | none |
| flags | none |

## Roles (signing order)

1. Recipient (`recipient`), signer
2. Witness (`witness`), signer
3. Company (`company`), countersigner

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `agreement.company_legal_name` | Company legal name | party_name | sender | yes | — | 1 | f1 |  |
| `agreement.company_mailing_address` | Company mailing address | address | sender | yes | — | 1 | f2 |  |
| `recipient.party_name` | Recipient legal name | party_name | Recipient | yes | — | 2 | f3, f35 |  |
| `recipient.address` | Recipient mailing address | address | Recipient | yes | — | 1 | f4 |  |
| `agreement.effective_date` | Effective date | date | sender | yes | — | 1 | f5 |  |
| `recipient.initials` | Recipient initials, page 1 | initials | Recipient | yes | — | 9 | f6, f8, f10, f13, f20, f31, f47, f57, f64 |  |
| `company.initials` | Company initials, page 1 | initials | Company | yes | — | 9 | f7, f9, f11, f14, f21, f32, f48, f58, f65 |  |
| `agreement.governing_law_state` | Governing law state | text | sender | yes | — | 1 | f12 |  |
| `agreement.permitted_purpose` | Permitted purpose | text | sender | yes | — | 1 | f15 |  |
| `agreement.consideration_amount_in_words` | Consideration amount in words | amount_in_words | sender | yes | — | 1 | f16 |  |
| `agreement.consideration_amount_in_figures` | Consideration amount in figures | currency | sender | yes | — | 1 | f17 |  |
| `agreement.non_solicitation_period_in_months` | Non-solicitation period in months | number | sender | yes | — | 1 | f18 |  |
| `agreement.company_notice_email_address` | Company notice email address | email | sender | yes | — | 1 | f19 |  |
| `recipient.signature` | Recipient signature | signature | Recipient | yes | — | 2 | f22, f62 |  |
| `recipient.date_signed` | Recipient signing date | date_signed | Recipient | yes | — | 2 | f23, f63 |  |
| `recipient.full_name` | Recipient printed name | full_name | Recipient | yes | — | 1 | f24 |  |
| `company.signature` | Company signature | signature | Company | yes | — | 1 | f25 |  |
| `company.date_signed` | Company signing date | date_signed | Company | yes | — | 1 | f26 |  |
| `company.full_name` | Company representative printed name | full_name | Company | yes | — | 1 | f27 |  |
| `witness.signature` | Witness signature | signature | Witness | yes | — | 1 | f28 |  |
| `witness.date_signed` | Witness signing date | date_signed | Witness | yes | — | 1 | f29 |  |
| `witness.full_name` | Witness printed name | full_name | Witness | yes | — | 1 | f30 |  |
| `recipient.type` | Recipient type | choice | Recipient | yes | — | 2 | f33, f34 |  |
| `recipient.address_2` | Recipient street address | address | Recipient | yes | — | 1 | f36 |  |
| `recipient.city` | Recipient city | city | Recipient | yes | — | 1 | f37 |  |
| `recipient.state` | Recipient state | state | Recipient | yes | — | 1 | f38 |  |
| `recipient.postal_code` | Recipient ZIP code | postal_code | Recipient | yes | — | 1 | f39 |  |
| `recipient.country` | Recipient country | country | Recipient | yes | — | 1 | f40 |  |
| `recipient.date_of_birth` | Recipient date of birth | date_of_birth | Recipient | yes | recipient.type = Individual (ai) | 1 | f41 |  |
| `recipient.tax_id` | Recipient taxpayer identification number | tax_id | Recipient | yes | — | 1 | f42 |  |
| `recipient.email` | Recipient email address | email | Recipient | yes | — | 1 | f43 |  |
| `recipient.phone` | Recipient phone number | phone | Recipient | no | — | 1 | f44 |  |
| `recipient.full_name_2` | Recipient business contact person | full_name | Recipient | yes | recipient.type = Business entity (ai) | 1 | f45 |  |
| `recipient.title` | Recipient business contact title | title | Recipient | no | recipient.type = Business entity (ai) | 1 | f46 |  |
| `agreement.signing_fee` | Signing fee | currency | sender | yes | — | 1 | f49 |  |
| `agreement.annual_confidentiality_fee` | Annual confidentiality fee | currency | sender | yes | — | 1 | f50 |  |
| `agreement.payment_method` | Payment method | choice | sender | yes | — | 2 | f52, f53 |  |
| `recipient.bank_name` | Recipient bank name | text | Recipient | yes | — | 1 | f54 | its condition was on a field someone else fills; check when it applies |
| `recipient.bank_account` | Recipient bank account number | bank_account | Recipient | yes | — | 1 | f55 | its condition was on a field someone else fills; check when it applies |
| `recipient.bank_account_2` | Recipient bank routing number | bank_account | Recipient | yes | — | 1 | f56 | its condition was on a field someone else fills; check when it applies |
| `recipient.acknowledgment_of_receipt_and_reading` | Acknowledgment of receipt and reading of Company Information Security Policy | checkbox | Recipient | no | — | 1 | f59 |  |
| `recipient.consent_to_receive_notices_by_email` | Consent to receive notices by email | checkbox | Recipient | no | — | 1 | f60 |  |
| `recipient.disclosure_of_prior_knowledge_of_the` | Disclosure of prior knowledge of the Subject Matter | checkbox | Recipient | no | — | 1 | f61 |  |

## Not asked

- f51 Text46 (text): calculated by the PDF from other fields: never asked for

## Notes

- extra field 'Total for the first year' dropped: a form field already sits after its words: that field is the blank
