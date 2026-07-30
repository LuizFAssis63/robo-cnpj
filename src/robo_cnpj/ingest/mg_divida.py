"""Ingestão da Dívida Ativa Estadual de Minas Gerais (SEF/AGE-MG).

Fonte: fazenda.mg.gov.br/transparencia/divida-ativa — arquivo publicado sob a
Resolução Conjunta SEF/AGE nº 5.625/2022, que lista as inscrições em Certidão
de Dívida Ativa (CDA) do estado com CNPJ do devedor, valor e data de
inscrição. É o equivalente estadual do que a PGFN publica para a dívida ativa
da União — mas aqui é ICMS e outros tributos estaduais, não federais.

Diferente da Receita/PGFN, não há segmentação por competência nem por UF (o
arquivo já é só de MG): uma única URL fixa, atualizada pela SEF quando querem.
Não existe versão CSV, só .xlsb (Excel binário).

O arquivo cobre ~25 anos de inscrições (quase 300 mil linhas). Carregamos só
os últimos `janela_dias` (padrão 365, ver config.yml) — dívida antiga demais
perde relevância comercial e só infla o banco sem ganho de sinal.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from pathlib import Path

from pyxlsb import open_workbook
from rich.console import Console

from .. import db
from ..config import Config
from . import http

console = Console()

BASE_URL = "https://www.fazenda.mg.gov.br/transparencia/Divida-Ativa/divida-ativa-arquivos"
ARQUIVO = "Resolucao_5625_22_PTA_PJ.xlsb"

TABELA = "divida_ativa_mg"
TAMANHO_LOTE = 5000

# Excel conta datas como inteiro de dias a partir de 1899-12-30 (o "erro do
# ano bissexto de 1900" do Lotus 1-2-3, herdado até hoje).
_EPOCH_EXCEL = datetime.date(1899, 12, 30)


def _serial_para_iso(valor: object) -> str | None:
    if not isinstance(valor, (int, float)):
        return None
    try:
        return (_EPOCH_EXCEL + datetime.timedelta(days=int(valor))).isoformat()
    except (OverflowError, ValueError):
        return None


def _criar_tabela(con) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE "{TABELA}" (
            cpf_cnpj VARCHAR,
            cnpj_basico VARCHAR,
            nome_devedor VARCHAR,
            numero_cda VARCHAR,
            data_inscricao VARCHAR,
            especie VARCHAR,
            saldo_cda DOUBLE,
            saldo_nucleo DOUBLE
        )
    """)


def _linhas_brutas(caminho: Path) -> Iterable[list]:
    """Gera as linhas do .xlsb como listas de valores, pulando o cabeçalho.

    Separado de `_inserir` para que a lógica de filtro/transformação (a parte
    que importa testar) rode sobre uma lista Python comum — sem precisar
    fabricar um .xlsb de verdade nos testes.
    """
    with open_workbook(str(caminho)) as wb, wb.get_sheet(1) as sheet:
        for i, linha in enumerate(sheet.rows()):
            if i == 0:
                continue  # cabeçalho: CNPJ, DEVEDOR PRINCIPAL, Nº CDA, DATA INSCRIÇÃO, ...
            yield [c.v for c in linha]


def _inserir(con, linhas: Iterable[list], corte_serial: float) -> int:
    """Filtra pela janela de datas e insere em lotes."""
    inseridos = 0
    lote: list[tuple] = []

    def _descarregar() -> None:
        nonlocal inseridos
        if lote:
            con.executemany(f'INSERT INTO "{TABELA}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)', lote)
            inseridos += len(lote)
            lote.clear()

    for valores in linhas:
        if len(valores) < 7:
            continue

        cnpj_bruto, nome, cda, data_serial, especie, saldo_cda, saldo_nucleo = valores[:7]

        if not isinstance(data_serial, (int, float)) or data_serial < corte_serial:
            continue

        cnpj = "".join(c for c in str(cnpj_bruto or "") if c.isdigit())
        if len(cnpj) != 14:
            continue  # inscrição estadual que não é CNPJ de 14 dígitos — não é PJ

        lote.append((
            cnpj, cnpj[:8], nome,
            str(cda) if cda is not None else None,
            _serial_para_iso(data_serial), especie,
            float(saldo_cda) if isinstance(saldo_cda, (int, float)) else None,
            float(saldo_nucleo) if isinstance(saldo_nucleo, (int, float)) else None,
        ))

        if len(lote) >= TAMANHO_LOTE:
            _descarregar()

    _descarregar()
    return inseridos


def _carregar(con, caminho: Path, corte_serial: float) -> int:
    return _inserir(con, _linhas_brutas(caminho), corte_serial)


def corte_serial_para(janela_dias: int, hoje: datetime.date | None = None) -> int:
    """Serial Excel do primeiro dia dentro da janela — ponto de corte do filtro."""
    hoje = hoje or datetime.date.today()
    corte = hoje - datetime.timedelta(days=janela_dias)
    return (corte - _EPOCH_EXCEL).days


def executar(cfg: Config, forcar_download: bool = False) -> None:
    hoje = datetime.date.today()
    corte = hoje - datetime.timedelta(days=cfg.mg_divida_janela_dias)
    corte_serial = corte_serial_para(cfg.mg_divida_janela_dias, hoje)

    console.print(
        f"[bold]Dívida Ativa Estadual — MG[/] (SEF/AGE, inscrições desde {corte.isoformat()})"
    )

    destino = cfg.caminhos.brutos / "mg_divida"
    arquivo = http.baixar(f"{BASE_URL}/{ARQUIVO}", destino / ARQUIVO, forcar=forcar_download)

    with db.conectar(cfg) as con:
        _criar_tabela(con)
        total = _carregar(con, arquivo, corte_serial)
        con.execute(f'CREATE INDEX IF NOT EXISTS idx_dam_cnpj ON "{TABELA}" (cnpj_basico)')

    console.print(f"  {total:,} inscrições (últimos {cfg.mg_divida_janela_dias} dias)"
                  .replace(",", "."))
