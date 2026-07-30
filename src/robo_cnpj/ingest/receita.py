"""Ingestão da base CNPJ dos Dados Abertos da Receita Federal.

A Receita publica mensalmente em https://dadosabertos.rfb.gov.br/CNPJ/, hoje
organizado em subpastas por competência (AAAA-MM). Como esse arranjo já mudou
uma vez, a competência é descoberta lendo o índice em vez de ficar fixa no
código — se a estrutura mudar de novo, só `descobrir_competencia` precisa mexer.

Volume: ~5GB compactados, ~50GB em CSV. Use `fatias` no config.yml para
trabalhar com um pedaço durante o desenvolvimento.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console

from .. import db, schemas
from ..config import Config
from . import http

console = Console()

PADRAO_COMPETENCIA = re.compile(r'href="(\d{4}-\d{2})/"')

# Pausa entre um arquivo e o próximo — ser um cliente educado com um servidor
# que já sabemos ser instável reduz a chance de sermos limitados ou bloqueados.
PAUSA_ENTRE_ARQUIVOS_S = 2.0


@dataclass(frozen=True)
class ArquivoRemoto:
    tabela: schemas.Tabela
    nome_zip: str
    url: str


def descobrir_competencia(
    base_url: str, cache: Path | None = None, forcar: bool = False
) -> str | None:
    """Retorna a competência mais recente (ex: '2026-06'), ou None se os ZIPs
    estiverem soltos na raiz (layout antigo).

    Guarda o resultado em `cache` — um request a menos contra um índice que já
    sabemos instável, em cada execução seguinte. `forcar` ignora o cache.
    """
    if cache and cache.exists() and not forcar:
        valor = cache.read_text(encoding="utf-8").strip()
        return valor or None

    def _tentativa() -> str | None:
        resposta = httpx.get(base_url + "/", headers=http.CABECALHOS, timeout=http.TIMEOUT,
                             follow_redirects=True)
        resposta.raise_for_status()

        competencias = sorted(set(PADRAO_COMPETENCIA.findall(resposta.text)))
        if competencias:
            return competencias[-1]

        if ".zip" in resposta.text.lower():
            return None

        raise RuntimeError(
            f"Não encontrei nem subpastas de competência nem ZIPs em {base_url}. "
            "A estrutura do portal mudou — ajuste descobrir_competencia()."
        )

    resultado = http.repetir_com_backoff(_tentativa, "índice da Receita")

    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(resultado or "", encoding="utf-8")

    return resultado


def listar_arquivos(cfg: Config, competencia: str | None) -> list[ArquivoRemoto]:
    raiz = cfg.receita_base_url
    if competencia:
        raiz = f"{raiz}/{competencia}"

    arquivos: list[ArquivoRemoto] = []
    for tabela in schemas.TODAS_TABELAS:
        if tabela.fatiada:
            for i in range(cfg.receita_fatias):
                nome = f"{tabela.prefixo_zip}{i}.zip"
                arquivos.append(ArquivoRemoto(tabela, nome, f"{raiz}/{nome}"))
        else:
            nome = f"{tabela.prefixo_zip}.zip"
            arquivos.append(ArquivoRemoto(tabela, nome, f"{raiz}/{nome}"))
    return arquivos


def executar(cfg: Config, forcar_download: bool = False) -> None:
    destino_zip = cfg.caminhos.brutos / "receita"
    destino_csv = destino_zip / "csv"

    competencia = descobrir_competencia(
        cfg.receita_base_url, cache=destino_zip / "_competencia.txt", forcar=forcar_download
    )
    console.print(
        f"[bold]Receita Federal[/] — competência "
        f"{competencia or 'raiz (layout antigo)'}, filtrando UF={cfg.uf}"
    )

    arquivos = listar_arquivos(cfg, competencia)

    # Uma tabela é recriada na primeira fatia e recebe INSERT nas seguintes.
    tabelas_criadas: set[str] = set()

    with db.conectar(cfg) as con:
        for indice, remoto in enumerate(arquivos):
            if indice > 0:
                time.sleep(PAUSA_ENTRE_ARQUIVOS_S)

            try:
                zip_local = http.baixar(remoto.url, destino_zip / remoto.nome_zip,
                                        forcar=forcar_download)
            except httpx.HTTPStatusError as erro:
                if erro.response.status_code == 404:
                    console.print(f"  [yellow]{remoto.nome_zip}: não existe (404), pulando[/]")
                    continue
                raise

            if remoto.tabela.nome not in tabelas_criadas:
                db.criar_tabela(con, remoto.tabela)
                tabelas_criadas.add(remoto.tabela.nome)

            # `estabelecimentos` é a única tabela com coluna uf — as outras se
            # filtram depois, por join com o universo (ver sql/02_universo.sql).
            filtro = cfg.uf if "uf" in remoto.tabela.nomes_colunas else None

            total = 0
            for csv_path in http.extrair(zip_local, destino_csv,
                                         sufixo=remoto.tabela.sufixo_arquivo):
                total += db.carregar_csv(con, remoto.tabela, csv_path, filtro_uf=filtro)
                csv_path.unlink()  # ~50GB se acumular; o ZIP fica como cache

            rotulo = f" (UF={filtro})" if filtro else ""
            console.print(f"  {remoto.nome_zip} → {remoto.tabela.nome}: "
                          f"{total:,} linhas{rotulo}".replace(",", "."))

        _criar_indices(con, tabelas_criadas)


def _criar_indices(con, tabelas: set[str]) -> None:
    """Índice em cnpj_basico — é a chave de todos os joins do pipeline."""
    for tabela in tabelas:
        if "cnpj_basico" in [c for c, _ in _colunas(con, tabela)]:
            con.execute(f'CREATE INDEX IF NOT EXISTS idx_{tabela}_cnpj '
                        f'ON "{tabela}" (cnpj_basico)')


def _colunas(con, tabela: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in con.execute(f'DESCRIBE "{tabela}"').fetchall()]
