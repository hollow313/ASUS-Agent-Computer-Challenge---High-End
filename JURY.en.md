# Vigie, for a jury with twenty minutes

**The problem.** A local agent exists to do multi-step work without sending the data anywhere else, and to
do it again tomorrow without anyone watching. On a 3 GB card, the difficulty is not writing a loop: it is
making that loop verifiable, resumable, and honest about what it cannot do.

**What Vigie does.** It receives an instruction, picks its tools, writes a file, re-reads it, learns from
its mistakes and resumes after a brutal stop. Nine scenarios replayable offline, a free-form instruction in
plain text, image reading, and a daily watch on three real sources whose every run is versioned under
`docs/runs/`.

**The command that proves it**, no key, no network, three seconds:

```bash
git clone https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End && cd ASUS-Agent-Computer-Challenge---High-End
make jury-check
```

It chains the 89 tests, the nine scenarios, cassette validation against the real tools, the installation
diagnostic and the memory sizing, then writes its summary into
[`docs/JURY-CHECK.md`](docs/JURY-CHECK.md). Details of what is demonstrated are in
[`docs/SCENARIOS.md`](docs/SCENARIOS.md), dated measurements in [`docs/mesures/`](docs/mesures) and real
runs in [`docs/runs/`](docs/runs).

**What is demonstrated.** The tests and the scenarios replayed by `make jury-check`. A short, reproducible
live run with a small model: [`docs/runs/live-pico/`](docs/runs/live-pico/README.md). A vision score with
no tolerance, recomputable with `python3 scripts/vision_check.py`, which returns ten exact answers out of
ten. A real, dated watch with its failures: [`docs/production/journal.md`](docs/production/journal.md).

**What is not demonstrated.** Reasoning quality depends on the model installed next to the agent: 60 %
success on a 7B at Q4 on this card, 90 % on the vision model, and none of these numbers say anything about
a 32-billion model, which I could not measure for lack of the card. The 8, 16 and 32 GB tiers are computed
by `python3 -m agentdemo fit`, not measured: [`docs/MATERIEL.md`](docs/MATERIEL.md).

**The target tier is High-End**, the 32 GB card category. What the card changes: a 32-billion model at 4
bits fits in memory (30.4 GB of weights, 1.6 GB of headroom), and with it the second-model review and
parallel sub-agents become the default instead of a setting.

One last point, said plainly: the agent contains no model, and that is deliberate. One command is enough to
plug in Ollama, LM Studio, vLLM or a remote API, with no image rebuild.
