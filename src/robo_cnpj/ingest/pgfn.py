"""Ingestão da Dívida Ativa da União (PGFN) — o apontamento mais forte do robô.

Publicação trimestral em https://dadosabertos.pgfn.gov.br/, dividida em três
sistemas de origem: dívida geral (não previdenciária), previdenciária e FGTS.

Diferente da Receita, estes CSVs TÊM cabeçalho — e as colunas variam entre os
três arquivos. Por isso a carga usa auto-detecção e depois normaliza só os
campos que o robô consome, em vez de fixar um layout posicional.

Dicionário de campos:
https://www.gov.br/pgfn/pt-br/assuntos/divida-ativa-da-uniao/transparencia-fiscal-1/arquivos-dados-abertos/dicionario_de_campos.xlsx
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import httpx
from rich.console import Console

from .. import db
from ..config import Config
from . import http

console = Console()

BASE_URL = "https://dadosabertos.pgfn.gov.br"

# (rótulo, nome do arquivo ZIP)
CATEGORIAS = (
    ("Dívida Ativa - Geral", "Dados_abertos_Nao_Previdenciario.zip"),
    ("Dívida Ativa - Previdenciária", "Dados_abertos_Previdenciario.zip"),
    ("Dívida Ativa - FGTS", "Dados_abertos_FGTS.zip"),
)

# Nomes normalizados que buscamos → coluna canônica na nossa tabela.
# Cada tupla lista os aliases já vistos entre os três arquivos.
MAPA_COLUNAS: dict[str, tuple[str, ...]] = {
    "cpf_cnpj": ("cpf_cnpj", "cnpj_cpf", "ni_devedor", "cpfcnpj"),
    "tipo_pessoa": ("tipo_pessoa", "tipo_de_pessoa"),
    "tipo_devedor": ("tipo_devedor", "tipo_de_devedor"),
    "nome_devedor": ("nome_devedor", "nome_do_devedor", "nome"),
    "uf_devedor": ("uf_devedor", "uf_unidade_responsavel", "uf"),
    "unidade_responsavel": ("unidade_responsavel", "unidade_de_responsavel"),
    "numero_inscricao": ("numero_inscricao", "numero_da_inscricao"),
    "situacao_inscricao": ("situacao_inscricao", "situacao_da_inscricao"),
    "receita_principal": ("receita_principal", "tipo_de_receita", "receita"),
    "data_inscricao": ("data_inscricao", "data_da_inscricao"),
    "indicador_ajuizado": ("indicador_ajuizado", "ajuizado"),
    "valor_consolidado": ("valor_consolidado", "valor", "valor_total"),
}

TABELA = "divida_ativa_uniao"


def _normalizar(nome: str) -> str:
    """'Valor Consolidado' → 'valor_consolidado'; remove acento e pontuação."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)
    )
    limpo = "".join(c if c.isalnum() else "_" for c in sem_acento.lower())
    return "_".join(p for p in limpo.split("_") if p)


def _resolver(colunas_reais: list[str]) -> dict[str, str | None]:
    """Casa as colunas do arquivo com as canônicas. None quando ausente."""
    indice = {_normalizar(c): c for c in colunas_reais}
    resolvido: dict[str, str | None] = {}
    for canonica, aliases in MAPA_COLUNAS.items():
        resolvido[canonica] = next((indice[a] for a in aliases if a in indice), None)
    return resolvido


