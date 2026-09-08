gcloud builds submit --tag gcr.io/hackathon-505614/cinema-ci:latest --project hackathon-505614 && \
gcloud run deploy cinema-ci --image gcr.io/hackathon-505614/cinema-ci:latest --region us-central1 --project hackathon-505614 && \
gcloud run jobs update cinema-ci-build-worker --image gcr.io/hackathon-505614/cinema-ci:latest --region us-central1 --project hackathon-505614