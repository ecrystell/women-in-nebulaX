<#
Build and deploy For Rails without credentials in source control.
Run after copying cloud-run.env.example to a local ignored .env file and
setting BUILD_COMMIT to a full Git SHA. The commands are intentionally
explicit so an operator can review all cloud changes before execution.
#>
param(
  [Parameter(Mandatory = $true)][string]$BuildCommit,
  [string]$ProjectId = "qwiklabs-gcp-00-94397d478e88",
  [string]$Region = "us-central1",
  [string]$Service = "for-rails",
  [string]$Repository = "for-rails"
)

$ErrorActionPreference = "Stop"
if ($BuildCommit -notmatch '^[0-9a-f]{40}$') { throw "BuildCommit must be the full 40-character lowercase Git SHA." }
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$Service`:$BuildCommit"

gcloud builds submit --project $ProjectId --config cloudbuild.yaml --substitutions "_FOR_RAILS_BUILD_COMMIT=$BuildCommit,_IMAGE=$image"
gcloud run deploy $Service --project $ProjectId --region $Region --image $image --allow-unauthenticated --service-account "for-rails-runtime@$ProjectId.iam.gserviceaccount.com" --cpu 2 --memory 2Gi --concurrency 1 --max-instances 1 --min-instances 0 --timeout 600 --no-cpu-throttling --set-env-vars "FOR_RAILS_AI_ENABLED=true,FOR_RAILS_COOKIE_SECURE=true,FOR_RAILS_RUN_TTL_SECONDS=1800,FOR_RAILS_GCP_PROJECT=$ProjectId,FOR_RAILS_VERTEX_LOCATION=global,FOR_RAILS_GEMINI_MODEL=gemini-2.5-flash,FOR_RAILS_BUILD_COMMIT=$BuildCommit"
