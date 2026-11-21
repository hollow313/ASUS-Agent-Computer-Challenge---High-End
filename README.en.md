# Vigie

**An autonomous agent that runs on your machine. It takes an objective in plain language, acts on
real files, verifies its own work, and remembers what it learned.**

No API key, no network, no dependency. One command and it runs.

[▶ Watch the presentation (2 min 31)](docs/video/agent-computer-presentation.mp4) · [Try it in 30 seconds](#in-thirty-seconds) · [The measured numbers](#the-numbers)

![Interface capture](docs/screenshot-run.png)

[![build](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End/actions/workflows/docker-build.yml/badge.svg)](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End/actions/workflows/docker-build.yml)
![python](https://img.shields.io/badge/python-3.10%2B-3b7ddd)
![dependencies](https://img.shields.io/badge/dependencies-none-2ea043)
![tests](https://img.shields.io/badge/tests-52%20passing-2ea043)
![licence](https://img.shields.io/badge/licence-MIT-6e7681)

[Français](README.md) · **English**

**ASUS Agent Computer Challenge submission, High-End category.** Vigie is the distributable version
of the agent that has been running on my machine for months; this repository publishes its core,
without my data and without my keys.

**In three sentences.** An agent is not a chat that answers: it is a program that picks tools, writes
files, re-reads what it produced and starts again when something breaks. Vigie does that with six
shipped scenarios, including a local security audit, and it learns by recording procedures it
re-reads on the next run. All of it runs today on a 3 GB VRAM card, and that is where the project
meets its ceiling.

The rest comes in two parts: the first sells the project, the second opens it up for an engineer,
limits included.

## What is missing, and what the card unlocks

With 3 GB of VRAM, the largest model that fits is 7 billion parameters at 4 bits. It is fast, it is
free, and it is wrong about one task in two. The model that handles ambiguous work does not fit.
Sub-agents cannot run in parallel. Context stays short, so the agent forgets the start of the file
in the middle of the file.

32 GB of VRAM is not comfort. It is the size that holds a 32-billion-parameter model at 4-bit
quantisation (30.4 GB measured, 1.6 GB of margin for context and sub-agents), or a 14B model at 8
bits with 11 GB of margin. Such a model reads a whole file, holds a thirty-step reasoning chain, and
no longer needs the work chopped into pieces in case it loses the thread.

The measurement ships with the repository, reproducible with one command, and the limits are
written down in part 2. Nobody has to take my word for it: run the bench.

## In thirty seconds

```bash
git clone https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End
cd ASUS-Agent-Computer-Challenge---High-End
python3 -m agentdemo scenarios                  # six scenarios, nothing to install
python3 -m agentdemo run --scenario cyber-brief # one full, deterministic run
python3 -m agentdemo serve --port 8080          # the same with the web UI
python3 -m unittest discover -s tests           # 52 tests, two seconds
```

Or in a container, the same image used for every screenshot here:

```bash
docker run --rm -p 8080:8080 holloow313/asus-agent-computer-challenge-high-end:latest
```

No Python dependency, no framework, no API key. Replay mode replays recorded decisions, but the
tools really execute: files are written, the CSV is computed, the chart is generated.

![Interface](docs/screenshot-run.png)

## The numbers

Same 10 tasks, same prompt, temperature 0, deterministic exact-match grading. Not an opinion: a
test that passes or fails. Hardware: the 3 GB VRAM card currently in my machine.

| Target | Where | Success | p50 | p95 | Cost / 1 000 tasks |
| --- | --- | --- | --- | --- | --- |
| Qwen 2.5 Coder 7B, Q4 | local, 3 GB VRAM | 60 % | 0.75 s | 3.98 s | 0 € |
| Qwen3 VL 8B, Q4 | local, 3 GB VRAM | 90 % | 0.67 s | 4.63 s | 0 € |
| Gemini 3.8 Flash | cloud | 100 % | 4.17 s | 5.23 s | 0.07 € |

Measured 2026-11-21 13:37 UTC, ten tasks, one pass. Raw report and JSON:
[`docs/mesures/mesures-20261121.md`](docs/mesures/mesures-20261121.md).

The same 1 000 tasks, at public prices as of 2026-11-21 and with the token usage actually measured
(791 input and 50 output tokens for ten tasks):

| Model | Input / M tokens | Output / M tokens | 1 000 tasks |
| --- | --- | --- | --- |
| local, 8B Q4 | 0 € | 0 € | 0 € |
| Gemini 3.8 Flash | 0.69 € | 3.45 € | 0.07 € |
| Claude Opus 5.5 | 3.68 € | 18.40 € | 0.38 € |
| GPT-5.5 Pro | 27.60 € | 165.60 € | 3.01 € |

This table does not rank models by quality, it prices the bill: at equal usage, the most expensive
model in the list costs forty-three times the entry-level rate.

Three lines, one conclusion: local is free but wrong one time in two, or six times slower on the
slow cases; cloud is right but sends your data out; and the middle model that would do both does not
exist in 3 GB.
That is exactly the gap the card fills.

Method, tasks, prices and raw files: [`bench/README.md`](bench/README.md) and
[`docs/comparatif-local-cloud.md`](docs/comparatif-local-cloud.md).

## Why 32 GB, computed rather than wished

```
$ python3 -m agentdemo fit --vram 32 --context 32768

model                      size         quant   memory     margin
qwen2.5-coder-7b            7.6 B           Q8    11.7 GB   20.3 GB
qwen2.5-coder-14b          14.7 B           Q8    20.9 GB   11.1 GB
mistral-small-24b          23.6 B           Q6    26.9 GB    5.1 GB
qwen2.5-coder-32b          32.8 B           Q4    30.4 GB    1.6 GB
llama-3.3-70b              70.6 B does not fit     56.0 GB  -24.0 GB
```

A 32-billion-parameter model fits at 4 bits, with 1.6 GB left for long context and sub-agents. That
is the format that changes the nature of the work: the agent stops chopping each task into pieces
it can hold, and starts reading the whole file.

The same command on 16 GB shows the 32B does not fit at all, even at Q4. The requested card is not a
whim, it is a sizing decision you can verify.

| Today (3 GB) | With 32 GB |
| --- | --- |
| 7 to 8 B at Q4, one task in two fails at times | 32 B at Q4 fully resident, 70 B possible |
| short context, truncated history | long context, whole file and a held reasoning chain |
| monitoring and mail handled in the cloud | everything stays on the machine, sensitive data included |
| personal RAG unrealistic | index over my archives, cited answers |

## What a jury can verify in ten minutes

1. **It runs.** One command, no key, six scenarios, deliverables written.
2. **The result is real.** Briefing, summary and chart are in the run sandbox, with a timestamped
   step journal and a downloadable ZIP export.
3. **The agent learns.** Run `self-repair`: pass 2 does 4 steps where pass 1 did 6, and zero errors
   instead of one. The procedure sits in `data/skills/`, readable, with its verification contract.
4. **The agent really delegates.** `delegation` spawns three sub-agents with their own budget and
   folder, then aggregates their deliverables. Verified in live mode too.
5. **The agent picks its model.** `/routing` decides which target handles which task, and every
   execution journals its decision with the reason.
6. **It is operable.** `/settings` wires a CSV folder, an IMAP account and schedules scenarios every
   morning. The password is never returned by the API.
7. **The limits are written.** Part 2 below, and [`docs/PRODUCTION.md`](docs/PRODUCTION.md).

## Two videos, two uses

| Video | Length | What it shows |
| --- | --- | --- |
| [`docs/video/agent-computer-presentation.mp4`](docs/video/agent-computer-presentation.mp4) | 2 min 31 | the whole project: the 3 GB ceiling, the six scenarios, procedural memory, delegation, routing, scheduling, the measurements and the card sizing |
| [`docs/video/agent-computer-demo.mp4`](docs/video/agent-computer-demo.mp4) | 64 s | the agentic loop in action, from objective to deliverable |

The first is the guided tour: nine slides, a continuous voice-over, the real screenshots of the
repository. The second is the short demo, for whoever wants to see the agent run before reading.
Narration script: [`video/narration-presentation.txt`](video/narration-presentation.txt); the edit
is reproducible with `video/slides3.py` then `video/build3.py`.

The voice-over of the first video is produced by a tool of the project (`tts_speak`), not by
external software. The audio file and the narration script are in the repository.

## What I do not promise

Cost is not the argument. At 0.05 € per thousand tasks, the cloud is cheaper than the card's
electricity. An honest demo cannot sell local inference on price.

Three arguments hold:

- **sovereignty**: a client file, a letter, a family archive never leaves the machine, and that is
  checkable in the code;
- **quality parity locally**: 32 GB holds the model that is almost never wrong, which 3 GB forbids
  today;
- **availability**: the agent runs at night, no quota, no outage, no bill that climbs.

And a roadmap the hardware makes possible: a RAG over my archives, LoRA fine-tuning of a small model
on my own traces, a router driven by measured thresholds. Each step produces a publishable number.

---

# Part 2. Under the hood

## Overview

```
                 +----------------------------------------------+
   objective --->|  agent loop: plan -> tool -> observation      |
                 +------+-------------------------------+-------+
                        |                               |
        +---------------v----------+        +-----------v-------------+
        | planner                  |        | tools (sandbox)         |
        |  replay: cassette        |        |  fs_*   csv_*   rss_*   |
        |  live:   /chat/...       |        |  mail_*  chart  tts     |
        +---------------+----------+        +-----------+-------------+
                        |                               |
        +---------------v----------+        +-----------v-------------+
        | routing: which target    |        | procedural memory       |
        | for which task           |        | skills/, with contracts |
        +--------------------------+        +-------------------------+
```

One process, standard library only, no network call by default. A run lives in
`data/runs/<id>/workspace/`, writes its journal as JSON, and leaves its deliverables on disk.

## The agent cycle

One turn is one planner decision and one observation. The planner receives the objective and the
history, and returns either a tool call or a conclusion. The step budget is hard: past it the run
stops with `budget` status instead of looping.

Three guardrails came out of real runs that went sideways:

- **tolerant arguments**: a small model sometimes returns its arguments as a JSON string, they are
  decoded instead of failing the step;
- **suggested paths**: a "not found" error returns the real path of the file it looked for and the
  list of CSVs in the run, so the model corrects itself on the next turn;
- **loop breaker**: three identical failing calls stop the run as `blocked` instead of burning the
  budget.

These are not polish: they are the difference between a 7B that works and a 7B that goes in circles.

## Replay and live, one interface

- **`ReplayPlanner`**, default: replays a recorded decision trace
  (`scenarios/<slug>/cassette.json`). Deterministic, offline, no key. **Tools still execute for
  real**: the sandbox is real, the files are real. This is what a reviewer runs in thirty seconds.
- **`OpenAICompatPlanner`**: talks to any OpenAI-compatible `/chat/completions` endpoint. The model
  gets the tool catalogue in its system prompt and answers with a single JSON action.

The same scenario therefore runs in replay for a demo and in live mode to measure a model.

## The six scenarios

| Scenario | Objective given to the agent | Real deliverables |
| --- | --- | --- |
| `cyber-brief` | aggregate three feeds, rank them, write a dated briefing | `briefing.md` |
| `inbox-triage` | read 5 messages, classify by moving files, report actions | `rapport-tri.md` + `triaged/` |
| `dataset-report` | profile a CSV, draw a chart, produce a note with three findings | `synthese.md`, `graphique.svg` |
| `delegation` | delegate three zones to three sub-agents, re-read, aggregate | `comparatif.md` + 3 deliverables |
| `self-repair` | three passes on the same objective: break, learn, correct | `veille.md` + two procedure versions |
| `local-audit` | audit auth logs, listening ports and SSH config on the machine | `RAPPORT-AUDIT.md` + two audit procedures |

A scenario can also be created from the UI (button **new scenario**), run once in live mode, then
recorded as a cassette. The trace only holds decisions; observations are reproduced at run time by
the real tools, so replay stays honest.

## Procedural memory and its upkeep

The agent is not smarter from one run to the next, it is cheaper. A learned procedure is a JSON file
in `data/skills/` with its content, date, usage count, a verification contract and a computed
confidence.

- `skill_recall` re-reads procedures before acting;
- `skill_write` records a lesson with its contract ("the file exists and has 3 columns");
- `skill_feedback` updates confidence from success or failure;
- `skill_revise` rewrites a stale procedure and only reactivates it if the new contract passes;
- `skill_resolve` arbitrates two contradictory procedures by evidence, not by date;
- `maintenance_run` runs an upkeep pass: repair by name similarity, arbitrate, retire.

In `self-repair`, pass 2 does 4 steps and 0 errors where pass 1 did 6 with one error. The procedure
that became wrong (the file is renamed between passes) is detected by its broken contract, not by
luck.

```bash
python3 -m agentdemo skills            # registry: status, successes, uses, confidence, contract
python3 -m agentdemo maintain --once   # repair, arbitrate, retire
python3 -m agentdemo maintain --interval 300
```

![Three-pass comparison](docs/screenshot-selfrepair.png)

## Sub-agent delegation

A sub-agent is not a function call. It has its own budget, its own journal, its own sandbox in
`delegations/<name>/`, and the parent shares nothing with it except the inventory of input files.

Two modes: if a cassette exists for that name, the sub-agent replays it; otherwise, if the run talks
to a real model, it inherits the parent endpoint and model and does the work. Depth is capped at
three levels, an already-spawned sub-agent cannot be respawned, and a sub-agent that exceeds its
budget returns its status.

```
parent (8 steps, live mode)
+-- sub-agent zone-north -> analysed deliverable
+-- sub-agent zone-west  -> analysed deliverable
+-- sub-agent zone-south -> analysed deliverable
+-- re-reads all three, then comparatif.md
```

## Model routing

An agent that talks to a single model picks the wrong tool for every task. `/routing` declares any
number of targets (two LM Studio instances, two clouds, or a mix) and ordered rules: sensitive
words, scenario, objective pattern, catch-all. The first matching rule wins, a manual override can
force any target, and every real execution journals its decision with the reason.

![Routing page](docs/screenshot-routing.png)

```bash
python3 -m agentdemo route --objective "Summarise the client file"        # local, sensitive data
python3 -m agentdemo route --objective "Analyse this dataset" --scenario dataset-report
python3 -m agentdemo route --override local-gros                         # force a target
```

Details: [`docs/ROUTAGE.md`](docs/ROUTAGE.md).

## Real inputs and scheduling

`/settings` declares the real inputs: a CSV folder (copied into `inputs/` at run start, never mounted
read-write), RSS feeds, an IMAP account with an archive folder. The password is stored 0600 on the
volume, the API returns `********` and a boolean.

![Operational settings](docs/screenshot-settings.png)

Two mail tools talk to the mailbox for real, with `imaplib` from the standard library: `mail_list`
reads sender, subject, date and a snippet; `mail_move` archives a message. Without a configured
account, the tool refuses and says where to configure it. Verified against a real mailbox: 18
messages read, report written in 5 steps, no message moved during the test.

The scheduler runs inside the server process, re-reads `settings.json` on every tick and consumes
each due slot once: every day at a fixed time, or every N minutes. A task created after its time
fires once, then resumes its rhythm: the catch-up behaviour you want after an outage. Verified in a
container: due task, fired in 20 s, run produced, history kept.

```
08:00  cyber watch   -> dated briefing     (daily, fixed time)
02:00  CSV report    -> analysis + chart   (every 1440 minutes)
```

## Security and data

- per-run sandbox: any path outside the run folder, including `../`, is refused;
- network off by default (`AGENTDEMO_ALLOW_NETWORK=0`), network tools disabled unless asked;
- no deletion: triage moves files, everything is reversible;
- secrets never in the repository: a fresh clone contains no key, no address, no machine path, and
  `settings.json` / `routing.json` live on the volume;
- non-privileged container, UID 568, a single `/data` volume, no Docker socket;
- CI builds the image, starts the container, hits `/healthz`, runs a scenario and downloads the
  deliverable before publishing.

## Real runs, not only replays

Replay mode serves the demo. It does not prove a real model does the work. Three runs are versioned
in `docs/runs/`, each with its full journal, a readable transcript and metadata.

| Date | Scenario | Model | Status | Steps | Duration |
| --- | --- | --- | --- | --- | --- |
| 21/11 | cyber-brief | qwen2.5-coder-7b-instruct | done after a corrected error | 4 | 9 s |
| 21/11 | cyber-brief | qwen/qwen3-vl-8b | done, one tool error | 7 | 136 s |
| 21/11 | local-audit | qwen2.5-coder-7b-instruct | done, shallow report | 7 | 32 s |

The three runs tell three different stories, and the third is the most useful.

The 7B on the briefing asks for `feeds/*.xml`, a glob the tool refuses: the message lists the feeds
that actually exist and the next step succeeds. The 8B on the same scenario takes 7 steps and 136
seconds, hits one tool error, then reads the three XML files directly: same result, fifteen times
slower.

The 7B on the audit is the honest one: seven steps, zero errors, and a **shallow** report. It counts
failures per user, sees port 22, quotes the sudo rule, but misses the exposed 3306 and 6379 and
gives neither severity nor remediation. Published as is, because that is exactly the limit 32 GB
removes.

```bash
python3 bench/run_real.py --scenario cyber-brief --model qwen2.5-coder-7b-instruct \
  --base-url http://YOUR-IP:1234/v1
```

## Confined execution, network declared per scenario

The `run` tool executes commands inside a sandbox whose level is written into the run report.

| Level | What is isolated | When |
| --- | --- | --- |
| `bwrap` | read-only system, `/tmp` and `$HOME` in memory, network cut, only the run folder writable | bubblewrap installed |
| `unshare -n` | network cut by the kernel | fallback without bwrap |
| `none` | nothing, and it says so | refused by default, or declared by the scenario |

Network is a capability of the scenario, not a global switch:

```json
"network": {"mode": "deny"}
"network": {"mode": "allowlist", "hosts": ["www.cert.ssi.gouv.fr"]}
"network": {"mode": "open", "justification": "..."}
```

`deny` is the default and the only mode of the shipped scenarios. A refusal is a readable
observation plus an event in the journal, never a raw exception.

## Local audit, the domain scenario

`local-audit` reads an auth log, a listening-port list, an SSH configuration and a sudo rule, then
writes `RAPPORT-AUDIT.md` with severity, remediation and the source line of every finding. Two
things make it different from a generic demo: it runs in `deny` with the routing rule sending it to
the local model, and it learns, with pass 2 doing 6 steps instead of 11 and zero errors instead of
one.

## MCP server

The tools are exposed to an external client over JSON-RPC on stdio, no dependency:

```bash
python3 -m agentdemo mcp
```

`initialize`, `tools/list` and `tools/call` are implemented with the expected JSON-RPC error codes.
Read, analysis and memory tools are exposed; **`mail_*`, `http_get` and `run` stay out**: a client
that lists a catalogue must not be able to send mail, leak data or launch a command.

## Human approval before writing

`--interactive` (or `--confirm-writes` for writes only) asks for confirmation before `fs_write`,
`fs_move`, `mail_move` and `run`. A refusal is not a crash: it becomes the step observation, the
agent reorganises, and the decision is journaled.

## Lifecycle: removing a scenario

`scenario remove` prints what will disappear (scenario, runs, attached procedures) before deleting,
refuses shipped scenarios without `--force`, and never writes outside `data/`.

## Tool catalogue, no pip install

The agent can extend its tooling without installing packages. A tool is a folder with a manifest, a
Python entry point and its sha256. Installation verifies the hash, refuses an entry point escaping
its folder, copies into `data/tools/<name>/` and reloads the registry.

```bash
python3 -m agentdemo tool list
python3 -m agentdemo tool install csv_top --yes
```

**What we do not do, and it is an architecture decision**: no `pip install`, no remote registry, no
code executed outside the data folder. Every refusal is a line in `data/tools/install.jsonl`.

## Production evidence

Three captures generated by `docs/production/make_captures.py` from facts read on the machine: uptime
and scheduled jobs, a briefing produced by a real run, the journal of versioned runs. Details and
what is deliberately redacted: [`docs/production/README.md`](docs/production/README.md).

## Measure, don't claim

`bench/bench.py` runs ten exact-match tasks against any OpenAI-compatible endpoint, measures
client-side latency (p50 and p95), counts the tokens actually reported and computes a cost per
thousand executions.

```bash
python3 bench/bench.py --target "local=http://IP:1234/v1|model" --repeat 3
```

What those figures do not say, and the generated report states: the task set is short and
checkable, hence conservative; remote endpoints vary with network load; the local cost ignores the
card amortisation.

## Memory sizing

`agentdemo fit` takes VRAM, a context size and a list of models, then says what fits:
`weights = parameters x bytes per billion by quantisation + 1.5 GB runtime`. Assumptions live in
`agentdemo/fit.py`; the table above comes from the command.

## Build, run, test

```bash
python3 -m agentdemo doctor                    # pre-flight check
python3 -m agentdemo run --scenario delegation # replay, deterministic
python3 -m agentdemo serve --port 8080         # UI, /routing, /settings
python3 -m agentdemo export                    # archive of the last run
python3 -m agentdemo route --objective "..."   # routing decision
python3 -m agentdemo fit --vram 32             # sizing
python3 -m agentdemo validate                  # cross-check cassettes against tools
python3 -m unittest discover -s tests          # 32 tests
```

In a container, UID 568 must own the volume:

```bash
mkdir -p /mnt/<pool>/apps/agent-demo && chown -R 568:568 /mnt/<pool>/apps/agent-demo
docker run -d --name agentdemo -p 8080:8080 \
  -v /mnt/<pool>/apps/agent-demo:/data \
  holloow313/asus-agent-computer-challenge-high-end:latest
```

Two registries: `holloow313/...` on Docker Hub (pull without authentication) and
`ghcr.io/hollow313/...` on GHCR. Tags `latest`, `sha-*` and `v*`.

### Plugging a real model

Live mode points at any OpenAI-compatible endpoint: LM Studio, Ollama, vLLM, or a remote API. Three
fields in the UI (endpoint, model, optional key), a button that queries `/models` and fills the
list, four presets.

```bash
python3 -m agentdemo run --scenario cyber-brief --live \
  --base-url http://YOUR-IP:1234/v1 --model llama-3.1-8b
```

As environment variables, handy in a container: `AGENTDEMO_LLM_BASE_URL`, `AGENTDEMO_LLM_MODEL`,
`AGENTDEMO_LLM_API_KEY`. The `/v1` suffix is added when missing, and the error is explained instead
of returning a raw code.

![Live model panel](docs/screenshot-live.png)

## API

| Route | Method | Purpose |
| --- | --- | --- |
| `/` | GET | web UI |
| `/healthz` | GET | health probe |
| `/api/scenarios` | GET, POST | scenario list, or create one |
| `/api/scenarios/<slug>/record` | POST | record a run trace as a cassette |
| `/api/run` | POST | `{"scenario": "...", "mode": "replay live", "llm": {...}}` |
| `/api/runs/<id>` | GET | state, steps, summary, artifacts |
| `/api/runs/<id>/export` | GET | run archive: journal and deliverables |
| `/api/artifacts/<id>/<path>` | GET | download a deliverable |
| `/api/skills` | GET | learned procedures, confidence, status |
| `/api/maintenance` | GET | recent upkeep passes |
| `/api/maintenance/run` | POST | trigger an upkeep pass |
| `/api/routing` | GET, POST | routing policy |
| `/api/routing/decide` | POST | decision for an objective |
| `/api/routing/probe` | POST | query a target's `/models` |
| `/api/settings` | GET, POST | real inputs and scheduling |
| `/api/settings/test-mail` | POST | test the IMAP connection |
| `/api/jobs/<id>/run` | POST | run a scheduled task now |
| `/api/llm/models` | GET | probe an OpenAI-compatible endpoint |

## Assumed limits

- **No fine-tuning.** The agent does not learn new weights, it accumulates written procedures. A
  fine-tuned model would be better, that is not what this repository does.
- **No automatic content rewrite.** A wrong procedure is detected by its broken contract and
  retired, but its text is not rewritten by the model during upkeep.
- **Simple scheduler.** One instance, no distributed lock, one catch-up slot. For several
  instances, use an external scheduler.
- **Settings in a single file.** Two tabs saving at once overwrite each other.
- **IMAP read and move only.** No replies, no attachment processing.
- **Live mode depends on the model.** A 7B is wrong, repeats itself, invents paths. The guardrails
  absorb, they do not fix an undersized model. That is precisely the argument for the card.
- **No real IMAP in CI.** That path is checked by hand; automation covers the error cases.
- **This is not my production agent.** The real instance runs permanently on a personal server with
  about a hundred procedures, twenty scheduled tasks, a browser driven over CDP on another machine.
  It holds private data, so it is not published. This repository is the publishable version, with the
  same mechanisms.

## Repository layout

```
agentdemo/
+-- agent.py              # the loop: planning, tool, observation, summary
+-- planners.py           # deterministic replay + OpenAI-compatible endpoint
+-- tools.py              # sandbox tools, delegation, memory
+-- skills.py             # procedural memory: contracts, confidence, revision, arbitration
+-- maintenance.py        # upkeep: repair, arbitrate, retire
+-- routing.py            # routing policy: targets, rules, override, history
+-- settings_store.py     # real inputs and scheduling (password never returned)
+-- mailbox.py            # real IMAP read and triage (imaplib)
+-- fit.py                # memory sizing: what fits on a card
+-- doctor.py             # install diagnostics
+-- export.py             # run archive: journal, deliverables, summary
+-- scenarios_loader.py   # scenarios, cassettes and fixtures loading
+-- cli.py                # CLI: run, serve, doctor, export, fit, skills, maintain, validate, new
+-- server.py             # HTTP API, web UI and scheduler (http.server)
+-- web/index.html        # single-page UI, no dependency
+-- web/routing.html      # routing configuration page
+-- web/settings.html     # operations page: inputs, IMAP, scheduling
+-- scenarios/            # cyber-brief, inbox-triage, dataset-report, delegation, self-repair
tests/test_demo.py        # 52 tests: scenarios, sandbox, network, MCP, catalogue, HITL
demo/inputs/              # ready-to-use demo files (audit, CSV)
bench/                    # measurement bench: tasks, prices, simulated endpoint
video/                    # title cards, UI capture and narration script
docs/                     # screenshots, architecture, comparison, scenarios, 3-minute path
```

## Adding a scenario

```bash
python3 -m agentdemo new --slug invoice-triage --title "Invoice triage" \
  --objective "Classify invoices from inbox and write rapport.md."
python3 -m agentdemo validate --slug invoice-triage
python3 -m agentdemo run --scenario invoice-triage
```

A scenario is a folder with `scenario.json`, `cassette.json` (one action per step, `args` keys
matching the tool signature exactly) and `fixtures/`. `validate` cross-checks cassettes against the
real tools: unknown tool, missing or extra argument, missing conclusion. Full format:
[`docs/SCENARIOS.md`](docs/SCENARIOS.md). Three-minute path for a busy reviewer:
[`docs/DEMO.md`](docs/DEMO.md).

## Licence and author

MIT, see `LICENSE`. Author: Loïc Huon.
