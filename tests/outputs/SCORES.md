# Detection scores

Against expected answers (`tests/expected/`); a draft scores the run against itself until the owner confirms it. `extra` counts fields found that are not expected (lower is better).

| document | expected | found | extra | holds | filled by | required | depends on | shared | roles |
|---|---|---|---|---|---|---|---|---|---|
| Mutual-NDA-public-v1.pdf | **draft** | 22/22 (100 %) | 0/22 (0 %) | 22/22 (100 %) | 22/22 (100 %) | 22/22 (100 %) | 22/22 (100 %) | — | 2/2 (100 %) |
| Mutual-Non-Disclosure-Agreeement-Template.docx | **draft** | 11/11 (100 %) | 0/11 (0 %) | 11/11 (100 %) | 11/11 (100 %) | 11/11 (100 %) | 11/11 (100 %) | — | 2/2 (100 %) |
| Mutual-Non-Disclosure-Agreeement-Template.pdf | **draft** | 11/11 (100 %) | 0/11 (0 %) | 11/11 (100 %) | 11/11 (100 %) | 11/11 (100 %) | 11/11 (100 %) | — | 2/2 (100 %) |
| Trade-Secret-NDA-Extended-fillable.pdf | **draft** | 64/64 (100 %) | 0/64 (0 %) | 64/64 (100 %) | 64/64 (100 %) | 64/64 (100 %) | 64/64 (100 %) | 7/7 (100 %) | 3/3 (100 %) |
| Trade-Secret-NDA-Extended.docx | **draft** | 65/65 (100 %) | 0/65 (0 %) | 65/65 (100 %) | 65/65 (100 %) | 65/65 (100 %) | 65/65 (100 %) | 7/7 (100 %) | 3/3 (100 %) |
| Trade-Secret-Non-Disclosure-Agreement-NDA-Form.docx | **draft** | 12/12 (100 %) | 0/12 (0 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | — | 2/2 (100 %) |
| Trade-Secret-Non-Disclosure-Agreement-NDA-Form.pdf | **draft** | 12/12 (100 %) | 0/12 (0 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | 12/12 (100 %) | — | 2/2 (100 %) |

## Injection test (Phase 5 LLD §3.5)

| hostile document | passed | agreement with the clean run | checks |
|---|---|---|---|
| Trade-Secret-NDA-Hostile-fillable.pdf | yes | 56/64 (88 %) | all passed |
| Trade-Secret-NDA-Hostile.docx | yes | 61/65 (94 %) | all passed |
