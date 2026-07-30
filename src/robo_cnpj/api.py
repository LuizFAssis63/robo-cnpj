"""API do dashboard.

Abre o DuckDB em modo somente-leitura uma vez por processo e entrega um *cursor*
por requisição. O cursor não é enfeite: os endpoints são `def` síncronos, que o
FastAPI executa num threadpool, então duas requisições simultâneas — a página
dispara /api/resumo e /api/municipios juntas — chegam ao mesmo objeto de
conexão. Um `execute()` seguido de `fetchall()` numa conexão compartilhada
embaralha o resultado entre as threads, e um endpoint acaba lendo as linhas do
outro. `cursor()` isola cada requisição sobre o mesmo banco.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config

cfg = config.carregar()
app = FastAPI(title="Robô CNPJ", version="0.1.0")

_base: duckdb.DuckDBPyConnection | None = None
_trava = threading.Lock()

ORDENACOES = {
    "score": "score DESC, dau_valor_total DESC",
    "divida": "dau_valor_total DESC",
    "divida_mg": "dam_valor_total DESC",
    "capital": "capital_social DESC NULLS LAST",
    "razao_social": "razao_social ASC",
}


def _conexao_base() -> duckdb.DuckDBPyConnection:
    """Conexão única do processo. A trava evita duas aberturas simultâneas."""
    global _base
    with _trava:
        if _base is None:
            if not cfg.caminhos.banco.exists():
                raise HTTPException(
                    503,
                    "Banco não encontrado. Rode: python -m robo_cnpj amostra "
                    "(dados fictícios) ou python -m robo_cnpj ingerir + transformar",
                )
            nova = duckdb.connect(str(cfg.caminhos.banco), read_only=True)
            try:
                nova.execute("SELECT 1 FROM leads LIMIT 1")
            except duckdb.CatalogException as erro:
                nova.close()
                raise HTTPException(
                    503, "Tabela `leads` ausente. Rode: python -m robo_cnpj transformar"
                ) from erro
            _base = nova
        return _base


def cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    """Dependência: um cursor isolado por requisição."""
    filho = _conexao_base().cursor()
    try:
        yield filho
    finally:
        filho.close()


Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursor)]


def _dicts(resultado) -> list[dict[str, Any]]:
    colunas = [d[0] for d in resultado.description]
    return [dict(zip(colunas, linha)) for linha in resultado.fetchall()]


@app.get("/api/resumo")
def resumo(con: Con) -> dict[str, Any]:
    linha = _dicts(con.execute("""
        SELECT
            count(*)                                              AS total,
            count_if(qtd_apontamentos > 0)                        AS com_apontamento,
            count_if(tem_divida_ativa_uniao)                      AS com_divida,
            COALESCE(sum(dau_valor_total), 0)                     AS valor_divida,
            count_if(tem_divida_ativa_mg)                         AS com_divida_mg,
            COALESCE(sum(dam_valor_total), 0)                     AS valor_divida_mg,
            count_if(situacao_irregular)                          AS irregulares,
            count_if(tem_sancao)                                  AS sancionadas,
            count_if(saiu_do_simples)                             AS ex_simples,
            count_if(regime_provavel LIKE 'Lucro Real%')          AS lucro_real,
            count_if(regime_provavel LIKE 'Lucro Presumido%')     AS lucro_presumido
        FROM leads
    """))[0]

    linha["por_municipio"] = _dicts(con.execute("""
        SELECT municipio, count(*) AS total,
               count_if(qtd_apontamentos > 0) AS com_apontamento
        FROM leads
        WHERE municipio IS NOT NULL
        GROUP BY municipio ORDER BY total DESC LIMIT 15
    """))

    linha["por_regime"] = _dicts(con.execute("""
        SELECT regime_provavel AS regime, count(*) AS total
        FROM leads GROUP BY regime_provavel ORDER BY total DESC
    """))
    return linha


@app.get("/api/leads")
def leads(
    con: Con,
    busca: str | None = Query(None, description="Razão social, fantasia ou CNPJ"),
    municipio: str | None = None,
    regime: str | None = Query(None, description="real | presumido"),
    com_divida: bool | None = None,
    com_divida_mg: bool | None = None,
    irregular: bool | None = None,
    com_sancao: bool | None = None,
    ex_simples: bool | None = None,
    score_minimo: int = 0,
    ordenar: str = Query("score", pattern="^(score|divida|divida_mg|capital|razao_social)$"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    filtros = ["score >= ?"]
    params: list[Any] = [score_minimo]

    if busca:
        curinga = f"%{busca}%"
        alternativas = ["razao_social ILIKE ?", "nome_fantasia ILIKE ?"]
        params += [curinga, curinga]

        # O usuário digita o CNPJ com ou sem pontuação. Só entra na cláusula se
        # houver dígitos — senão o padrão viraria '%%' e casaria com tudo,
        # devolvendo o universo inteiro para qualquer busca textual.
        digitos = "".join(c for c in busca if c.isdigit())
        if digitos:
            alternativas.append("cnpj LIKE ?")
            params.append(f"%{digitos}%")

        filtros.append("(" + " OR ".join(alternativas) + ")")

    if municipio:
        filtros.append("municipio = ?")
        params.append(municipio)

    if regime == "real":
        filtros.append("regime_provavel LIKE 'Lucro Real%'")
    elif regime == "presumido":
        filtros.append("regime_provavel LIKE 'Lucro Presumido%'")

    for valor, coluna in (
        (com_divida, "tem_divida_ativa_uniao"),
        (com_divida_mg, "tem_divida_ativa_mg"),
        (irregular, "situacao_irregular"),
        (com_sancao, "tem_sancao"),
        (ex_simples, "saiu_do_simples"),
    ):
        if valor is not None:
            filtros.append(f"{coluna} = ?")
            params.append(valor)

    where = " AND ".join(filtros)
    total = con.execute(f"SELECT count(*) FROM leads WHERE {where}", params).fetchone()[0]

    offset = (pagina - 1) * por_pagina
    itens = _dicts(con.execute(
        f"""SELECT * FROM leads WHERE {where}
            ORDER BY {ORDENACOES[ordenar]}
            LIMIT ? OFFSET ?""",
        [*params, por_pagina, offset],
    ))

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": max(1, -(-total // por_pagina)),
        "itens": itens,
    }


@app.get("/api/leads/{cnpj}")
def lead(cnpj: str, con: Con) -> dict[str, Any]:
    limpo = "".join(c for c in cnpj if c.isdigit())

    encontrado = _dicts(con.execute("SELECT * FROM leads WHERE cnpj = ?", [limpo]))
    if not encontrado:
        raise HTTPException(404, f"CNPJ {cnpj} não está no universo de leads.")

    detalhe = encontrado[0]
    basico = detalhe["cnpj_basico"]

    detalhe["inscricoes_divida"] = _dicts(con.execute("""
        SELECT categoria, situacao_inscricao, receita_principal, data_inscricao,
               indicador_ajuizado, valor_consolidado, unidade_responsavel
        FROM divida_ativa_uniao WHERE cnpj_basico = ?
        ORDER BY valor_consolidado DESC
    """, [basico]))

    detalhe["inscricoes_divida_mg"] = _dicts(con.execute("""
        SELECT numero_cda, data_inscricao, especie, saldo_cda, saldo_nucleo
        FROM divida_ativa_mg WHERE cnpj_basico = ?
        ORDER BY saldo_cda DESC
    """, [basico]))

    detalhe["sancoes"] = _dicts(con.execute("""
        SELECT cadastro, tipo_sancao, data_inicio, data_fim,
               orgao_sancionador, fundamentacao
        FROM sancoes WHERE cnpj_basico = ?
    """, [basico]))

    detalhe["socios"] = _dicts(con.execute("""
        SELECT s.nome_socio_razao_social AS nome,
               q.descricao AS qualificacao,
               s.data_entrada_sociedade,
               s.faixa_etaria
        FROM socios s
        LEFT JOIN qualificacoes q ON q.codigo = s.qualificacao_socio
        WHERE s.cnpj_basico = ?
    """, [basico]))

    return detalhe


@app.get("/api/municipios")
def municipios(con: Con) -> list[str]:
    return [r[0] for r in con.execute("""
        SELECT DISTINCT municipio FROM leads
        WHERE municipio IS NOT NULL ORDER BY municipio
    """).fetchall()]


@app.get("/")
def raiz() -> FileResponse:
    return FileResponse(cfg.caminhos.web / "index.html")


app.mount("/static", StaticFiles(directory=cfg.caminhos.web), name="static")
