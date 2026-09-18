<#
Build and deploy RailAccess AI without credentials in source control.
Run after copying cloud-run.env.example to a local ignored .env file and
setting BUILD_COMMIT to a full Git SHA. The commands are intentionally
explicit so an operator can review all cloud changes before execution.
#>
param(
  [Parameter(Mandatory = $true)][string]$BuildCommit,
  [string]$ProjectId = "qwiklabs-gcp-00-94397d478e88",
  [string]$Region = "us-central1",
  [string]$Service = "railaccess-ai",
  [string]$Repository = "railaccess"
)

$ErrorActionPreference = "Stop"
if ($BuildCommit -notmatch '^[0-9a-f]{40}$') { throw "BuildCommit must be the full 40-character lowercase Git SHA." }
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$Service`:$BuildCommit"

gcloud builds submit --project $ProjectId --config cloudbuild.yaml --substitutions "_RAILACCESS_BUILD_COMMIT=$BuildCommit,_IMAGE=$image"
gcloud run deploy $Service --project $ProjectId --region $Region --image $image --allow-unauthenticated --service-account "railaccess-runtime@$ProjectId.iam.gserviceaccount.com" --cpu 2 --memory 2Gi --concurrency 1 --max-instances 1 --min-instances 0 --timeout 600 --set-env-vars "RAILACCESS_AI_ENABLED=true,RAILACCESS_COOKIE_SECURE=true,RAILACCESS_RUN_TTL_SECONDS=1800,RAILACCESS_GCP_PROJECT=$ProjectId,RAILACCESS_VERTEX_LOCATION=global,RAILACCESS_GEMINI_MODEL=gemini-2.5-flash,RAILACCESS_BUILD_COMMIT=$BuildCommit"
