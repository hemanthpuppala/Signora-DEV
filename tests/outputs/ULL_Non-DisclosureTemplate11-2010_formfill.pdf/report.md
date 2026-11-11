# ULL_Non-DisclosureTemplate11-2010_formfill.pdf: field detection

**University of Louisiana at Lafayette Non-Disclosure Agreement**: A non-disclosure agreement between UL Lafayette and another party. It covers confidential information shared to evaluate a possible collaborative research arrangement and the parties’ confidentiality obligations. Both parties sign; neither is designated to countersign.

Uploader instructions: (none) · fields from: blanks

## Calls

| | |
|---|---|
| model, effort | `gpt-6-luna`, medium |
| read stage | 342 ms |
| AI latency | **43.3 s** over 2 call(s) |
| input tokens | 35075 (cached 16746) |
| output tokens | 5162 (reasoning 1221) |
| problems sent back | the description has 304 characters (at most 300) |
| problems left | none |
| flags | repaired |

## Roles (signing order)

1. Party 1 (`party_1`), signer
2. UL Lafayette (`ul_lafayette`), signer

## Fields (one per key)

| key | label | holds | filled by | req | depends on | places | ids | needs review |
|---|---|---|---|---|---|---|---|---|
| `party_1.party_name` | Other party legal name | party_name | Party 1 | yes | — | 9 | f1, f4, f7, f10, f13, f16, f19, f22, f25 |  |
| `party_1.other_party_type_or_legal_form` | Other party type or legal form | text | Party 1 | yes | — | 9 | f2, f5, f8, f11, f14, f17, f20, f23, f26 |  |
| `party_1.address` | Other party address | address | Party 1 | yes | — | 9 | f3, f6, f9, f12, f15, f18, f21, f24, f27 |  |
| `party_1.signature` | Other party signature | signature | Party 1 | yes | — | 1 | f28 |  |
| `ul_lafayette.signature` | UL Lafayette signature | signature | UL Lafayette | yes | — | 1 | f29 |  |
| `party_1.full_name` | Other party signer's printed name | full_name | Party 1 | yes | — | 1 | extra | placed after the words printed before it: check its position |
| `party_1.title` | Other party signer's title | title | Party 1 | no | — | 1 | extra | placed after the words printed before it: check its position |
| `party_1.date_signed` | Other party signing date | date_signed | Party 1 | yes | — | 1 | f30 |  |
| `ul_lafayette.date_signed` | UL Lafayette signing date | date_signed | UL Lafayette | yes | — | 1 | f31 |  |

## Not asked

none

## Notes

none
