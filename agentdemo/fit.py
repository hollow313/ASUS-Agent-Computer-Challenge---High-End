"""Dimensionnement : quels modèles tiennent dans combien de mémoire vidéo.

Le jury note l'adéquation matérielle. Ce module répond à la question par un calcul, pas par une
intention : pour une carte donnée et un contexte donné, quels modèles tiennent entièrement en
mémoire, à quelle quantification, et avec quelle marge.

Deux formules seulement :

* **poids** = paramètres (milliards) × Go par milliard selon la quantification ;
* **cache d'attention** = 2 (clés et valeurs) × couches × têtes KV × dimension de tête × 2 octets
  × contexte en tokens.

Les chiffres de quantification sont des ordres de grandeur (Q4_K_M ≈ 0,62 Go par milliard,
Q5_K_M ≈ 0,73, Q6_K ≈ 0,85, Q8_0 ≈ 1,10, F16 ≈ 2,0), avec une marge de sécurité de 1,5 Go pour
le runtime. Ce n'est pas un benchmark : c'est un calcul de dimensionnement, à vérifier avec le
fichier réellement téléchargé.
"""

from __future__ import annotations

from dataclasses import dataclass

GB_PER_BILLION = {"Q4": 0.62, "Q5": 0.73, "Q6": 0.85, "Q8": 1.10, "F16": 2.0}
RUNTIME_OVERHEAD_GB = 1.5


@dataclass(frozen=True)
class Model:
    name: str
    params_b: float
    layers: int
    kv_heads: int
    head_dim: int

    def weights_gb(self, quant: str) -> float:
        return self.params_b * GB_PER_BILLION[quant]

    def kv_cache_gb(self, context: int) -> float:
        """Cache d'attention en Go pour un contexte donné, en f16."""
        per_token = 2 * self.layers * self.kv_heads * self.head_dim * 2
        return per_token * context / 1e9

    def total_gb(self, quant: str, context: int) -> float:
        return self.weights_gb(quant) + self.kv_cache_gb(context) + RUNTIME_OVERHEAD_GB


# Ordres de grandeur, configuration publiée des modèles ouverts les plus courants.
MODELS = [
    Model("qwen2.5-coder-7b", 7.6, 28, 4, 128),
    Model("llama-3.1-8b", 8.0, 32, 8, 128),
    Model("qwen3-vl-8b", 8.2, 36, 8, 128),
    Model("qwen2.5-coder-14b", 14.7, 48, 4, 128),
    Model("mistral-small-24b", 23.6, 40, 8, 128),
    Model("qwen2.5-coder-32b", 32.8, 64, 8, 128),
    Model("llama-3.3-70b", 70.6, 80, 8, 128),
]

QUANTS = ("Q4", "Q5", "Q6", "Q8")


def fits(vram_gb: float, model: Model, quant: str, context: int) -> tuple[bool, float, float]:
    """Retourne (ça tient, mémoire totale, marge restante)."""
    total = model.total_gb(quant, context)
    return total <= vram_gb, round(total, 1), round(vram_gb - total, 1)


def plan(vram_gb: float, context: int = 32768, models: list[Model] | None = None) -> list[dict]:
    """Meilleure quantification qui tient pour chaque modèle, sinon la plus petite essayée."""
    rows = []
    for model in models or MODELS:
        best = None
        # du plus fidèle au plus compressé : on garde la meilleure quantification qui tient
        for quant in sorted(QUANTS, key=lambda q: GB_PER_BILLION[q], reverse=True):
            ok, total, margin = fits(vram_gb, model, quant, context)
            if ok:
                best = {"quant": quant, "total": total, "margin": margin}
                break
        if best is None:
            _, total, margin = fits(vram_gb, model, QUANTS[0], context)
            rows.append(
                {
                    "model": model.name,
                    "params_b": model.params_b,
                    "quant": "ne rentre pas",
                    "total": total,
                    "margin": margin,
                }
            )
        else:
            rows.append(
                {
                    "model": model.name,
                    "params_b": model.params_b,
                    "quant": best["quant"],
                    "total": best["total"],
                    "margin": best["margin"],
                }
            )
    return rows


def table(vram_gb: float, context: int = 32768) -> str:
    header = f"{'modèle':<24} {'taille':>8} {'quant':>12} {'mémoire':>9} {'marge':>8}"
    lines = [
        f"carte simulée : {vram_gb} Go · contexte {context // 1024} k · marge runtime {RUNTIME_OVERHEAD_GB} Go",
        "",
        header,
        "-" * len(header),
    ]
    for row in plan(vram_gb, context):
        fits_ok = row["quant"] != "ne rentre pas"
        lines.append(
            f"{row['model']:<24} {row['params_b']:>6.1f} B {row['quant']:>12} "
            f"{row['total']:>7.1f} Go {row['margin']:>6.1f} Go" + ("" if fits_ok else "   (hors budget)")
        )
    lines.append("")
    lines.append(
        "hors budget = ne tient pas entièrement en mémoire vidéo ; le runtime bascule alors une partie"
    )
    lines.append(
        "des couches sur le CPU, ce qui explique les latences mesurées sur une carte trop petite."
    )
    return "\n".join(lines)
