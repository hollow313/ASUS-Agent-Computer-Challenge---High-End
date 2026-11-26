PYTHON ?= python3
PORT ?= 8080

.PHONY: help scenarios run all test serve docker-build docker-run jury-check pico vision clean

help:
	@echo "make scenarios    liste les scénarios"
	@echo "make run          exécute les trois scénarios en CLI"
	@echo "make test         lance la suite de tests"
	@echo "make serve        interface web sur http://localhost:$(PORT)"
	@echo "make docker-build construit l'image"
	@echo "make jury-check   tout ce qui est vérifiable hors ligne, en une page"
	@echo "make docker-run   lance l'image sur le port $(PORT)"

scenarios:
	$(PYTHON) -m agentdemo scenarios

run:
	@for s in cyber-brief inbox-triage dataset-report; do \
		echo "=== $$s"; $(PYTHON) -m agentdemo run --scenario $$s; echo; \
	done

test:
	$(PYTHON) -m unittest discover -s tests -v

serve:
	$(PYTHON) -m agentdemo serve --port $(PORT)

docker-build:
	docker build -t agent-computer-demo:1.0.0 .

docker-run:
	docker run --rm -p $(PORT):8080 agent-computer-demo:1.0.0

clean:
	rm -rf data __pycache__ agentdemo/__pycache__ tests/__pycache__

jury-check:
	$(PYTHON) scripts/jury_check.py

pico:
	$(PYTHON) -m agentdemo run --scenario pico

vision:
	$(PYTHON) scripts/vision_check.py
