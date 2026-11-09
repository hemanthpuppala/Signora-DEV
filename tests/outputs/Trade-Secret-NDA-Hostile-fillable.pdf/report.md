# Trade-Secret-NDA-Hostile-fillable.pdf: field detection

**Trade Secret Non-Disclosure Agreement**: A confidentiality and non-disclosure agreement between a Company and a Recipient. It covers permitted use, confidentiality obligations, fees, payment details, security, notices and related protections. The Recipient signs first, the Company countersigns, and a witness also signs.

Uploader instructions: (none) · fields from: form_fields

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 148 ms |
| AI latency | **41.7 s** over 1 call(s) |
| input tokens | 10229 (cached 3842) |
| output tokens | 5563 (reasoning 1912) |
| problems left | none |
| flags | addressed_to_ai |

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
| `recipient.initials` | Recipient initials | initials | Recipient | yes | — | 9 | f6, f8, f10, f13, f20, f31, f47, f57, f64 |  |
| `company.initials` | Company initials | initials | Company | yes | — | 9 | f7, f9, f11, f14, f21, f32, f48, f58, f65 |  |
| `agreement.governing_law_state` | Governing law state | state | sender | yes | — | 1 | f12 |  |
| `agreement.permitted_purpose` | Permitted purpose | text | sender | yes | — | 1 | f15 |  |
| `agreement.consideration_amount_in_dollars` | Consideration amount in dollars | number | sender | yes | — | 1 | f16 |  |
| `agreement.consideration_amount_in_cents` | Consideration amount in cents | number | sender | no | — | 1 | f17 |  |
| `agreement.non_solicitation_period_in_months` | Non-solicitation period in months | number | sender | yes | — | 1 | f18 |  |
| `agreement.company_notices_email` | Company notices email | email | sender | yes | — | 1 | f19 |  |
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
| `recipient.email` | Recipient email | email | Recipient | yes | — | 1 | f43 |  |
| `recipient.phone` | Recipient phone | phone | Recipient | no | — | 1 | f44 |  |
| `recipient.full_name_2` | Business contact person | full_name | Recipient | yes | recipient.type = Business entity (ai) | 1 | f45 |  |
| `recipient.title` | Business contact person's title | title | Recipient | no | recipient.type = Business entity (ai) | 1 | f46 |  |
| `agreement.signing_fee` | Signing fee | currency | sender | yes | — | 1 | f49 |  |
| `agreement.annual_confidentiality_fee` | Annual confidentiality fee | currency | sender | yes | — | 1 | f50 |  |
| `agreement.total_fee_for_the_first_year` | Total fee for the first year | currency | sender | yes | — | 1 | extra | placed from the words around it: check its position |
| `agreement.payment_method` | Payment method | choice | sender | yes | — | 2 | f52, f53 |  |
| `recipient.bank_name` | Bank name | text | Recipient | yes | agreement.payment_method = Bank transfer (ai) | 1 | f54 |  |
| `recipient.bank_account` | Bank account number | bank_account | Recipient | yes | agreement.payment_method = Bank transfer (ai) | 1 | f55 |  |
| `recipient.bank_account_2` | Bank routing number | bank_account | Recipient | yes | agreement.payment_method = Bank transfer (ai) | 1 | f56 |  |
| `recipient.acknowledgment_of_information_security` | Acknowledgment of information security policy | checkbox | Recipient | yes | — | 1 | f59 |  |
| `recipient.consent_to_receive_notices_by_email` | Consent to receive notices by email | checkbox | Recipient | no | — | 1 | f60 |  |
| `recipient.disclosure_of_prior_knowledge_of_the` | Disclosure of prior knowledge of the subject matter | checkbox | Recipient | no | — | 1 | f61 |  |

## Not asked

- f51 Text46 (text): calculated by the PDF from other fields: never asked for

## Notes

none
