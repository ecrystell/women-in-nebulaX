# Hidden scheduling-data policy

## Data lifetime

An uploaded instance, its prepared representation, candidate schedule, exports,
submission package and organiser metadata exist only in the Cloud Run process
that owns the live run. They expire after 30 minutes without access and are
deleted on expiry, process restart, revision rollout or scale-down. They are
not written to Git, Cloud Storage, Firestore, a database, or application logs.

## Browser access

Creating a run issues a per-run `HttpOnly`, `Secure`, `SameSite=Lax` cookie in
production. Every read, export, package, evidence and recovery route requires
that cookie. A run ID alone is not enough to retrieve hidden data. Dynamic
responses use `Cache-Control: no-store` and do not put tokens in URLs.

## Gemini boundary

The copilot uses Vertex AI's global endpoint only after the API has built one
of three bounded evidence envelopes: one requested activity, at most ten
capacity hotspots, or a compact handover summary. It never receives:

- raw eight-CSV inputs, CSV bytes, exports or submission ZIPs;
- a complete schedule, all activity rows, checksums or organiser metadata;
- user-uploaded screenshots, organiser reports or a free-text disruption;
- credentials, service-account keys, or API keys.

Gemini is a narrative renderer. It cannot invoke the solver, local validator,
exporter, submission workflow, recovery endpoint, or `ScenarioChange` code.
Every answer contains its exact evidence envelope and a service-generated
notice that organiser verification remains unavailable or unverified.

## Cloud controls

Cloud Run uses a dedicated `railaccess-runtime` service account with only the
Vertex AI user permission. Authentication uses Cloud Run Application Default
Credentials; no API key is created. The public hackathon service is limited to
one concurrent request and one instance, so it intentionally offers no durable
run history. Application logs retain operational request IDs and error codes,
not request bodies, evidence payloads, Gemini prompts/responses, CSV content or
exports.

The deployment uses instance-based CPU allocation while the single instance is
alive. This is required for the in-memory background solver to complete after
the upload response is returned; `min-instances=0` still permits scale-down,
which removes all run data by design.
