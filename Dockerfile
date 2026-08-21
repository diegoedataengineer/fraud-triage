# Duas imagens a partir de um Dockerfile: a que TREINA e a que SERVE.
#
# Separá-las não é preciosismo. A imagem de treino carrega Optuna, SHAP, matplotlib
# e o dataset inteiro; a de serving precisa apenas do modelo e do que responde uma
# requisição. Juntá-las levaria dependências de laboratório para dentro do que roda
# em produção — mais superfície de ataque e imagem várias vezes maior, sem ganho.

# ─── base comum: dependências travadas (ADR-0013) ────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libgomp é requisito de runtime do XGBoost; sem ela o import falha em tempo de
# execução, não de build — o tipo de erro que só aparece em produção.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt


# ─── imagem de treino: executa o pipeline e produz o artefato ────────────────
FROM base AS trainer

COPY config/ ./config/
COPY src/ ./src/
COPY monitoring/ ./monitoring/
COPY run_pipeline.py pyproject.toml ./

# Volumes para que dataset e artefatos sobrevivam ao contêiner: retreinar não
# deveria significar baixar 150 MB de novo.
VOLUME ["/app/data", "/app/models", "/app/reports"]

ENTRYPOINT ["python", "run_pipeline.py"]


# ─── imagem de serving: modelo embutido, atrás da API ────────────────────────
FROM base AS serving

COPY config/ ./config/
COPY src/ ./src/
COPY deploy/ ./deploy/

# O artefato entra na imagem em vez de ser baixado na inicialização: é o que faz
# a imagem ser o artefato promovido, imutável e idêntico ao validado (ADR-0017).
COPY models/ ./models/

# Não roda como root. Um processo que só responde HTTP não tem por que ter
# permissão de escrever no próprio código.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["python", "-m", "deploy.api"]
