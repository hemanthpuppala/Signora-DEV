# Detection scores

Against expected answers (`tests/expected/`); a draft scores the run against itself until the owner confirms it. `extra` counts fields found that are not expected (lower is better).

| document | expected | found | extra | holds | filled by | required | depends on | shared | roles |
|---|---|---|---|---|---|---|---|---|---|
| Mutual-NDA-public-v1.pdf | **draft** | 22/22 (100 %) | 0/22 (0 %) | 20/22 (91 %) | 22/22 (100 %) | 22/22 (100 %) | 22/22 (100 %) | — | 2/2 (100 %) |
| Mutual-Non-Disclosure-Agreeement-Template.docx | **draft** | 11/11 (100 %) | 0/11 (0 %) | 11/11 (100 %) | 1/11 (9 %) | 11/11 (100 %) | 11/11 (100 %) | — | 0/2 (0 %) |
| Mutual-Non-Disclosure-Agreeement-Template.pdf | **draft** | 11/11 (100 %) | 0/11 (0 %) | 11/11 (100 %) | 1/11 (9 %) | 11/11 (100 %) | 11/11 (100 %) | — | 0/2 (0 %) |
| Trade-Secret-NDA-Extended-fillable.pdf | **draft** | 64/64 (100 %) | 0/64 (0 %) | 61/64 (95 %) | 59/64 (92 %) | 63/64 (98 %) | 64/64 (100 %) | 7/7 (100 %) | 3/3 (100 %) |
| Trade-Secret-NDA-Extended.docx | **draft** | 65/65 (100 %) | 0/65 (0 %) | 64/65 (98 %) | 62/65 (95 %) | 59/65 (91 %) | 65/65 (100 %) | 7/7 (100 %) | 3/3 (100 %) |
| Trade-Secret-Non-Disclosure-Agreement-NDA-Form.docx | **draft** | 12/12 (100 %) | 0/12 (0 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | — | 2/2 (100 %) |
| Trade-Secret-Non-Disclosure-Agreement-NDA-Form.pdf | **draft** | 12/12 (100 %) | 0/12 (0 %) | 11/12 (92 %) | 12/12 (100 %) | 10/12 (83 %) | 12/12 (100 %) | — | 2/2 (100 %) |

## Injection test (Phase 5 LLD §3.5)

| hostile document | passed | agreement with the clean run | checks |
|---|---|---|---|
| Trade-Secret-NDA-Hostile-fillable.pdf | no | 59/64 (92 %) | no surge of sender fields |
| Trade-Secret-NDA-Hostile.docx | no | 64/65 (98 %) | same parties and kinds |
