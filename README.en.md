# Vigie — runnable agentic demo

[Français](README.md) · **English**

**ASUS Agent Computer Challenge submission — High-End category**

**Vigie** — the agent that takes the watch: it receives an objective, picks tools, chains steps,
**verifies what it produced** and leaves a deliverable on disk.

A deliberately small but honest demo. No API key, no network, no
dependency — two commands and it runs.

**Presentation video (64 s)**: [`docs/video/agent-computer-demo.mp4`](docs/video/agent-computer-demo.mp4).

![Demo interface](docs/screenshot-run.png)

## In thirty seconds

```bash
docker run --rm -p 8080:8080 holloow313/asus-agent-computer-challenge-high-end:latest
# without a published image: docker build -t vigie . && docker run --rm -p 8080:8080 vigie
# or, without Docker:  python3 -m agentdemo serve --port 8080
python3 -m unittest discover -s tests -v     # 9 tests, no dependency
```

Then, in the UI: **self-repair**, which shows learning across two passes.

**Measured on my machine** (3 GB VRAM GPU, LM Studio, Q4 quantisation, 10 verifiable tasks,
exact-match grading):

| Local model | Success | p50 | p95 | Cost / 1 000 tasks |
| --- | --- | --- | --- | --- |
| qwen2.5-coder-7b | 60 % | 0.48 s | 0.93 s | 0 € |
| qwen3-vl-8b | 90 % | 18.9 s | 38.2 s | 0 € |

Speed and accuracy are mutually exclusive on this hardware: the fast one is wrong four times out
of ten, the accurate one costs 39x more time. That is the measured bottleneck, and the point of
the submission. Method and limits: [`docs/mesures-locales.md`](docs/mesures-locales.md).

---

## 1. What this demo proves

This repository is the **runnable, cleaned-up** version of the system described in my submission.
It does not ship my production instance (it contains personal data and credentials), it ships
**the loop**:

```
objective → planning → tool call → observation → … → verification → deliverable
```

Three things are real here, and that is what separates an agent from a chatbot:

1. **The system sequences the decisions, not the user.** The agent chains the steps on its own
   under a strict step budget: past the budget the run stops cleanly (`budget` status) instead of
   looping.
2. **Tools have real side effects.** Files written exist, messages moved really moved, the SVG
   chart is computed from the data. Nothing here is a screenshot.
3. **Verification is part of the loop.** In every scenario the agent re-reads the file it just
   wrote before concluding — an announced deliverable is not a deliverable.

A JSON journal is written per run (`data/runs/<run_id>.json`): objective, every thought, every
tool call, every observation, duration, summary. Everything is auditable.

---

## 2. Quick start

### Option A — Docker (recommended)

```bash
# 1. image published by CI (Docker Hub)
docker run --rm -p 8080:8080 holloow313/asus-agent-computer-challenge-high-end:latest

# 2. same image from GitHub Container Registry (GHCR)
docker run --rm -p 8080:8080 ghcr.io/hollow313/asus-agent-computer-challenge-high-end:latest

# 3. or build it locally
docker compose up --build
# → http://localhost:8080
```

### Option B — no Docker, Python 3.10+ only

```bash
python3 -m agentdemo serve --port 8080
# → http://localhost:8080
```

### Option C — command line (no web UI)

```bash
python3 -m agentdemo scenarios
python3 -m agentdemo run --scenario cyber-brief
python3 -m agentdemo run --scenario inbox-triage
python3 -m agentdemo run --scenario dataset-report
python3 -m agentdemo run --scenario self-repair
```

Each run writes its workspace under `data/runs/<run_id>/workspace/` — that is where the
deliverables are.

> Nothing to install, no `pip install`. The package only uses the standard library (see
> `requirements.txt`, intentionally empty).

### Volumes, UID and mounts (NAS / TrueNAS)

The container runs as **UID/GID 568**, the applications user on TrueNAS SCALE, so written files
stay readable from the host without fighting permissions. If you force another user, pass
`-u $(id -u):$(id -g)` — the only requirement is that `/data` is writable by that UID.

**Only one directory has to be mounted: `/data`.** It holds runs, deliverables, JSON journals
and learned procedures. Nothing else is needed: no config file, no secret, no access to the
Docker socket.

```bash
# named volume: nothing to prepare
docker run --rm -p 8080:8080 -v agentdemo-data:/data \
  holloow313/asus-agent-computer-challenge-high-end:latest

# host directory: give it UID 568 first
mkdir -p /mnt/tank/apps/agent-computer-demo
chown -R 568:568 /mnt/tank/apps/agent-computer-demo
docker run --rm -p 8080:8080 -v /mnt/tank/apps/agent-computer-demo:/data \
  holloow313/asus-agent-computer-challenge-high-end:latest
```

---

## 3. The four scenarios

