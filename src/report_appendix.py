"""Gera o apêndice de código-fonte do relatório.

O apêndice é **gerado**, não escrito à mão. Código copiado para dentro de um documento
diverge do código real no primeiro ajuste, e um relatório que mostra uma versão enquanto
o repositório roda outra é pior que um relatório sem código.

    python -m src.report_appendix

Substitui o conteúdo entre os marcadores em `reports/relatorio.md`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.utils import get_logger, resolve_path

logger = get_logger("apendice")

INICIO = "<!-- INICIO-APENDICE-CODIGO -->"
FIM = "<!-- FIM-APENDICE-CODIGO -->"

# Ordem pela lógica do pipeline, não alfabética: quem lê o apêndice está seguindo o
# caminho do dado, do arquivo bruto até o serviço em execução.
SECOES: list[tuple[str, str, list[str]]] = [
    ("A", "Configuração central", ["config/config.yaml", "config/model_params.lock.json"]),
    ("B", "Utilidades e ingestão", ["src/utils.py", "src/ingestion.py", "src/eda.py"]),
    ("C", "Preparação dos dados", ["src/preprocessing.py"]),
    ("D", "Seleção, treino e calibração",
     ["src/model_selection.py", "src/train.py", "src/calibration.py"]),
    ("E", "Política de decisão e avaliação",
     ["src/policy.py", "src/evaluate.py", "src/figures.py"]),
    ("F", "Explicabilidade", ["src/explainability.py"]),
    ("G", "Monitoramento", ["monitoring/drift_monitor.py"]),
    ("H", "Artefato e versionamento",
     ["src/artifacts.py", "src/verify_minimums.py", "src/stamp_version.py"]),
    ("I", "Orquestração", ["run_pipeline.py"]),
    ("J", "Serviço e demonstração", ["deploy/api.py", "src/db.py", "deploy/demo_faker.py"]),
    ("K", "Persistência", ["db/schema.sql"]),
    ("L", "Empacotamento", ["Dockerfile", "docker-compose.yml",
                            "docker-compose.build.yml", "requirements.txt",
                            "requirements-serving.txt"]),
    ("M", "Esteira de integração e entrega",
     [".github/workflows/ci.yml", ".github/workflows/release.yml",
      ".github/workflows/deploy-production.yml", ".github/workflows/commitlint.yml",
      "release-please-config.json", ".commitlintrc.json"]),
    ("N", "Testes", ["tests/test_invariants.py"]),
]

LINGUAGEM = {
    ".py": "python", ".yml": "yaml", ".yaml": "yaml",
    ".sql": "sql", ".json": "json", ".txt": "text", "": "dockerfile",
}


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
            cwd=resolve_path("."), timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return "desconhecido"


def gerar() -> str:
    partes: list[str] = []
    total_linhas = 0
    total_arquivos = 0

    partes.append("## Apêndice — Código-fonte\n")
    partes.append(
        "Listagem integral do código que produziu os resultados deste relatório, no "
        f"commit `{_git_sha()}`. As seções seguem a ordem do pipeline — do arquivo bruto "
        "ao serviço em execução — e não a ordem alfabética.\n\n"
        "Este apêndice é **gerado a partir dos arquivos do repositório**, não transcrito. "
        "Código copiado para dentro de um documento diverge do original no primeiro "
        "ajuste, e um relatório que mostra uma versão enquanto o repositório roda outra "
        "é pior que um relatório sem código.\n"
    )

    for letra, titulo, arquivos in SECOES:
        existentes = [a for a in arquivos if resolve_path(a).exists()]
        if not existentes:
            continue
        partes.append(f"\n### {letra}. {titulo}\n")
        for caminho in existentes:
            p = resolve_path(caminho)
            conteudo = p.read_text(encoding="utf-8").rstrip()
            n = conteudo.count("\n") + 1
            total_linhas += n
            total_arquivos += 1
            partes.append(f"\n#### `{caminho}` · {n} linhas\n")
            partes.append(f"```{LINGUAGEM.get(p.suffix, 'text')}\n{conteudo}\n```\n")

    partes.insert(
        2,
        f"\n**{total_arquivos} arquivos · {total_linhas:,} linhas.**\n".replace(",", "."),
    )
    logger.info("Apêndice gerado: %d arquivos, %d linhas", total_arquivos, total_linhas)
    return "".join(partes)


def aplicar() -> None:
    relatorio = resolve_path("reports/relatorio.md")
    texto = relatorio.read_text(encoding="utf-8")
    apendice = gerar()

    if INICIO in texto and FIM in texto:
        antes = texto.split(INICIO)[0]
        depois = texto.split(FIM)[1]
        novo = f"{antes}{INICIO}\n\n{apendice}\n{FIM}{depois}"
    else:
        novo = f"{texto.rstrip()}\n\n---\n\n{INICIO}\n\n{apendice}\n{FIM}\n"

    relatorio.write_text(novo, encoding="utf-8")
    logger.info("Relatório atualizado: %d linhas", novo.count("\n") + 1)


if __name__ == "__main__":
    aplicar()
