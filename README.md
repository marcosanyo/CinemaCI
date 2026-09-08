# Cinema CI — Runtime Creative Lineage for Generative Filmmaking

<div align="center">

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Vertex%20AI%20%2B%20Cloud%20Run-4285F4.svg)](https://cloud.google.com/)
[![Grafana Cloud](https://img.shields.io/badge/Grafana-Tempo%20%2B%20Official%20MCP-F46800.svg)](https://grafana.com/)
[![Google ADK](https://img.shields.io/badge/Agent-Google%20ADK-34A853.svg)](https://github.com/google/adk)
[![Demo Video](https://img.shields.io/badge/YouTube-Demo_Video-red.svg?logo=youtube)](https://youtu.be/fM0Q5CqtAoA)

**Trace creative decisions. Predict impact. Rebuild only what became stale.**

[🎬 Demo Video (3m)](https://youtu.be/fM0Q5CqtAoA) · [🎥 Baseline Film](https://youtu.be/5rd_jhhyUZ8) · [✨ Incremental Film](https://youtu.be/NFjmPEYDuWY) · [日本語 (Japanese)](README.ja.md) · [Architecture](docs/ARCHITECTURE.md) · [Deployment](docs/DEPLOYMENT.md) · [Grafana Guide](docs/GRAFANA_GUIDE.md)

<br/>

[![Cinema CI Demo Video](docs/images/thumb.jpeg)](https://youtu.be/fM0Q5CqtAoA)

> 🎬 **Generated Film Outputs**:  
> • **Baseline Master Film (Before Change: With Eyeglasses)**: [https://youtu.be/5rd_jhhyUZ8](https://youtu.be/5rd_jhhyUZ8)  
> • **Incremental Master Film (After Change: Eyeglasses Removed & Shot 02 Reused)**: [https://youtu.be/NFjmPEYDuWY](https://youtu.be/NFjmPEYDuWY)  

</div>

---

## What is Cinema CI?

Generative filmmaking becomes difficult when a director changes something after multiple shots and downstream assets have already been produced.

The problem is not only static dependency management. **Agentic production pipelines can create dependencies at runtime.** An AI art director may choose one generated shot as the source for a poster only after the shots exist. That dependency cannot be fully known from the static production manifest in advance.

Cinema CI records those runtime creative decisions in **Grafana Tempo** and uses them as evidence for the next change.

```text
Creative change
      ↓
Google ADK + Gemini
      ↓
Declared dependencies (cinema.yaml)
          ∪
Observed runtime lineage (Grafana Tempo via official mcp-grafana)
      ↓
True Blast Radius
      ↓
Incremental rebuild → QA → Human release gate
```

### Hero scenario

The creator requests:

> **Remove Marcus's eyeglasses.**

The static manifest identifies the character traits and the shots containing Marcus (`shot_01` and `shot_03`). During the previous build, however, Gemini visually evaluated **real keyframes extracted from generated shots** and selected one as the poster source. The poster artifact was then materialized from that selected generated shot.

That runtime choice is emitted as an OpenTelemetry span:

```text
cinema.reference.select
  cinema.consumer = poster
  cinema.reference.selected = <actual generated shot keyframe>
  cinema.selection.reason = <Gemini decision>
  cinema.selection.confidence = <score>
  cinema.source.sha256 = <actual source fingerprint>
```

The next Google ADK impact-analysis run queries that Tempo evidence through the **official Grafana MCP server**.

> **True Blast Radius = Declared Dependencies ∪ Observed Runtime Lineage**

For the demo production graph:

- **3 / 4 artifacts rebuilt** (`shot_01`, `shot_03`, `poster`)
- **1 / 4 artifacts byte-identically reused** (`shot_02`)
- **1 / 4 pipeline artifact operations avoided (25.0%)**
- **1 / 3 video-generation operations avoided (33.3%)**

We intentionally do **not** describe this as “25.0% GPU cost saved”; the operations have different costs. The measured claims are: 1 of 3 video-generation operations avoided (33.3%), and 1 of 4 pipeline artifact operations avoided (25.0%). The submitted demo proves the mechanism on four real production artifacts. The same runtime-lineage model can extend to larger agentic production graphs where downstream dependencies are selected during execution.

---

## Why Grafana is part of the product logic

Grafana is not used only for dashboards.

> **Static manifests show what should depend on what. Grafana Tempo shows what actually did at runtime.**

Cinema CI sends OpenTelemetry traces to Grafana Tempo. The Google ADK agent queries those traces through `mcp-grafana` and uses the observed creative lineage as input to the deterministic impact calculation.

Grafana therefore acts as the **execution memory of the creative pipeline**.

Prometheus and Loki provide operational/QA visibility; Tempo lineage is the differentiating control-plane evidence.

---

## Core capabilities

### 1. Change Impact Intelligence

- Gemini interprets a natural-language creative instruction into a structured mutation.
- The ADK agent retrieves the relevant prior build evidence through official Grafana MCP.
- Deterministic Python graph traversal computes the rebuild / reuse plan.

### 2. Causal runtime creative lineage

Poster selection is not a synthetic trace label:

1. generated shot videos already exist;
2. FFmpeg extracts real candidate keyframes;
3. Gemini visually evaluates those keyframes;
4. Gemini selects one runtime reference;
5. the poster is actually materialized from that selected generated shot;
6. the same source reference/fingerprint is recorded in Tempo.

### 3. Byte-identical incremental reuse

Unaffected artifacts are copied from the baseline rather than regenerated. SHA-256 verifies that the reused bytes are identical to the baseline bytes.

The hash proves this precise claim only; it is not presented as proof that an entire film has zero quality risk.

### 4. Multi-stage QA

- PyAV / FFmpeg deterministic technical checks
- Gemini multimodal creative checks
- cross-shot consistency checks
- regression detection against the baseline

A failing build is blocked before release.

### 5. Continuous delivery with a human gate

Passing builds become `RELEASE_READY`, are packaged into a master cut, and require explicit human promotion before becoming a production release.

### 6. Bounded agentic repair

When validation fails, the ADK agent can investigate Grafana metrics, logs, and traces and trigger surgical regeneration. Repair is bounded; unresolved cases escalate to `HUMAN_REVIEW`.

---

## Google Cloud production architecture

[![Cinema CI System Architecture](docs/images/architecture.jpeg)](docs/images/architecture.jpeg)

```text
Browser
   │
   ▼
Cloud Run Service
Cinema CI Control Plane
   ├── FastAPI UI / API
   ├── Google ADK + Gemini
   ├── Deterministic ImpactEngine
   └── official mcp-grafana ───────▶ Grafana Cloud
               │                       Tempo / Loki / Prometheus
               │
               ├── Firestore
               │   Build / Impact / Release metadata
               │
               └── Cloud Run Job
                   Build Worker
                     ├── Veo 3.1
                     ├── Gemini QA
                     ├── PyAV / FFmpeg
                     └── Cloud Storage artifacts
```

Cloud Run Jobs keep long-running Veo generation outside the HTTP request lifecycle. GCS and Firestore keep the production durable across Cloud Run restarts.

Local development remains supported with local `./storage`; local + GCS/Firestore is also supported through the backend adapters.

---

## Technology

- **Agent orchestration:** Google ADK
- **Semantic / multimodal AI:** Gemini 3.8 Flash on Vertex AI
- **Video generation:** Google Veo 3.1
- **Runtime:** Cloud Run Service + Cloud Run Jobs
- **Artifacts:** Google Cloud Storage / local adapter
- **Metadata:** Firestore / local adapter
- **Observability:** Grafana Tempo, Loki, Prometheus
- **Agent observability tool:** official `mcp-grafana` over STDIO
- **Instrumentation:** OpenTelemetry
- **Backend:** FastAPI / Python
- **Frontend:** Zero-build ES Modules & CSS Tokens (fully responsive for mobile, tablet, and desktop)
- **QA:** PyAV / FFmpeg + Gemini multimodal evaluation

---

## Local quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Launch via zero-argument shell scripts:
./run_mock.sh   # Offline mock mode (fixtures, instant execution, $0.00 cost)
./run_prod.sh   # Production Strict Mode (Veo 3.1, Gemini 3.8 Flash, Grafana MCP)

# Or launch directly:
export CINEMA_ENV=local
export CINEMA_ARTIFACT_BACKEND=local
export CINEMA_METADATA_BACKEND=local
export CINEMA_BUILD_EXECUTOR=local

uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Artifacts remain directly inspectable under `./storage`.

For production deployment, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Credential values must never be committed; Grafana/OTLP secrets should be injected from Secret Manager.

---

## Verification

```bash
# Deterministic local/unit coverage
python -m unittest discover tests

# Strict ADK + Grafana MCP / Tempo integration verification
python scripts/test_strict_submission_e2e.py

# Cloud backend adapter integration verification
# NOTE: this test uses FixtureGenerator and does NOT claim live Veo or live Cloud Run Job execution.
python scripts/test_cloud_submission_e2e.py
```

Live Cloud Run Job / Veo execution should be proven separately using deployed Google Cloud execution evidence for the submission video.

---

## Submission narrative

The three-minute demo is intentionally centered on one proof:

> **A previous AI decision became runtime evidence in Grafana, and that evidence changed the next rebuild plan.**

---

## License

Apache License 2.0.
