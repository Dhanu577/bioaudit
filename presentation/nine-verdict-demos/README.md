# Bioaudit — nine-verdict demo pack

These are nine synthetic, minimal paper/code pairs. Each folder contains a `paper.txt` and one code file. Upload the two files from one folder to Bioaudit using **Source files**. Each pair is designed to yield exactly one finding with the listed verdict.

| Folder | Expected verdict | What it demonstrates |
|---|---|---|
| `01_match` | `MATCH` | Same parameter and value appear in paper and code. |
| `02_call_found` | `CALL_FOUND` | A named method call is present in code. |
| `03_not_found` | `NOT_FOUND` | No supporting code evidence for a named method is found. |
| `04_mismatch` | `MISMATCH` | A related parameter is present with a different value. |
| `05_result_needs_run` | `RESULT_NEEDS_RUN` | A reported performance result cannot be verified from static code. |
| `06_partial_match` | `PARTIAL_MATCH` | A matching value exists, but the same parameter also has a conflicting value. |
| `07_value_present_unrelated` | `VALUE_PRESENT_UNRELATED` | The value occurs in code, but under unrelated names/context. |
| `08_literal_found` | `LITERAL_FOUND` | The value appears inline in related code without a matching named constant. |
| `09_import_only` | `IMPORT_ONLY` | A relevant method is imported but not called. |

## Presentation caveat

These tiny fixtures are controlled demonstrations of verdict behavior, not real research results. Bioaudit uses static analysis and does not execute uploaded code. `MATCH` is evidence of a static correspondence, not proof that code ran correctly or that a scientific claim is valid. `RESULT_NEEDS_RUN` needs runtime/data-backed verification.
