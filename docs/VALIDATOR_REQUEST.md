# Organiser validator request

The public PS1 repository provides `01_data` and a sample answer key, but does not provide a runnable reference validator. For Rails deliberately marks all Phase 0 schedules as **unverified** until the organiser package is integrated.

Please provide:

1. The validator package/source or its approved distribution location and version.
2. The supported Python/runtime version and all installation dependencies.
3. The exact command line, including how the eight input CSVs and the three submission CSVs are passed.
4. The required input/output directory structure and scenario selection mechanism.
5. The machine-readable report format, exit-code semantics, and one expected report generated from the published sample submission.

Once supplied, the adapter in `backend/app/validation/adapter.py` will invoke it, translate its report into `ValidationReport`, and permit `status="verified"` only when the validator itself reports zero hard violations.
