# Cinema CI — Google Cloud Run Production Deployment Guide

Cinema CI runs with a decoupled control-plane / build-worker architecture:

- **Cloud Run Service (`cinema-ci`)** — FastAPI UI/API, Google ADK orchestration, deterministic ImpactEngine, official `mcp-grafana` subprocess.
- **Cloud Run Job (`cinema-ci-build-worker`)** — long-running Veo generation, PyAV/FFmpeg QA, Gemini creative QA, packaging.
- **Google Cloud Storage** — durable film artifacts and server-side byte-identical reuse.
- **Firestore** — build, impact-plan, and release metadata across service restarts.
- **Grafana Cloud** — Tempo traces, Loki logs, and Prometheus metrics.

```text
Browser
  │
  ▼
Cloud Run Service
  ├── Google ADK / Gemini
  ├── ImpactEngine
  ├── official mcp-grafana ──▶ Grafana Cloud
  ├── Firestore
  └── Cloud Run Job
          ├── Veo 3.1
          ├── Gemini QA
          ├── PyAV / FFmpeg
          └── GCS artifacts
```

## Environment matrix

| Mode | Artifact backend | Metadata backend | Build executor |
| --- | --- | --- | --- |
| Local default | `local` (`./storage`) | `local` | `local` |
| Local + Cloud | `gcs` | `firestore` | `local` |
| Cloud production | `gcs` | `firestore` | `cloud-run-job` |

## Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"
```

## Durable storage

```bash
gcloud storage buckets create "gs://$CINEMA_GCS_BUCKET" \
  --location=us-central1 \
  --project="$GOOGLE_CLOUD_PROJECT"

gcloud firestore databases create \
  --location=us-central1 \
  --project="$GOOGLE_CLOUD_PROJECT" || true
```

## Build image

```bash
gcloud builds submit \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --tag="gcr.io/$GOOGLE_CLOUD_PROJECT/cinema-ci" .
```

## Secrets — never commit credential values

Create or rotate Grafana credentials outside Git. The repository must contain only secret names/placeholders.

Recommended Secret Manager entries:

```text
cinema-grafana-sa-token
cinema-otel-auth-header
```

Example creation pattern:

```bash
printf '%s' "$GRAFANA_SA_TOKEN" | \
  gcloud secrets create cinema-grafana-sa-token \
    --data-file=- --replication-policy=automatic \
    --project="$GOOGLE_CLOUD_PROJECT"

printf '%s' "$OTEL_EXPORTER_OTLP_HEADERS" | \
  gcloud secrets create cinema-otel-auth-header \
    --data-file=- --replication-policy=automatic \
    --project="$GOOGLE_CLOUD_PROJECT"
```

If the secret already exists, add a new version instead of creating it again.

## Deploy Cloud Run Job

```bash
gcloud run jobs deploy cinema-ci-build-worker \
  --image="gcr.io/$GOOGLE_CLOUD_PROJECT/cinema-ci" \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region=us-central1 \
  --command=python \
  --args=-m,app.worker \
  --memory=4Gi \
  --cpu=2 \
  --max-retries=0 \
  --task-timeout=3600 \
  --set-env-vars="CINEMA_ENV=cloud,CINEMA_ARTIFACT_BACKEND=gcs,CINEMA_METADATA_BACKEND=firestore,CINEMA_GCS_BUCKET=$CINEMA_GCS_BUCKET,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true,GENERATOR_TYPE=veo,VEO_MODEL=veo-3.1-lite-generate-001,VEO_LOCATION=us-central1,STRICT_MODE=true,CINEMA_STRICT_MODE=1,OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT" \
  --set-secrets="OTEL_EXPORTER_OTLP_HEADERS=cinema-otel-auth-header:latest"
```

## Deploy Cloud Run Service

```bash
gcloud run deploy cinema-ci \
  --image="gcr.io/$GOOGLE_CLOUD_PROJECT/cinema-ci" \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=3600 \
  --min-instances=0 \
  --max-instances=2 \
  --set-env-vars="CINEMA_ENV=cloud,CINEMA_ARTIFACT_BACKEND=gcs,CINEMA_METADATA_BACKEND=firestore,CINEMA_BUILD_EXECUTOR=cloud-run-job,CINEMA_GCS_BUCKET=$CINEMA_GCS_BUCKET,CINEMA_BUILD_JOB=cinema-ci-build-worker,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true,GENERATOR_TYPE=veo,VEO_MODEL=veo-3.1-lite-generate-001,VEO_LOCATION=us-central1,STRICT_MODE=true,CINEMA_STRICT_MODE=1,GRAFANA_URL=$GRAFANA_URL,PROM_DATASOURCE_UID=grafanacloud-prom,LOKI_DATASOURCE_UID=grafanacloud-logs,TEMPO_DATASOURCE_UID=grafanacloud-traces,OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT" \
  --set-secrets="GRAFANA_SA_TOKEN=cinema-grafana-sa-token:latest,OTEL_EXPORTER_OTLP_HEADERS=cinema-otel-auth-header:latest"
```

## IAM

The Cloud Run service/job should use service accounts with only the required permissions:

- GCS object read/write for the Cinema CI bucket
- Firestore read/write for Cinema CI metadata
- Vertex AI model invocation
- Cloud Run Job execution from the control-plane service
- Secret Manager secret accessor for the two Grafana/OTel secrets

Use ADC / workload identity. Do **not** place JSON keys inside the container image.

## Verification

After deployment, verify the public service and persistent metadata:

```bash
SERVICE_URL="$(gcloud run services describe cinema-ci \
  --region=us-central1 \
  --project="$GOOGLE_CLOUD_PROJECT" \
  --format='value(status.url)')"

curl -fsS "$SERVICE_URL/api/project" | jq .
curl -fsS "$SERVICE_URL/api/builds" | jq .
```

For submission evidence, separately capture:

1. Cloud Run service URL / revision
2. Cloud Run Job execution history
3. GCS build artifacts
4. Firestore build metadata
5. Grafana Tempo trace containing `cinema.reference.select`

> **Security note:** If credentials were ever committed to Git history, deleting them from the current file is not sufficient. Revoke/rotate those credentials before using this repository for submission.
