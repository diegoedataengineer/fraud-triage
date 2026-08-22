"""Monta o PDF do relatório: Markdown → HTML → PDF.

    python tools/build_report.py

O PDF é o entregável. Esta etapa é reprodutível como qualquer outra do projeto: a
folha de estilo, a ordem das seções e os diagramas embutidos são todos derivados do
repositório, e nada é montado à mão.

A conversão final usa o Google Chrome em modo headless. Não é elegante, mas é a única
ferramenta de impressão presente no sistema, e produz saída fiel ao que o navegador
renderiza — inclusive os SVG dos diagramas, que entram como vetor e não como imagem
rasterizada.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parent.parent
RELATORIO = RAIZ / "reports" / "relatorio.md"
VISUALIZACAO = RAIZ / "reports" / "ciclo_rotulo.html"
HTML_SAIDA = RAIZ / "reports" / "relatorio.html"
PDF_SAIDA = RAIZ / "reports" / "relatorio.pdf"

# Os diagramas entram ANTES do bloco de citacao que os menciona. Injeta-los dentro
# dele os faria herdar o recuo e o fundo da citacao, comprimindo o desenho.
ANCORA_DIAGRAMAS = re.compile(
    r"<blockquote>\s*<p><strong>Visualização do ciclo completo:</strong>", re.S
)

ESTILO = """
@page { size: A4; margin: 18mm 16mm 20mm; }

* { box-sizing: border-box; }

body {
  font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #16202B; background: #FFF;
  margin: 0; padding: 0;
}

h1 { font-size: 22pt; line-height: 1.2; margin: 0 0 4pt; letter-spacing: -.01em; }
h2 { font-size: 14pt; margin: 20pt 0 7pt; padding-bottom: 4pt;
     border-bottom: .8pt solid #C9D2DB; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 5pt; page-break-after: avoid; }
h4 { font-size: 10pt; margin: 12pt 0 4pt; font-family: "IBM Plex Mono", monospace;
     color: #47576B; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin-bottom: 2.5pt; }
strong { font-weight: 600; }
hr { border: none; border-top: .8pt solid #C9D2DB; margin: 16pt 0; }

blockquote { margin: 9pt 0; padding: 7pt 12pt; border-left: 2.5pt solid #4A6E8A;
             background: #F2F5F8; font-size: 9.8pt; }
blockquote p:last-child { margin-bottom: 0; }

table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt;
        font-size: 9.3pt; page-break-inside: avoid; }
th, td { border: .6pt solid #C9D2DB; padding: 4pt 7pt; text-align: left;
         vertical-align: top; }
th { background: #EEF2F6; font-weight: 600; }
td:nth-child(n+2) { font-variant-numeric: tabular-nums; }

code { font-family: "IBM Plex Mono", "DejaVu Sans Mono", monospace;
       font-size: .87em; background: #F0F3F6; padding: .5pt 3pt; border-radius: 2pt; }
pre { background: #F7F9FB; border: .6pt solid #D8E0E8; border-radius: 3pt;
      padding: 7pt 9pt; overflow-x: auto; font-size: 7.6pt; line-height: 1.42;
      margin: 7pt 0 11pt; page-break-inside: auto; }
pre code { background: none; padding: 0; font-size: inherit; }

img { max-width: 92%; height: auto; display: block; margin: 10pt auto;
      page-break-inside: avoid; }

figure { margin: 12pt 0; page-break-inside: avoid; }
figure svg { max-width: 100%; height: auto; display: block; margin: 0 auto; color: #16202B; }
figcaption { font-size: 8.6pt; color: #56656F; text-align: center; margin-top: 5pt; }

/* A capa ocupa a primeira página inteira; o corpo começa na seguinte. */
h1 + h3 + table { margin-bottom: 24pt; }
h2#_1-introdução { page-break-before: always; }

/* O apêndice de código começa em página nova, para consulta. */
h2#apêndice--código-fonte { page-break-before: always; }
"""


def diagramas() -> str:
    """Extrai as duas figuras SVG da visualização do ciclo de vida."""
    if not VISUALIZACAO.exists():
        return ""
    html = VISUALIZACAO.read_text(encoding="utf-8")
    encontradas = re.findall(r"<figure>.*?</figure>", html, re.S)
    if not encontradas:
        return ""
    # Remove o atributo de rolagem, que não faz sentido em papel.
    return "\n".join(encontradas)


def construir_html() -> str:
    texto = RELATORIO.read_text(encoding="utf-8")
    corpo = markdown.markdown(
        texto,
        extensions=["tables", "fenced_code", "codehilite", "toc", "attr_list"],
        extension_configs={"codehilite": {"guess_lang": False, "noclasses": True,
                                          "pygments_style": "friendly"}},
    )

    figuras = diagramas()
    encontrado = ANCORA_DIAGRAMAS.search(corpo)
    if figuras and encontrado:
        corpo = corpo[: encontrado.start()] + figuras + "\n" + corpo[encontrado.start() :]

    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        "<title>Triagem de Fraude em Transações de Cartão de Crédito</title>"
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
        f"<style>{ESTILO}</style></head><body>{corpo}</body></html>"
    )


def chrome() -> str:
    for nome in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    raise SystemExit("Nenhum navegador encontrado para gerar o PDF.")


def main() -> int:
    HTML_SAIDA.write_text(construir_html(), encoding="utf-8")
    print(f"HTML  → {HTML_SAIDA.relative_to(RAIZ)}  ({HTML_SAIDA.stat().st_size/1024:.0f} KB)")

    resultado = subprocess.run(
        [chrome(), "--headless", "--disable-gpu", "--no-sandbox",
         "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000",
         "--no-pdf-header-footer", f"--print-to-pdf={PDF_SAIDA}", HTML_SAIDA.as_uri()],
        capture_output=True, text=True, timeout=600,
    )
    if not PDF_SAIDA.exists():
        print(resultado.stderr[-1500:], file=sys.stderr)
        raise SystemExit("Falha ao gerar o PDF.")

    print(f"PDF   → {PDF_SAIDA.relative_to(RAIZ)}  ({PDF_SAIDA.stat().st_size/1024/1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
