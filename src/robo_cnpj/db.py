"""Camada DuckDB: conexão, carga de CSV e execução de scripts SQL."""

from __future__ import annotations

import contextlib
import csv
from collections.abc import Iterator
from pathlib import Path

import duckdb

from . import schemas
from .config import Config


class BancoOcupadoError(RuntimeError):
    """Outro processo tem o banco aberto — quase sempre o dashboard."""


@contextlib.contextmanager
def conectar(cfg: Config, somente_leitura: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    try:
        con = duckdb.connect(str(cfg.caminhos.banco), read_only=somente_leitura)
    except duckdb.IOException as erro:
        # DuckDB admite um só escritor, e o erro cru cita um PID sem dizer o que
        # fazer. Não dá para filtrar pela mensagem: ela vem traduzida conforme o
        # locale do Windows. Qualquer IOException ao ABRIR é falha de acesso ao
        # arquivo, então explicamos a causa provável e repassamos o original.
        raise BancoOcupadoError(
            f"Não consegui abrir {cfg.caminhos.banco.name} "
            f"em modo {'leitura' if somente_leitura else 'escrita'}.\n"
            "Causa mais comum: o dashboard está rodando e travou o arquivo. "
            "Pare-o com Ctrl+C antes de ingerir ou transformar.\n"
            f"\nErro original do DuckDB:\n{erro}"
        ) from erro

    try:
        yield con
    finally:
        con.close()


class LayoutInesperadoError(RuntimeError):
    """A Receita mudou o layout do CSV — abortar antes de gravar dados deslocados."""


def conferir_largura(arquivo: Path, tabela: schemas.Tabela, amostra: int = 50) -> None:
    """Conta as colunas reais do CSV e compara com o layout declarado.

    Sem isso, uma coluna nova no meio do arquivo faria toda a carga entrar
    deslocada — razao_social caindo em natureza_juridica, etc. Silencioso e
    catastrófico. Melhor falhar aqui.

    Usa o módulo csv (e não string_split) porque razão social pode conter ';'
    dentro de aspas, e aí contar delimitadores na linha crua daria falso positivo.
    """
    esperado = len(tabela.colunas)
    larguras: set[int] = set()

    with arquivo.open(encoding=schemas.ENCODING, newline="") as fh:
        leitor = csv.reader(fh, delimiter=schemas.DELIMITADOR, quotechar=schemas.QUOTE)
        for i, linha in enumerate(leitor):
            if i >= amostra:
                break
            if linha:
                larguras.add(len(linha))

    if larguras and esperado not in larguras:
        raise LayoutInesperadoError(
            f"{arquivo.name}: layout declarado tem {esperado} colunas, "
            f"o arquivo tem {sorted(larguras)}. Confira o layout oficial em "
            f"https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf "
            f"e atualize schemas.{tabela.nome.upper()}."
        )


def criar_tabela(con: duckdb.DuckDBPyConnection, tabela: schemas.Tabela) -> None:
    colunas = ", ".join(f'"{nome}" {tipo}' for nome, tipo in tabela.colunas)
    con.execute(f'CREATE OR REPLACE TABLE "{tabela.nome}" ({colunas})')


def carregar_csv(
    con: duckdb.DuckDBPyConnection,
    tabela: schemas.Tabela,
    arquivo: Path,
    filtro_uf: str | None = None,
) -> int:
    """Carrega um CSV da Receita na tabela, aplicando filtro de UF quando possível.

    Filtrar na leitura (só `estabelecimentos` tem coluna uf) evita materializar
    milhões de linhas de outros estados no banco.
    """
    conferir_largura(arquivo, tabela)

    colunas_spec = "{" + ", ".join(f"'{n}': '{t}'" for n, t in tabela.colunas) + "}"
    leitura = (
        f"read_csv('{arquivo.as_posix()}', "
        f"delim='{schemas.DELIMITADOR}', quote='{schemas.QUOTE}', header=false, "
        f"columns={colunas_spec}, encoding='{schemas.ENCODING}', "
        f"ignore_errors=true, null_padding=true)"
    )

    where = ""
    if filtro_uf and "uf" in tabela.nomes_colunas:
        where = f" WHERE uf = '{filtro_uf}'"

    antes = _contar(con, tabela.nome)
    con.execute(f'INSERT INTO "{tabela.nome}" SELECT * FROM {leitura}{where}')
    return _contar(con, tabela.nome) - antes


def _contar(con: duckdb.DuckDBPyConnection, tabela: str) -> int:
    return con.execute(f'SELECT count(*) FROM "{tabela}"').fetchone()[0]


def executar_script(con: duckdb.DuckDBPyConnection, arquivo: Path, **params: object) -> None:
    """Roda um .sql do diretório sql/, interpolando parâmetros via str.format.

    Os SQLs usam {chave} para valores de config (UF, pesos do score). São valores
    nossos, de config.yml — não entrada de usuário.
    """
    sql = arquivo.read_text(encoding="utf-8")
    if params:
        sql = sql.format(**params)
    con.execute(sql)