def _criar_tabela(con) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE "{TABELA}" (
            cpf_cnpj VARCHAR,
            cnpj_basico VARCHAR,
            tipo_pessoa VARCHAR,
            tipo_devedor VARCHAR,
            nome_devedor VARCHAR,
            uf_devedor VARCHAR,
            unidade_responsavel VARCHAR,
            numero_inscricao VARCHAR,
            situacao_inscricao VARCHAR,
            receita_principal VARCHAR,
            data_inscricao VARCHAR,
            indicador_ajuizado VARCHAR,
            valor_consolidado DOUBLE,
            categoria VARCHAR
        )
    """)


def _carregar(con, csv_path: Path, categoria: str, uf: str) -> int:
    leitura = (
        f"read_csv('{csv_path.as_posix()}', delim=';', header=true, "
        f"encoding='latin-1', all_varchar=true, ignore_errors=true, null_padding=true)"
    )
    colunas_reais = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {leitura}").fetchall()]
    m = _resolver(colunas_reais)

    if not m["cpf_cnpj"]:
        console.print(f"  [yellow]{csv_path.name}: sem coluna de CPF/CNPJ, pulando[/]")
        return 0

    def col(chave: str) -> str:
        real = m[chave]
        return f'"{real}"' if real else "NULL"

    cnpj = f'regexp_replace({col("cpf_cnpj")}, \'[^0-9]\', \'\', \'g\')'

    # Valor vem no formato brasileiro (1.234.567,89) — tira o ponto de milhar
    # antes de trocar a vírgula decimal, senão TRY_CAST devolve NULL.
    valor_real = m["valor_consolidado"]
    if valor_real:
        valor = (
            f"TRY_CAST(replace(replace(\"{valor_real}\", '.', ''), ',', '.') AS DOUBLE)"
        )
    else:
        valor = "NULL"

    # Só pessoa jurídica (14 dígitos) e, quando o arquivo informa UF, só a nossa.
    where = f"WHERE length({cnpj}) = 14"
    if m["uf_devedor"]:
        where += f" AND (upper(trim({col('uf_devedor')})) = '{uf}' OR {col('uf_devedor')} IS NULL)"

    antes = con.execute(f'SELECT count(*) FROM "{TABELA}"').fetchone()[0]
    con.execute(f"""
        INSERT INTO "{TABELA}"
        SELECT {cnpj} AS cpf_cnpj,
               substr({cnpj}, 1, 8) AS cnpj_basico,
               {col("tipo_pessoa")}, {col("tipo_devedor")}, {col("nome_devedor")},
               {col("uf_devedor")}, {col("unidade_responsavel")},
               {col("numero_inscricao")}, {col("situacao_inscricao")},
               {col("receita_principal")}, {col("data_inscricao")},
               {col("indicador_ajuizado")},
               {valor} AS valor_consolidado,
               '{categoria}' AS categoria
        FROM {leitura}
        {where}
    """)
    return con.execute(f'SELECT count(*) FROM "{TABELA}"').fetchone()[0] - antes


def executar(cfg: Config, forcar_download: bool = False) -> None:
    pasta = f"{cfg.pgfn_ano}_trimestre_{cfg.pgfn_trimestre:02d}"
    console.print(f"[bold]PGFN — Dívida Ativa da União[/] ({pasta}, UF={cfg.uf})")

    destino_zip = cfg.caminhos.brutos / "pgfn"
    destino_csv = destino_zip / "csv"

    with db.conectar(cfg) as con:
        _criar_tabela(con)

        for rotulo, nome_zip in CATEGORIAS:
            url = f"{BASE_URL}/{pasta}/{nome_zip}"
            try:
                zip_local = http.baixar(url, destino_zip / nome_zip, forcar=forcar_download)
            except httpx.HTTPStatusError as erro:
                console.print(
                    f"  [yellow]{nome_zip}: HTTP {erro.response.status_code}. "
                    f"Confira se {pasta} já foi publicado.[/]"
                )
                continue

            total = 0
            for csv_path in http.extrair(zip_local, destino_csv):
                if csv_path.suffix.lower() not in (".csv", ".txt"):
                    continue
                total += _carregar(con, csv_path, rotulo, cfg.uf)
                csv_path.unlink()

            console.print(f"  {rotulo}: {total:,} inscrições".replace(",", "."))

        con.execute(f'CREATE INDEX IF NOT EXISTS idx_dau_cnpj ON "{TABELA}" (cnpj_basico)')
