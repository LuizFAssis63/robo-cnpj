"""Ingestão dos cadastros de sanção do Portal da Transparência.

- CEIS:  empresas inidôneas e suspensas de licitar
- CNEP:  empresas punidas (Lei Anticorrupção)
- CEPIM: entidades sem fins lucrativos impedidas de receber recurso federal

O download exige uma data de referência na URL (AAAAMMDD) e a publicação não é
diária, então tentamos a data de hoje e retrocedemos até achar. Os CSVs vêm com
cabeçalho e, como as colunas diferem entre os três cadastros, a carga localiza
os campos por nome normalizado — mesma estratégia do ingestor da PGFN.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
from rich.console import Console

from .. import db
from ..config import Config
from . import http
from .pgfn import _normalizar

console = Console()

BASE_URL = "https://portaldatransparencia.gov.br/download-de-dados"

CADASTROS = (
    ("CEIS", "ceis"),
    ("CNEP", "cnep"),
    ("CEPIM", "cepim"),
)

DIAS_PARA_TENTAR = 10
TABELA = "sancoes"

ALIASES: dict[str, tuple[str, ...]] = {
    "cpf_cnpj": (
        "cpf_ou_cnpj_do_sancionado",
        "cnpj_ou_cpf_do_sancionado",
        "cpf_cnpj_do_sancionado",
        "cnpj_cpf",
        "cpf_cnpj",
        "cnpj",
    ),
    "nome": (
        "nome_informado_pelo_orgao_sancionador",
        "razao_social_cadastro_receita",
        "nome_do_sancionado",
        "nome_da_entidade",
        "nome",
    ),
    "tipo_sancao": ("tipo_de_sancao", "categoria_da_sancao", "motivo_do_impedimento"),
    "data_inicio": ("data_inicio_sancao", "data_de_inicio_da_sancao", "data_inicio"),
    "data_fim": ("data_final_sancao", "data_de_fim_da_sancao", "data_fim"),
    "orgao_sancionador": (
        "orgao_sancionador",
        "nome_do_orgao_superior",
        "orgao_superior",
        "concedente",
    ),
    "uf": ("uf_do_sancionado", "uf", "uf_da_entidade"),
    "fundamentacao": ("fundamentacao_legal", "descricao_da_fundamentacao_legal"),
}


def _criar_tabela(con) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE "{TABELA}" (
            cpf_cnpj VARCHAR,
            cnpj_basico VARCHAR,
            cadastro VARCHAR,
            nome VARCHAR,
            tipo_sancao VARCHAR,
            data_inicio VARCHAR,
            data_fim VARCHAR,
            orgao_sancionador VARCHAR,
            uf VARCHAR,
            fundamentacao VARCHAR
        )
    """)


def _baixar_mais_recente(slug: str, destino_dir: Path, forcar: bool) -> Path | None:
    """Tenta hoje e retrocede — a publicação não é diária."""
    hoje = dt.date.today()
    for delta in range(DIAS_PARA_TENTAR):
        data = hoje - dt.timedelta(days=delta)
        marca = data.strftime("%Y%m%d")
        url = f"{BASE_URL}/{slug}/{marca}"
        alvo = destino_dir / f"{slug}_{marca}.zip"

        if alvo.exists() and not forcar:
            return alvo
        try:
            return http.baixar(url, alvo, forcar=forcar)
        except httpx.HTTPStatusError:
            continue
        except httpx.HTTPError as erro:
            console.print(f"  [yellow]{slug} {marca}: {erro}[/]")
            continue
    return None


def _carregar(con, csv_path: Path, cadastro: str) -> int:
    leitura = (
        f"read_csv('{csv_path.as_posix()}', delim=';', header=true, "
        f"encoding='latin-1', all_varchar=true, ignore_errors=true, null_padding=true)"
    )
    reais = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {leitura}").fetchall()]
    indice = {_normalizar(c): c for c in reais}

    def col(chave: str) -> str:
        achado = next((indice[a] for a in ALIASES[chave] if a in indice), None)
        return f'"{achado}"' if achado else "NULL"

    if col("cpf_cnpj") == "NULL":
        console.print(f"  [yellow]{csv_path.name}: sem coluna de CNPJ, pulando[/]")
        return 0

    cnpj = f"regexp_replace({col('cpf_cnpj')}, '[^0-9]', '', 'g')"

    antes = con.execute(f'SELECT count(*) FROM "{TABELA}"').fetchone()[0]
    con.execute(f"""
        INSERT INTO "{TABELA}"
        SELECT {cnpj} AS cpf_cnpj,
               substr({cnpj}, 1, 8) AS cnpj_basico,
               '{cadastro}' AS cadastro,
               {col("nome")}, {col("tipo_sancao")},
               {col("data_inicio")}, {col("data_fim")},
               {col("orgao_sancionador")}, {col("uf")}, {col("fundamentacao")}
        FROM {leitura}
        WHERE length({cnpj}) = 14
    """)
    return con.execute(f'SELECT count(*) FROM "{TABELA}"').fetchone()[0] - antes


def executar(cfg: Config, forcar_download: bool = False) -> None:
    console.print("[bold]Portal da Transparência — CEIS / CNEP / CEPIM[/]")

    destino_zip = cfg.caminhos.brutos / "transparencia"
    destino_zip.mkdir(parents=True, exist_ok=True)
    destino_csv = destino_zip / "csv"

    with db.conectar(cfg) as con:
        _criar_tabela(con)

        for rotulo, slug in CADASTROS:
            zip_local = _baixar_mais_recente(slug, destino_zip, forcar_download)
            if not zip_local:
                console.print(
                    f"  [yellow]{rotulo}: nenhum arquivo nos últimos "
                    f"{DIAS_PARA_TENTAR} dias — siga sem este cadastro[/]"
                )
                continue

            total = 0
            for csv_path in http.extrair(zip_local, destino_csv):
                if csv_path.suffix.lower() not in (".csv", ".txt"):
                    continue
                total += _carregar(con, csv_path, rotulo)
                csv_path.unlink()

            console.print(f"  {rotulo}: {total:,} registros PJ".replace(",", "."))

        con.execute(f'CREATE INDEX IF NOT EXISTS idx_sancoes_cnpj ON "{TABELA}" (cnpj_basico)')
