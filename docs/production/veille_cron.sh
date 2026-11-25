#!/usr/bin/env bash
# Veille quotidienne versionnée, lancée par le planificateur.
#
# Trois garanties, dans cet ordre :
#   1. si LM Studio ne répond pas, on n'invente rien : une ligne « absent » est ajoutée au journal,
#      et le script sort en 0 sans toucher au dépôt (un jour sans run doit se voir, pas se cacher) ;
#   2. si le run tourne, il est versionné (docs/runs/<date>-veille/) puis poussé ;
#   3. si le run échoue, la ligne d'échec est quand même poussée : la série dit la vérité.
#
# Usage : veille_cron.sh [--model NOM] [--base-url URL]

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

MODEL="${AGENTDEMO_LLM_MODEL:-qwen/qwen3-vl-8b}"
BASE_URL="${AGENTDEMO_LLM_BASE_URL:-http://192.168.1.153:1234/v1}"
LOG="$REPO/docs/production/veille-cron.log"

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] démarrage, modèle $MODEL sur $BASE_URL" >>"$LOG"

# 1. le modèle est-il joignable ?
code=$(curl -s -o /dev/null -w "%{http_code}" -m 12 "$BASE_URL/models" || echo 000)
if [ "$code" != "200" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] endpoint injoignable (HTTP $code) : ligne absent, rien de poussé" >>"$LOG"
  python3 - "$REPO" <<'PY'
import sys
from datetime import datetime, timezone
from pathlib import Path
repo = Path(sys.argv[1])
journal = repo / "docs" / "production" / "journal.md"
stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
row = f"| {stamp} | absent | — | — | aucun (machine éteinte) | — |\n"
text = journal.read_text(encoding="utf-8")
if f"| {stamp} |" not in text:
    journal.write_text(text.rstrip("\n") + "\n" + row, encoding="utf-8")
PY
  exit 0
fi

# 2. le run, avec le même budget de temps que la fois où il a réussi
AGENTDEMO_DATA_DIR="${AGENTDEMO_DATA_DIR:-$REPO/../veille-data}" \
  python3 docs/production/veille.py --once --base-url "$BASE_URL" --model "$MODEL" --timeout 420 \
  >>"$LOG" 2>&1
status=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] run terminé, code $status" >>"$LOG"

# 3. on pousse ce qui existe, échec compris : le dépôt porte la série, pas seulement les bons jours
git add docs/runs docs/production/journal.md >/dev/null 2>&1
if git diff --cached --quiet; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] rien de nouveau à pousser" >>"$LOG"
  exit 0
fi
git -c user.name="Hollow" -c user.email="9007044+hollow313@users.noreply.github.com" \
  commit -q -m "Veille du $(date -u +%Y-%m-%d) : run versionné" >>"$LOG" 2>&1
git push -q origin main >>"$LOG" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] poussé (code $?)" >>"$LOG"

# une ligne lisible pour la notification du planificateur
python3 - "$REPO" <<'PY'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
metas = sorted((repo / "docs" / "runs").glob("*-veille*/meta.json"))
if not metas:
    print("veille : aucun run versionné")
    raise SystemExit(0)
last = json.loads(metas[-1].read_text(encoding="utf-8"))
print(
    f"veille {last.get('date')} · {last.get('status')} · {last.get('steps')} étapes · "
    f"{last.get('items')} entrées · {last.get('sources_fetched')} source(s) lue(s) · "
    f"{int(float(last.get('duration_s') or 0) // 60)} min"
)
PY
exit 0
