"""Carrega config.yml e resolve os caminhos do projeto."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Caminhos:
    raiz: Path = RAIZ
    dados: Path = RAIZ / "data"
    brutos: Path = RAIZ / "data" / "brutos"
    banco: Path = RAIZ / "data" / "robo_cnpj.duckdb"
    sql: Path = RAIZ / "sql"
    exports: Path = RAIZ / "exports"
    web: Path = RAIZ / "web"

    def preparar(self) -> None:
        for p in (self.dados, self.brutos, self.exports):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    uf: str
    pgfn_ano: int
    pgfn_trimestre: int
    mg_divida_janela_dias: int
    receita_base_url: str
    receita_fatias: int
    situacoes_cadastrais: list[str]
    prefixo_natureza_juridica: str
    somente_matriz: bool
    somente_com_apontamento: bool
    score: dict[str, int]
    capital_lucro_real: int
    caminhos: Caminhos = field(default_factory=Caminhos)


@lru_cache(maxsize=1)
def carregar(caminho: Path | None = None) -> Config:
    arquivo = caminho or (RAIZ / "config.yml")
    with arquivo.open(encoding="utf-8") as fh:
        bruto = yaml.safe_load(fh)

    cfg = Config(
        uf=bruto["uf"].upper(),
        pgfn_ano=int(bruto["pgfn"]["ano"]),
        pgfn_trimestre=int(bruto["pgfn"]["trimestre"]),
        mg_divida_janela_dias=int(bruto["mg_divida"]["janela_dias"]),
        receita_base_url=bruto["receita"]["base_url"].rstrip("/"),
        receita_fatias=int(bruto["receita"]["fatias"]),
        situacoes_cadastrais=[str(s) for s in bruto["universo"]["situacoes_cadastrais"]],
        prefixo_natureza_juridica=str(bruto["universo"]["prefixo_natureza_juridica"]),
        somente_matriz=bool(bruto["universo"]["somente_matriz"]),
        somente_com_apontamento=bool(bruto["universo"]["somente_com_apontamento"]),
        score=dict(bruto["score"]),
        capital_lucro_real=int(bruto["regime"]["capital_lucro_real"]),
    )
    cfg.caminhos.preparar()
    return cfg