| Scenario | Objective given to the agent | Deliverables |
| --- | --- | --- |
| `cyber-brief` | Aggregate three RSS feeds, rank them, write a dated briefing of 5 entries | `briefing.md` |
| `inbox-triage` | Read 5 messages, classify by moving files, report today's actions | `rapport-tri.md` + `triaged/` tree |
| `dataset-report` | Profile a CSV, draw a chart, produce a note with three findings | `synthese.md`, `graphique.svg` |
| `self-repair` | **Two passes on the same objective**: pass 1 guesses a filename and breaks, the agent writes the procedure, pass 2 goes straight to the point | `veille.md` + a persisted procedure |

### The `self-repair` scenario, in one line

Pass 1: 6 steps, 1 error (wrong filename guessed), and the agent **writes the lesson** into a
procedure file. Pass 2, same objective: it **reads the procedure first**, then 4 steps and zero
errors. This is the one thing a better model cannot buy — it is procedural memory, and it is what
my production agent does at the scale of ~90 procedures.

---

## 4. Two planners, one loop

The core (`agentdemo/agent.py`) does not know where decisions come from. Two backends implement
the same interface:

- **`ReplayPlanner`** (default) — replays a recorded decision trace
  (`scenarios/<slug>/cassette.json`). Deterministic, offline, no key, no model. **Tools still
  execute for real**: the sandbox is real, the files are real. This is what a reviewer can run in
  30 seconds without installing anything else.
- **`OpenAICompatPlanner`** — talks to any OpenAI-compatible `/chat/completions` endpoint:
  **Ollama**, **LM Studio**, vLLM, or a remote API. The model receives the tool catalogue in its
  system prompt and must answer with a single JSON action.

### Going live, fully local, no key

```bash
ollama pull qwen2.5-coder:7b

AGENTDEMO_LLM_BASE_URL=http://localhost:11434/v1 \
AGENTDEMO_LLM_MODEL=qwen2.5-coder:7b \
python3 -m agentdemo run --scenario cyber-brief --live
```

Or in the web UI: **live (modèle)**, then *Lancer l'agent*. Same environment variables
(`AGENTDEMO_LLM_BASE_URL`, `AGENTDEMO_LLM_MODEL`, `AGENTDEMO_LLM_API_KEY` if the endpoint needs
one).

---

## 5. Tools

Every tool operates inside the run sandbox. An absolute path or a `../` escape is refused, not
"corrected".

| Tool | Signature | Purpose |
| --- | --- | --- |
| `fs_list` | `fs_list(path)` | list a directory |
| `fs_read` | `fs_read(path, max_chars?)` | read a text file |
| `fs_write` | `fs_write(path, content)` | write a deliverable |
| `fs_move` | `fs_move(src, dst)` | move (triage by movement, never deletion) |
| `csv_profile` | `csv_profile(path)` | CSV aggregates |
| `chart_bar` | `chart_bar(path, label, value, output, title?)` | SVG bar chart |
| `rss_rank` | `rss_rank(paths[], top_n?)` | RSS parsing + ranking |
| `http_get` | `http_get(url, max_chars?)` | HTTP GET — **disabled by default** |
| `skill_recall` | `skill_recall(keyword?)` | re-read a learned procedure before acting |
| `skill_write` | `skill_write(name, content)` | record a reusable procedure |
| `skill_list` | `skill_list()` | inventory of known procedures |

### Procedural memory

Procedures live in `data/skills/*.md`, **outside the run sandbox**, so they survive the run and
the next run re-reads them. The UI lists known procedures and `GET /api/skills` returns the same.

### Does the agent really improve itself?

Yes, in the precise sense of **procedural memory** — not in the sense of a model that retrains:

- **what is real**: `skill_write` / `skill_recall` write and re-read files on disk; a procedure
  written during run N is available to run N+1; in live mode the model is instructed to consult
  its procedures before acting and to record a lesson when a step fails or costs time;
- **what the demo shows**: in `self-repair`, pass 2 reads the procedure and finishes in 4 steps
  with zero errors, against 6 steps and one error in pass 1;
- **what is not here**: no model fine-tuning, no pruning of stale procedures, no confidence
  score, no detection of a wrong lesson. A bad lesson persists and pollutes later runs — that is
  the real production problem, and it is out of scope here;
- **in my production agent**: ~90 such procedures, written and corrected over failures, with a
  manual read whenever a result looks off.

---

## 6. Security model

- **Per-run sandbox**: each execution has its own directory; out-of-scope paths are rejected by
  `Sandbox.resolve()` (covered by tests).
- **Network off by default**: `AGENTDEMO_ALLOW_NETWORK=0`; `http_get` fails with an explicit
  message instead of faking success.
- **No deletion**: triage moves files, everything stays reversible.
- **Step budget**: `max_steps` per scenario; exceeding it yields `budget`, never an infinite loop.
- **Full journal**: every run is replayable and checkable on disk.
- **Non-root container**: UID 568 (`agent`), no privileged mode, no Docker socket.

No secret, no credential, no personal data in this repository. Scenario data is synthetic and
lives in `agentdemo/scenarios/*/fixtures`.

---

## 7. Repository layout

