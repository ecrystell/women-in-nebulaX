# Organiser submission playbook

Use this workflow only after a run has succeeded with zero local hard violations.
A locally clean result remains **unverified** until the organiser website gives
an authoritative decision.

1. Build or launch with `FOR_RAILS_BUILD_COMMIT` set to the full 40-character
   commit being tested. Package creation is intentionally blocked without it.
2. In the controller, run the eight CSVs, create a manual upload ZIP, and
   download it. The ZIP contains only the three official result CSVs and
   `submission-manifest.json` with input/output checksums and local preflight
   evidence.
3. Upload the three CSV files manually to the organiser website. The app does
   not automate or submit to that website.
4. Record attempt number, time, reported outcome, and a report or screenshot
   reference in the controller. Do not upload screenshots or paste the raw
   organiser report. Download the evidence JSON and retain it outside Git.

The service holds packages and evidence only until its process restarts. Never
commit hidden inputs, generated hidden outputs, screenshots, raw reports, or
their metadata. The table below is only a public-fixture template; leave hidden
instance attempts in your separately retained evidence JSON.

| Public fixture attempt | Scenario | Git commit | Outcome | Evidence JSON retained outside Git |
| --- | --- | --- | --- | --- |
| 1 | — | — | unused | — |
| 2 | — | — | unused | — |
| 3 | — | — | unused | — |
| 4 | — | — | unused | — |
| 5 | — | — | unused | — |

An organiser-reported “accepted” value is metadata only in R4.4. It does not
change the API report from `unverified` or set `feasible=true`; report parsing
and verified status await a supported organiser integration.
