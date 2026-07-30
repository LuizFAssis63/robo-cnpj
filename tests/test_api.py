"""Testa a API, incluindo acesso concorrente.

O teste de concorrência não é zelo excessivo: a versão inicial compartilhava uma
única conexão DuckDB entre requisições, e como os endpoints são `def` síncronos
rodando em threadpool, duas chamadas simultâneas embaralhavam os resultados —
/api/resumo recebia as linhas de /api/municipios e estourava. A página dispara
exatamente essas duas chamadas em paralelo no carregamento.

    python tests/test_api.py

Requer um banco populado (python -m robo_cnpj amostra).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from robo_cnpj import config  # noqa: E402
from robo_cnpj.api import app  # noqa: E402

falhas: list[str] = []


def conferir(condicao: bool, descricao: str, detalhe: str = "") -> None:
    if condicao:
        print(f"  [ok]    {descricao}")
    else:
        print(f"  [FALHA] {descricao}" + (f" — {detalhe}" if detalhe else ""))
        falhas.append(descricao)


def main() -> int:
    cfg = config.carregar()
    if not cfg.caminhos.banco.exists():
        print("Banco não encontrado. Rode primeiro: python -m robo_cnpj amostra")
        return 1

    cliente = TestClient(app)

    print("1. Endpoints básicos")
    r = cliente.get("/api/resumo")
    conferir(r.status_code == 200, "/api/resumo responde 200", str(r.status_code))
    resumo = r.json()
    for chave in ("total", "com_divida", "valor_divida", "com_divida_mg",
                  "valor_divida_mg", "por_municipio", "por_regime"):
        conferir(chave in resumo, f"/api/resumo traz '{chave}'")

    r = cliente.get("/api/municipios")
    conferir(r.status_code == 200 and isinstance(r.json(), list),
             "/api/municipios devolve lista", str(r.status_code))
    conferir(all(isinstance(m, str) for m in r.json()),
             "/api/municipios só contém strings")

    r = cliente.get("/api/leads")
    conferir(r.status_code == 200, "/api/leads responde 200")
    dados = r.json()
    conferir(dados["total"] == resumo["total"],
             "total de /api/leads casa com /api/resumo",
             f"{dados['total']} vs {resumo['total']}")

    print("\n2. Concorrência (a corrida que derrubava a página)")
    # 60 requisições paralelas alternando os endpoints que a página chama junto.
    caminhos = ["/api/resumo", "/api/municipios", "/api/leads",
                "/api/leads?ordenar=divida", "/api/leads?com_divida=true"]
    alvos = [caminhos[i % len(caminhos)] for i in range(60)]

    with ThreadPoolExecutor(max_workers=12) as pool:
        respostas = list(pool.map(lambda c: (c, cliente.get(c)), alvos))

    ruins = [(c, r.status_code) for c, r in respostas if r.status_code != 200]
    conferir(not ruins, "60 requisições concorrentes, todas 200",
             f"falharam: {ruins[:5]}")

    # Sob corrida, /api/resumo devolvia linhas de outra query — o total variava.
    totais = {r.json()["total"] for c, r in respostas
              if c == "/api/resumo" and r.status_code == 200}
    conferir(len(totais) == 1, "/api/resumo devolve o mesmo total sob concorrência",
             f"totais vistos: {totais}")

    municipios_vistos = {tuple(r.json()) for c, r in respostas
                         if c == "/api/municipios" and r.status_code == 200}
    conferir(len(municipios_vistos) == 1,
             "/api/municipios estável sob concorrência",
             f"{len(municipios_vistos)} respostas distintas")

    print("\n3. Busca e filtros")
    if dados["itens"]:
        primeiro = dados["itens"][0]

        r = cliente.get(f"/api/leads/{primeiro['cnpj']}")
        conferir(r.status_code == 200, "detalhe por CNPJ responde 200")
        detalhe = r.json()
        for chave in ("inscricoes_divida", "inscricoes_divida_mg", "sancoes", "socios"):
            conferir(chave in detalhe, f"detalhe traz '{chave}'")

        # Busca textual não deve casar CNPJ: sem dígitos, o padrão virava '%%'
        # e devolvia o universo inteiro.
        r = cliente.get("/api/leads", params={"busca": "zzznaoexistezzz"})
        conferir(r.json()["total"] == 0,
                 "busca textual sem resultado devolve 0",
                 str(r.json()["total"]))

        palavra = primeiro["razao_social"].split()[0]
        r = cliente.get("/api/leads", params={"busca": palavra})
        achados = r.json()["total"]
        conferir(0 < achados < dados["total"] or dados["total"] == 1,
                 f"busca por '{palavra}' restringe o resultado",
                 f"{achados} de {dados['total']}")

        r = cliente.get("/api/leads", params={"busca": primeiro["cnpj_formatado"]})
        conferir(r.json()["total"] >= 1, "busca por CNPJ formatado encontra o lead")

    r = cliente.get("/api/leads/00000000000000")
    conferir(r.status_code == 404, "CNPJ fora do universo devolve 404", str(r.status_code))

    r = cliente.get("/api/leads", params={"ordenar": "invalido"})
    conferir(r.status_code == 422, "ordenação inválida é rejeitada", str(r.status_code))

    print("\n3b. Dívida ativa estadual (MG)")
    r = cliente.get("/api/leads", params={"ordenar": "divida_mg"})
    conferir(r.status_code == 200, "ordenar=divida_mg é aceito", str(r.status_code))

    r = cliente.get("/api/leads", params={"com_divida_mg": "true"})
    conferir(r.status_code == 200, "filtro com_divida_mg responde 200", str(r.status_code))
    filtrados_mg = r.json()
    conferir(
        filtrados_mg["total"] == resumo["com_divida_mg"],
        "contagem do filtro com_divida_mg bate com /api/resumo",
        f"{filtrados_mg['total']} vs {resumo['com_divida_mg']}",
    )
    conferir(
        all(item["tem_divida_ativa_mg"] for item in filtrados_mg["itens"]),
        "todo item retornado por com_divida_mg=true realmente tem a flag",
    )

    print("\n4. Paginação")
    r = cliente.get("/api/leads", params={"por_pagina": 2, "pagina": 1})
    p1 = r.json()
    conferir(len(p1["itens"]) <= 2, "por_pagina limita os itens")
    if p1["paginas"] > 1:
        r2 = cliente.get("/api/leads", params={"por_pagina": 2, "pagina": 2})
        cnpjs1 = {i["cnpj"] for i in p1["itens"]}
        cnpjs2 = {i["cnpj"] for i in r2.json()["itens"]}
        conferir(not (cnpjs1 & cnpjs2), "páginas não repetem leads")

    print("\n5. Estáticos")
    for caminho in ("/", "/static/styles.css", "/static/app.js"):
        r = cliente.get(caminho)
        conferir(r.status_code == 200, f"{caminho} responde 200", str(r.status_code))

    print()
    if falhas:
        print(f"{len(falhas)} verificação(ões) falharam:")
        for f in falhas:
            print(f"  - {f}")
        return 1

    print("Todas as verificações passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