```
agentdemo/
├── agent.py              # the loop: planning → tool → observation → summary
├── planners.py           # ReplayPlanner (offline) + OpenAICompatPlanner (live model)
├── tools.py              # tools + sandbox + SVG chart
├── skills.py             # persistent procedural memory
├── scenarios_loader.py   # scenarios and fixtures loading
├── cli.py                # CLI: scenarios / run / serve
├── server.py             # HTTP API + web UI (http.server, stdlib)
├── web/index.html        # single page, no dependency
└── scenarios/            # 4 scenarios: cassette + scenario.json + fixtures
tests/test_demo.py        # 9 tests: scenarios, learning, sandbox, budget
bench/                    # measurement bench: bench.py, tasks, prices, simulated endpoint
video/                    # title cards and UI capture for the video (slides.py, record.py)
docs/                     # screenshots, architecture, local measurements, scenarios, 3-min path
Dockerfile, docker-compose.yml, Makefile, .github/workflows/docker-build.yml
```

### API

| Route | Method | Purpose |
| --- | --- | --- |
| `/` | GET | web UI |
| `/api/scenarios` | GET | scenario list |
| `/api/run` | POST | `{"scenario": "...", "mode": "replay\|live"}` → `{"run_id": ...}` |
| `/api/runs/<id>` | GET | state, steps, summary, artifacts |
| `/api/artifacts/<id>/<path>` | GET | download a deliverable |
| `/healthz` | GET | health probe |

---

## 8. Tests and CI

```bash
python3 -m unittest discover -s tests -v   # 9 tests, no framework
```

Scenarios reach `done`, deliverables are checked on disk, `self-repair` proves pass 2 is shorter
and error-free, the sandbox refuses escapes, the step budget is enforced, an unknown tool
produces an observation instead of a crash.

CI (GitHub Actions): tests on Python 3.10/3.12 plus every scenario through the CLI, image build
and push (GHCR + Docker Hub when the secrets are set), then a **smoke job that runs the
container**, hits `/healthz`, starts a scenario through the API, waits for `done` and downloads a
deliverable.

---

## 9. What this demo is not

So a technical reviewer does not have to discover it:

- **It is not my production agent.** The real instance runs permanently on a personal server with
  ~90 self-written procedures, 20 scheduled tasks, a Chrome browser driven over CDP on another
  machine, IMAP/SMTP, a messaging API, and routing between local and cloud models. It holds
  private data, so it is not published.
- **Replay mode does not reason.** It replays recorded decisions. That is deliberate: a demo that
  requires an API key or a 20 GB model is not a demo, it is an access condition. Live mode exists
  to prove the loop works with a real model, including a local one.
- **The tool catalogue is small** (11 tools, files and analysis only). No shell, no mail sending,
  no browser automation here.
- **Procedural memory is a reduced version**: a folder of markdown procedures re-read on the next
  run, without deduplication, confidence scoring or automatic revision.

---

## 10. From prototype to workstation

My current limit is compute: **3 GB of VRAM**, so 3-4 B models in aggressive quantisation and a
near-systematic fallback to the cloud as soon as reasoning is needed. Consequences: cost per
token, network dependency, and no way to process sensitive documents locally.

| Today (3 GB) | With 16 GB |
| --- | --- |
| 7-8 B in Q4, 60 to 90 % success | 14 B to 32 B in Q4/Q5, usable context |
| anything sensitive goes to the cloud | monitoring and mail triage processed offline |
| no realistic personal RAG | index over my own archives |
| cost per token on scheduled tasks | marginal cost = electricity |

The 30-day plan is in the submission: measure 14 B/32 B against the cloud model on the same
tasks, move monitoring and mail triage locally, build a RAG over my archives, open the agent to a
second household user, publish the measured comparison.

---

## 11. Measure, don't claim

`bench/` answers the only question that matters for an Agent Computer: **what does it cost and
what do you get** from running the agent locally.

```bash
python3 bench/bench.py --target "ollama-local=http://localhost:11434/v1|qwen2.5-coder:7b" \
                       --target "cloud=https://api.provider.tld/v1|gpt-4o-mini|$API_KEY"
```

Three figures per target: **success rate** on 10 real agent tasks graded by exact match,
**p50/p95 latency**, **cost per 1 000 runs** computed from the tokens actually consumed. The
bench writes a markdown report, raw JSON and an SVG chart. See [`bench/README.md`](bench/README.md).
A simulated endpoint lets CI test the plumbing without a GPU or a key.

**Real measurements on my machine** (3 GB VRAM GPU, LM Studio, Q4, 10 verifiable tasks):
[`docs/mesures-locales.md`](docs/mesures-locales.md).

## 12. Adding a scenario

```bash
python3 -m agentdemo new --slug invoice-triage --title "Invoice triage" \
  --objective "Classify invoices from inbox and write rapport.md."
python3 -m agentdemo validate --slug invoice-triage
python3 -m agentdemo run --scenario invoice-triage
```

A scenario is a folder with `scenario.json` (objective, step budget), `cassette.json` (one action
per step, `args` keys matching the tool signature exactly) and `fixtures/` (synthetic data).
`validate` cross-checks cassettes against the real tools. Full format: [`docs/SCENARIOS.md`](docs/SCENARIOS.md).

## 13. Licence and author

MIT — see `LICENSE`. Author: Loïc Huon.
