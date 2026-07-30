"""Executa os SQLs de transformação, injetando os parâmetros do config.yml."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from . import db, schemas
from .config import Config

console = Console()

ETAPAS = (
    ("01_universo.sql", "Universo de leads (fora do Simples/MEI)"),
    ("02_apontamentos.sql", "Apontamentos (dívida ativa, situação, sanções)"),
    ("03_leads.sql", "Regime provável e score"),
)


def _milhar(n: int) -> str:
    """1234567 → '1.234.567' (padrão brasileiro)."""
    return f"{n:,}".replace(",", ".")


def _reais(v: float) -> str:
    """1234567.89 → 'R$ 1.234.567,89'."""
    return "R$ " + f"{v:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def _lista_sql(valores: list[str]) -> str:
    """['02','03'] → \"('02', '03')\" para uso em IN (...)."""
    return "(" + ", ".join(f"'{v}'" for v in valores) + ")"


def _lista_duckdb(valores: tuple[str, ...]) -> str:
    """Literal de lista do DuckDB, para list_contains."""
    return "[" + ", ".join(f"'{v}'" for v in valores) + "]"


def _parametros(cfg: Config) -> dict[str, object]:
    return {
        "uf": cfg.uf,
        "situacoes_cadastrais": _lista_sql(cfg.situacoes_cadastrais),
        "prefixo_natureza_juridica": cfg.prefixo_natureza_juridica,
        "somente_matriz": "TRUE" if cfg.somente_matriz else "FALSE",
        "somente_com_apontamento": "TRUE" if cfg.somente_com_apontamento else "FALSE",
        "cnaes_lucro_real": _lista_duckdb(schemas.CNAE_PREFIXOS_LUCRO_REAL_OBRIGATORIO),
        "capital_lucro_real": cfg.capital_lucro_real,
        "peso_divida_ativa_uniao": cfg.score["peso_divida_ativa_uniao"],
        "peso_divida_ativa_mg": cfg.score["peso_divida_ativa_mg"],
        "peso_situacao_irregular": cfg.score["peso_situacao_irregular"],
        "peso_sancao": cfg.score["peso_sancao"],
        "peso_saiu_do_simples": cfg.score["peso_saiu_do_simples"],
        "peso_porte_demais": cfg.score["peso_porte_demais"],
    }


def _garantir_tabelas_opcionais(con) -> None:
    """Cria vazias as tabelas de apontamento que ainda não foram ingeridas.

    Assim `transform` roda depois de ingerir só a Receita, sem quebrar os joins —
    o resultado sai sem apontamentos externos, o que é correto e não um erro.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS divida_ativa_uniao (
            cpf_cnpj VARCHAR, cnpj_basico VARCHAR, tipo_pessoa VARCHAR,
            tipo_devedor VARCHAR, nome_devedor VARCHAR, uf_devedor VARCHAR,
            unidade_responsavel VARCHAR, numero_inscricao VARCHAR,
            situacao_inscricao VARCHAR, receita_principal VARCHAR,
            data_inscricao VARCHAR, indicador_ajuizado VARCHAR,
            valor_consolidado DOUBLE, categoria VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sancoes (
            cpf_cnpj VARCHAR, cnpj_basico VARCHAR, cadastro VARCHAR, nome VARCHAR,
            tipo_sancao VARCHAR, data_inicio VARCHAR, data_fim VARCHAR,
            orgao_sancionador VARCHAR, uf VARCHAR, fundamentacao VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS divida_ativa_mg (
            cpf_cnpj VARCHAR, cnpj_basico VARCHAR, nome_devedor VARCHAR,
            numero_cda VARCHAR, data_inscricao VARCHAR, especie VARCHAR,
            saldo_cda DOUBLE, saldo_nucleo DOUBLE
        )
    """)


def executar(cfg: Config) -> None:
    params = _parametros(cfg)

    with db.conectar(cfg) as con:
        _garantir_tabelas_opcionais(con)

        for arquivo, descricao in ETAPAS:
            console.print(f"[cyan]›[/] {descricao}")
            db.executar_script(con, cfg.caminhos.sql / arquivo, **params)

        resumo(cfg, con)


def resumo(cfg: Config, con=None) -> None:
    """Imprime o panorama do que o robô encontrou."""
    fechar = con is None
    if fechar:
        ctx = db.conectar(cfg, somente_leitura=True)
        con = ctx.__enter__()

    try:
        total_universo = con.execute("SELECT count(*) FROM universo").fetchone()[0]

        linha = con.execute("""
            SELECT
                count(*),
                count_if(tem_divida_ativa_uniao),
                sum(CASE WHEN tem_divida_ativa_uniao THEN dau_valor_total ELSE 0 END),
                count_if(tem_divida_ativa_mg),
                sum(CASE WHEN tem_divida_ativa_mg THEN dam_valor_total ELSE 0 END),
                count_if(situacao_irregular),
                count_if(tem_sancao),
                count_if(saiu_do_simples),
                count_if(regime_provavel LIKE 'Lucro Real%'),
                count_if(regime_provavel LIKE 'Lucro Presumido%'),
                count_if(qtd_apontamentos > 0)
            FROM leads
        """).fetchone()

        (total, com_dau, valor_dau, com_dam, valor_dam, irregular, sancionadas,
         ex_simples, real, presumido, com_apontamento) = linha

        tabela = Table(title=f"Leads em {cfg.uf}", show_header=False, title_style="bold")
        tabela.add_column(style="cyan")
        tabela.add_column(justify="right", style="bold")

        def pct(n: int) -> str:
            return _milhar(n) + (f"  ({n / total:.1%})" if total else "")

        if cfg.somente_com_apontamento:
            # `leads` já é só quem tem apontamento — o filtro tira o resto
            # antes de chegar na planilha/dashboard, é isso que "reduz os dados".
            tabela.add_row("Fora do Simples/MEI em MG (universo bruto)", _milhar(total_universo))
            tabela.add_row("Com apontamento → viram lead", _milhar(total))
            tabela.add_row(
                "Descartadas por não terem apontamento",
                _milhar(total_universo - total),
            )
        else:
            tabela.add_row("Total no universo (fora do Simples/MEI)", pct(total))
            tabela.add_row("Com ao menos um apontamento", pct(com_apontamento))

        tabela.add_row("", "")
        tabela.add_row("Lucro Real provável", pct(real))
        tabela.add_row("Lucro Presumido provável", pct(presumido))
        tabela.add_row("", "")
        tabela.add_row("Com dívida ativa da União", pct(com_dau))
        tabela.add_row("Valor total em dívida ativa (União)", _reais(valor_dau or 0.0))
        tabela.add_row("Com dívida ativa estadual (MG)", pct(com_dam))
        tabela.add_row("Valor total em dívida ativa (MG)", _reais(valor_dam or 0.0))
        tabela.add_row("Situação cadastral irregular", pct(irregular))
        tabela.add_row("Com sanção (CEIS/CNEP/CEPIM)", pct(sancionadas))
        tabela.add_row("Excluídas do Simples", pct(ex_simples))

        console.print(tabela)
    finally:
        if fechar:
            ctx.__exit__(None, None, None)
