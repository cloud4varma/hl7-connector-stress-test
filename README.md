# HL7 Connector Stress Test

This project provides a Python-based **Cloud Run Job** that sends HL7-like JSON payloads to a target HTTP endpoint.
It is intended for load and stress testing using a controlled traffic pattern (ramp-up, steady load, ramp-down).

---

## Test Configuration

* **Total duration:** 15 minutes
* **Ramp up:** 5 minutes (0 → 10,000 requests/min)
* **Hold:** 8 minutes (10,000 requests/min)
* **Ramp down:** 2 minutes (10,000 → 0 requests/min)
* **Peak load:** 10,000 requests/min
* **Total requests:** ~115,000

---

## Required APIs

Make sure the following Google Cloud APIs are enabled:

* `run.googleapis.com`
* `cloudbuild.googleapis.com`
* `artifactregistry.googleapis.com`

---

## Steps to Run

### 1. Create Artifact Registry

```bash
gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location="$REGION"
```

Replace `$REPO_NAME` and `$REGION` with your values.

---

### 2. Build and Push Image

Run from the project directory:

```bash
gcloud builds submit \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/hl7-connector-stress-test"
```

Replace `$REGION`, `$PROJECT_ID`, and `$REPO_NAME`.

---

### 3. Create Cloud Run Job

```bash
gcloud run jobs create "$JOB_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --task-timeout=1800s \
  --cpu=2 \
  --memory=1Gi \
  --set-env-vars TARGET_URL="$TARGET_URL" \
  --set-env-vars DURATION_SECONDS="900" \
  --set-env-vars RAMP_UP_SECONDS="300" \
  --set-env-vars HOLD_SECONDS="480" \
  --set-env-vars RAMP_DOWN_SECONDS="120" \
  --set-env-vars MAX_RPM="10000" \
  --set-env-vars MAX_WORKERS="500" \
  --set-env-vars TIMEOUT_SECONDS="30" \
  --set-env-vars LOG_EACH_REQUEST="true" \
  --set-env-vars PROGRESS_INTERVAL_SECONDS="30" \
  --set-env-vars HL7_BEARER_TOKEN="$HL7_BEARER_TOKEN"
```

Notes:

* Replace `$JOB_NAME`, `$IMAGE`, `$REGION` with actual values
* `TARGET_URL` is the endpoint receiving the payloads
* `HL7_BEARER_TOKEN` is used for Authorization header

---

### 4. Execute the Job

```bash
gcloud run jobs execute "$JOB_NAME" \
  --region "$REGION"
```

Replace `$JOB_NAME` and `$REGION`.

---

## Notes
* You can tune RPM, workers, and duration using env variables
* Logs are available in Cloud Logging

---
