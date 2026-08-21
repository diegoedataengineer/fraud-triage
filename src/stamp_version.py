"""Carimba a versão da release no artefato já validado.

Renomeia o diretório do artefato para a versão da tag e reescreve o campo `version` do
metadata. Não retreina e não altera o modelo — apenas a identificação (Spec 007).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from src.utils import cfg, get_logger, load_config, resolve_path

logger = get_logger("stamp_version")


def main() -> int:
    parser = argparse.ArgumentParser(description="Carimba a versão no artefato.")
    parser.add_argument("--version", required=True, help="versão da release, sem o 'v'")
    args = parser.parse_args()

    config = load_config()
    raiz = resolve_path(cfg(config, "versioning.registry_dir"))
    candidatos = sorted(p for p in raiz.iterdir() if p.is_dir())
    if not candidatos:
        logger.error("Nenhum artefato encontrado em %s", raiz)
        return 1

    origem = candidatos[-1]
    destino = raiz / args.version
    if origem != destino:
        if destino.exists():
            shutil.rmtree(destino)
        origem.rename(destino)

    caminho_meta = destino / cfg(config, "versioning.artifacts")["metadata"]
    metadata = json.loads(caminho_meta.read_text(encoding="utf-8"))
    anterior = metadata.get("version")
    metadata["version"] = args.version
    caminho_meta.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Artefato carimbado: %s → %s", anterior, args.version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
