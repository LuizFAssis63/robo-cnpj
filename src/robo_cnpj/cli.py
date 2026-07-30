"""CLI do robô.

    python -m robo_cnpj ingerir        # baixa e carrega todas as fontes
    python -m robo_cnpj transformar    # monta universo, apontamentos e score
    python -m robo_cnpj exportar       # gera a planilha
    python -m robo_cnpj servir         # sobe o dashboard
    python -m robo_cnpj tudo           # pipeline completo
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import config, export, transform
from .ingest import mg_divida, pgfn, receita, transparencia

app = typer.Typer(add_completion=False, help="Robô de prospecção de CNPJ para contabilidade.")
console = Console()

FONTES = {
    "receita": ("Base CNPJ (Receita Federal)", receita.executar),
    "pgfn": ("Dívida Ativa da União (PGFN)", pgfn.executar),
    "mg_divida": ("Dívida Ativa Estadual (SEF/AGE-MG)", mg_divida.executar),
    "transparencia": ("Sanções (CEIS/CNEP/CEPIM)", transparencia.executar),
}


@app.command()
def ingerir(
    fonte: Annotated[
        list[str] | None,
        typer.Option("--fonte", "-f", help="receita | pgfn | transparencia. Repetível."),
    ] = None,
    forcar: Annotated[bool, typer.Option("--forcar", help="Rebaixa os ZIPs já em cache.")] = False,
) -> None:
    """Baixa e carrega os dados abertos no DuckDB."""
    cfg = config.carregar()
    escolhidas = fonte or list(FONTES)

    desconhecidas = set(escolhidas) - set(FONTES)
    if desconhecidas:
        console.print(f"[red]Fonte desconhecida: {', '.join(sorted(desconhecidas))}[/]")
        raise typer.Exit(1)

    for chave in escolhidas:
        rotulo, funcao = FONTES[chave]
        console.rule(f"[bold]{rotulo}")
        funcao(cfg, forcar_download=forcar)


@app.command()
def transformar() -> None:
    """Monta universo, apontamentos, regime provável e score."""
    cfg = config.carregar()
    console.rule("[bold]Transformação")
    transform.executar(cfg)


@app.command()
def exportar(
    saida: Annotated[Path | None, typer.Option("--saida", "-o")] = None,
    limite: Annotated[int | None, typer.Option("--limite", "-n")] = None,
    minimo_apontamentos: Annotated[
        int, typer.Option("--min-apontamentos", help="Só leads com N+ apontamentos.")
    ] = 0,
) -> None:
    """Gera a planilha Excel para a contabilidade."""
    cfg = config.carregar()
    export.executar(cfg, destino=saida, limite=limite,
                    minimo_apontamentos=minimo_apontamentos)


@app.command()
def resumo() -> None:
    """Mostra o panorama dos leads já processados."""
    transform.resumo(config.carregar())


@app.command()
def amostra() -> None:
    """Popula o banco com dados sintéticos, para ver o dashboard sem baixar nada.

    Sobrescreve o banco atual. Rode `ingerir` depois para voltar aos dados reais.
    """
    import sys

    sys.path.insert(0, str(config.RAIZ / "tests"))
    import amostra as fixture  # noqa: PLC0415

    from . import db, schemas  # noqa: PLC0415
    from .ingest import mg_divida as ing_mg  # noqa: PLC0415
    from .ingest import pgfn as ing_pgfn  # noqa: PLC0415
    from .ingest import transparencia as ing_transp  # noqa: PLC0415

    cfg = config.carregar()
    console.rule("[bold]Amostra sintética")
    console.print("[yellow]Dados fictícios — apenas para conhecer a interface.[/]")

    destino = cfg.caminhos.brutos / "amostra"
    arquivos = fixture.gerar(destino)

    with db.conectar(cfg) as con:
        for tabela in schemas.TODAS_TABELAS:
            db.criar_tabela(con, tabela)
            filtro = cfg.uf if "uf" in tabela.nomes_colunas else None
            db.carregar_csv(con, tabela, arquivos[tabela.nome], filtro_uf=filtro)

        ing_pgfn._criar_tabela(con)
        ing_pgfn._carregar(con, arquivos["dau"], "Dívida Ativa - Geral", cfg.uf)
        ing_transp._criar_tabela(con)
        ing_transp._carregar(con, arquivos["sancoes"], "CEIS")
        ing_mg._criar_tabela(con)
        ing_mg._inserir(con, fixture.divida_mg_linhas(),
                        ing_mg.corte_serial_para(cfg.mg_divida_janela_dias))

    transform.executar(cfg)
    console.print("\nAgora rode: [bold]python -m robo_cnpj servir[/]")


@app.command()
def servir(
    porta: Annotated[int, typer.Option("--porta", "-p")] = 8000,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
) -> None:
    """Sobe a API e o dashboard web."""
    import uvicorn

    console.print(f"[green]Dashboard em[/] http://{host}:{porta}")
    uvicorn.run("robo_cnpj.api:app", host=host, port=porta, log_level="info")


@app.command()
def tudo(
    forcar: Annotated[bool, typer.Option("--forcar")] = False,
) -> None:
    """Pipeline completo: ingerir, transformar e exportar."""
    ingerir(fonte=None, forcar=forcar)
    transformar()
    exportar()


def main() -> None:
    """Ponto de entrada. Converte erros esperados em mensagem limpa."""
    from .db import BancoOcupadoError, LayoutInesperadoError
    from .ingest.http import ConexaoIndisponivelError

    try:
        app()
    except (BancoOcupadoError, LayoutInesperadoError, ConexaoIndisponivelError) as erro:
        console.print(f"\n[red]{erro}[/]")
        raise typer.Exit(1) from erro


if __name__ == "__main__":
    main()
