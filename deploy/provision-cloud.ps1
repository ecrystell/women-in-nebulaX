<#
Creates only the minimum project resources required by the public hackathon
service. It creates no API keys, no service-account keys, no database, and no
object storage. Review the rendered commands and billing-account selection
before running in Cloud Shell or a machine with gcloud installed.
#>
param(
  [string]$ProjectId = "qwiklabs-gcp-00-94397d478e88",
  [string]$RuntimeAccountId = "for-rails-runtime"
)

$ErrorActionPreference = "Stop"
$runtimeEmail = "$RuntimeAccountId@$ProjectId.iam.gserviceaccount.com"

gcloud services enable aiplatform.googleapis.com run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com logging.googleapis.com cloudbilling.googleapis.com --project $ProjectId

$existing = gcloud iam service-accounts list --project $ProjectId --filter "email:$runtimeEmail" --format "value(email)"
if (-not $existing) {
  gcloud iam service-accounts create $RuntimeAccountId --project $ProjectId --display-name "For Rails Cloud Run runtime"
}
gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$runtimeEmail" --role roles/aiplatform.user --condition None

$repository = gcloud artifacts repositories list --project $ProjectId --location us-central1 --filter "name:for-rails" --format "value(name)"
if (-not $repository) {
  gcloud artifacts repositories create for-rails --project $ProjectId --location us-central1 --repository-format docker --description "For Rails hackathon images"
}

Write-Host "Provisioning complete. Create the USD 20 billing alert in Billing > Budgets, then run deploy/cloud-run.ps1 with a full Git SHA."
