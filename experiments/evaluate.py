"""Avaliação em lote: repete os cenários e compara IA, health checks e sonda sintética.

Uso:
    python -m experiments.evaluate --repetitions 3
    python -m experiments.evaluate --repetitions 1 --scenarios normal orders_error

Pré-requisito: `docker compose up --build -d --wait` e as variáveis OBS_LLM_* no .env.
Gera `docs/evidencias/avaliacao-<data>/` com `resultados.json` e `relatorio.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from experiments.scenarios import ROOT, SCENARIOS, Lab, evaluate

METHODS = {"health": "Health checks", "probe": "Sonda sintética", "ai": "IA (artefato)"}


def rate(values: list[bool]) -> str:
    if not values:
        return "—"
    hits = sum(values)
    return f"{hits}/{len(values)} ({hits / len(values):.0%})"


def aggregate(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for method in METHODS:
        detection = [r["evaluation"][method]["detection_correct"] for r in results]
        localization = [
            r["evaluation"][method]["localization_correct"]
            for r in results
            if r["expected"]["incident"]
        ]
        false_positives = [
            r["evaluation"][method]["incident"] is True
            for r in results
            if not r["expected"]["incident"]
        ]
        summary[method] = {
            "detection": rate(detection),
            "localization": rate(localization),
            "false_positives": rate(false_positives),
        }
    ai_runs = [r["ai"] for r in results if r["ai"]]
    durations = sorted(run["duration_ms"] for run in ai_runs)
    summary["ai_details"] = {
        "provider_failures": sum(run["outcome"] == "failure" for run in ai_runs),
        "insufficient_evidence": sum(run["outcome"] == "insufficient_evidence" for run in ai_runs),
        "retries": sum(run["attempts"] > 1 for run in ai_runs),
        "median_duration_s": round(durations[len(durations) // 2] / 1000, 1) if durations else None,
        "max_duration_s": round(durations[-1] / 1000, 1) if durations else None,
        "reproduction_failures": sum(not r["ok"] for r in results),
        "not_triggered": sum(r["ai"] is None for r in results),
    }
    return summary


def repetition_range(results: list[dict[str, Any]]) -> str:
    counts = [sum(r["scenario"] == key for r in results) for key in SCENARIOS]
    counts = [count for count in counts if count]
    low, high = min(counts), max(counts)
    return f"{low} repetição(ões)" if low == high else f"{low} a {high} repetições"


def write_outputs(
    output: Path,
    results: list[dict[str, Any]],
    errors: list[dict[str, str]],
    meta: dict[str, Any],
) -> None:
    summary = aggregate(results)
    (output / "resultados.json").write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "results": results, "errors": errors},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "relatorio.md").write_text(report(results, summary, meta), encoding="utf-8")
    print(f"\nRelatório: {output / 'relatorio.md'}")


def rebuild(directory: Path) -> None:
    """Gera o relatório de uma bateria interrompida, com as execuções já gravadas."""
    data = json.loads((directory / "resultados.json").read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = data["results"]
    if not results:
        raise SystemExit("Nenhuma execução registrada.")
    # Recalcula a pontuação com as regras atuais a partir das observações gravadas.
    for result in results:
        result["evaluation"] = evaluate(SCENARIOS[result["scenario"]].expected, result)
    meta = data.get("meta") or {
        "started_at": min(r["timestamp"] for r in results),
        "scenarios": sorted({r["scenario"] for r in results}),
        "model": next((r["ai"]["model"] for r in results if r["ai"]), "—"),
        "errors": data["errors"],
        "interrupted": True,
    }
    write_outputs(directory, results, data["errors"], meta)


def per_scenario_rows(results: list[dict[str, Any]]) -> list[str]:
    rows = []
    for key, scenario in SCENARIOS.items():
        runs = [r for r in results if r["scenario"] == key]
        if not runs:
            continue
        truth = (
            f"incidente em {scenario.expected.service}"
            if scenario.expected.incident
            else "sem incidente"
        )
        cells = []
        for method in METHODS:
            evaluations = [r["evaluation"][method] for r in runs]
            if scenario.expected.incident:
                cells.append(rate([bool(e["localization_correct"]) for e in evaluations]))
            else:
                cells.append(rate([e["detection_correct"] for e in evaluations]))
        rows.append(f"| {scenario.title} | {truth} | " + " | ".join(cells) + " |")
    return rows


def report(
    results: list[dict[str, Any]], summary: dict[str, dict[str, Any]], meta: dict[str, Any]
) -> str:
    details = summary["ai_details"]
    lines = [
        "# Avaliação dos cenários",
        "",
        f"Executado em {meta['started_at']}: {len(results)} execuções, "
        f"{repetition_range(results)} por cenário. Modelo: {meta['model']}.",
        "",
        "Cada execução injeta uma falha conhecida (ou nenhuma, nos controles), gera tráfego "
        "de negócio correlacionado e compara três métodos com o gabarito:",
        "",
        "- **Health checks**: alerta se algum `/health` falha e aponta esse serviço.",
        "- **Sonda sintética**: consulta de negócio pela entrada; detecta falhas, "
        "mas só enxerga o Gateway.",
        "- **IA (artefato)**: diagnóstico sobre logs e snapshots da janela; o serviço apontado "
        "é o da primeira hipótese com serviço.",
        "",
        "## Resultado agregado",
        "",
        "| Método | Detecção correta | Localização correta (incidentes) "
        "| Falsos positivos (controles) |",
        "| --- | --- | --- | --- |",
    ]
    for method, label in METHODS.items():
        s = summary[method]
        lines.append(
            f"| {label} | {s['detection']} | {s['localization']} | {s['false_positives']} |"
        )
    lines += [
        "",
        "## Por cenário",
        "",
        "Incidentes: localização correta. Controles: ausência de alarme.",
        "",
        "| Cenário | Gabarito | Health checks | Sonda sintética | IA (artefato) |",
        "| --- | --- | --- | --- | --- |",
        *per_scenario_rows(results),
        "",
        "## Comportamento da IA",
        "",
        "- Falhas do provedor ou respostas inválidas após correção: "
        f"{details['provider_failures']}",
        f"- Respostas `insufficient_evidence`: {details['insufficient_evidence']}",
        f"- Execuções que precisaram de nova tentativa por validação: {details['retries']}",
        f"- Tempo de diagnóstico: mediana {details['median_duration_s']} s, "
        f"máximo {details['max_duration_s']} s",
        f"- Execuções em que o gatilho automático não acionou a IA: {details['not_triggered']}",
        f"- Execuções em que a falha injetada não se manifestou no tráfego: "
        f"{details['reproduction_failures']}",
        "",
        "Toda citação de evidência é validada contra o contexto antes de aceitar a resposta; "
        "respostas com IDs inexistentes são rejeitadas e reenviadas uma vez para correção.",
        "",
        "## Execuções",
        "",
        "| # | Cenário | Tráfego com falha | IA concluiu | IA apontou | Execução |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, r in enumerate(results, 1):
        ai = r["evaluation"]["ai"]
        lines.append(
            f"| {index} | {r['scenario']} | {r['traffic']['failed']}/{r['traffic']['total']} | "
            f"{ai['outcome']} | {ai['service'] or '—'} | "
            f"{'`' + r['ai']['run_id'] + '`' if r['ai'] else 'IA não acionada'} |"
        )
    lines += [
        "",
        "## Limitações",
        "",
        "- Falhas injetadas e ambiente controlado; não representa tráfego de produção.",
        "- Amostra pequena: os percentuais indicam tendência, não significância estatística.",
        "- O gabarito avalia detecção e serviço de origem, não a qualidade textual da explicação.",
        "- Respostas de LLM variam entre execuções; por isso cada cenário é repetido.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--project", help="Nome do projeto Compose")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Modo automático: a IA só é chamada se o gatilho do etcd disparar",
    )
    parser.add_argument(
        "--from-results",
        type=Path,
        metavar="PASTA",
        help="Só gera o relatório de uma bateria já gravada (por exemplo, interrompida)",
    )
    args = parser.parse_args()
    if args.from_results:
        rebuild(args.from_results)
        return
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions deve estar entre 1 e 20")

    started = datetime.now(UTC)
    output = args.output or ROOT / "docs" / "evidencias" / (
        "avaliacao-" + started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    )
    output.mkdir(parents=True, exist_ok=False)
    lab = Lab(args.project)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total = args.repetitions * len(args.scenarios)
    try:
        for repetition in range(1, args.repetitions + 1):
            for key in args.scenarios:
                label = f"[{len(results) + len(errors) + 1}/{total}] {key} (rep. {repetition})"
                print(label, end=" ... ", flush=True)
                try:
                    observation = lab.execute_auto(key) if args.auto else lab.execute(key)
                except Exception as exc:
                    errors.append({"scenario": key, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"ERRO {exc}", flush=True)
                    continue
                observation["repetition"] = repetition
                results.append(observation)
                ai = observation["evaluation"]["ai"]
                print(
                    f"IA={ai['outcome']}/{ai['service']} "
                    f"detecção={'ok' if ai['detection_correct'] else 'ERRO'} "
                    f"localização={ai['localization_correct']}",
                    flush=True,
                )
                (output / "resultados.json").write_text(
                    json.dumps(
                        {"results": results, "errors": errors}, ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
    finally:
        lab.reset()
        lab.compose("start", "collector")
    if not results:
        print("Nenhuma execução concluída.", file=sys.stderr)
        raise SystemExit(1)
    meta = {
        "started_at": started.isoformat(timespec="seconds"),
        "repetitions": args.repetitions,
        "scenarios": args.scenarios,
        "mode": "auto" if args.auto else "manual",
        "model": next((r["ai"]["model"] for r in results if r["ai"]), "—"),
        "errors": errors,
    }
    write_outputs(output, results, errors, meta)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
