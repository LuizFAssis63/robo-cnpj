"""Layout dos arquivos de Dados Abertos do CNPJ (Receita Federal).

Os CSVs vêm SEM cabeçalho, delimitados por ';', encoding LATIN-1 e com '"' como
quote. A ordem das colunas abaixo É o contrato: se a Receita alterar o layout, a
contagem de colunas muda e a carga falha alto (ver `db.carregar_csv`) em vez de
gravar dados deslocados silenciosamente.

Layout oficial: https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf
"""

from __future__ import annotations

from dataclasses import dataclass

DELIMITADOR = ";"
ENCODING = "latin-1"
QUOTE = '"'


@dataclass(frozen=True)
class Tabela:
    nome: str
    # Sufixo que a Receita usa no arquivo interno do ZIP (ex: .EMPRECSV)
    sufixo_arquivo: str
    # (coluna, tipo DuckDB) na ordem exata do CSV
    colunas: tuple[tuple[str, str], ...]
    # Prefixo dos ZIPs; None para tabelas de arquivo único
    prefixo_zip: str | None = None
    fatiada: bool = False

    @property
    def nomes_colunas(self) -> list[str]:
        return [c for c, _ in self.colunas]

    @property
    def tipos_duckdb(self) -> dict[str, str]:
        return {c: t for c, t in self.colunas}


EMPRESAS = Tabela(
    nome="empresas",
    prefixo_zip="Empresas",
    sufixo_arquivo=".EMPRECSV",
    fatiada=True,
    colunas=(
        ("cnpj_basico", "VARCHAR"),
        ("razao_social", "VARCHAR"),
        ("natureza_juridica", "VARCHAR"),
        ("qualificacao_responsavel", "VARCHAR"),
        # Vem com vírgula decimal no CSV; convertido em transform/.
        ("capital_social", "VARCHAR"),
        ("porte_empresa", "VARCHAR"),
        ("ente_federativo_responsavel", "VARCHAR"),
    ),
)

ESTABELECIMENTOS = Tabela(
    nome="estabelecimentos",
    prefixo_zip="Estabelecimentos",
    sufixo_arquivo=".ESTABELE",
    fatiada=True,
    colunas=(
        ("cnpj_basico", "VARCHAR"),
        ("cnpj_ordem", "VARCHAR"),
        ("cnpj_dv", "VARCHAR"),
        ("identificador_matriz_filial", "VARCHAR"),
        ("nome_fantasia", "VARCHAR"),
        ("situacao_cadastral", "VARCHAR"),
        ("data_situacao_cadastral", "VARCHAR"),
        ("motivo_situacao_cadastral", "VARCHAR"),
        ("nome_cidade_exterior", "VARCHAR"),
        ("pais", "VARCHAR"),
        ("data_inicio_atividade", "VARCHAR"),
        ("cnae_fiscal_principal", "VARCHAR"),
        ("cnae_fiscal_secundaria", "VARCHAR"),
        ("tipo_logradouro", "VARCHAR"),
        ("logradouro", "VARCHAR"),
        ("numero", "VARCHAR"),
        ("complemento", "VARCHAR"),
        ("bairro", "VARCHAR"),
        ("cep", "VARCHAR"),
        ("uf", "VARCHAR"),
        # Código de município da Receita, NÃO o código IBGE. Junta com a tabela `municipios`.
        ("municipio", "VARCHAR"),
        ("ddd_1", "VARCHAR"),
        ("telefone_1", "VARCHAR"),
        ("ddd_2", "VARCHAR"),
        ("telefone_2", "VARCHAR"),
        ("ddd_fax", "VARCHAR"),
        ("fax", "VARCHAR"),
        ("correio_eletronico", "VARCHAR"),
        ("situacao_especial", "VARCHAR"),
        ("data_situacao_especial", "VARCHAR"),
    ),
)

SOCIOS = Tabela(
    nome="socios",
    prefixo_zip="Socios",
    sufixo_arquivo=".SOCIOCSV",
    fatiada=True,
    colunas=(
        ("cnpj_basico", "VARCHAR"),
        ("identificador_socio", "VARCHAR"),
        ("nome_socio_razao_social", "VARCHAR"),
        ("cpf_cnpj_socio", "VARCHAR"),
        ("qualificacao_socio", "VARCHAR"),
        ("data_entrada_sociedade", "VARCHAR"),
        ("pais", "VARCHAR"),
        ("representante_legal", "VARCHAR"),
        ("nome_do_representante", "VARCHAR"),
        ("qualificacao_representante_legal", "VARCHAR"),
        ("faixa_etaria", "VARCHAR"),
    ),
)

SIMPLES = Tabela(
    nome="simples",
    prefixo_zip="Simples",
    sufixo_arquivo=".SIMPLES.CSV",
    colunas=(
        ("cnpj_basico", "VARCHAR"),
        ("opcao_pelo_simples", "VARCHAR"),
        ("data_opcao_simples", "VARCHAR"),
        ("data_exclusao_simples", "VARCHAR"),
        ("opcao_mei", "VARCHAR"),
        ("data_opcao_mei", "VARCHAR"),
        ("data_exclusao_mei", "VARCHAR"),
    ),
)


def _auxiliar(nome: str, prefixo_zip: str, sufixo: str) -> Tabela:
    """Tabelas de domínio: sempre (código, descrição)."""
    return Tabela(
        nome=nome,
        prefixo_zip=prefixo_zip,
        sufixo_arquivo=sufixo,
        colunas=(("codigo", "VARCHAR"), ("descricao", "VARCHAR")),
    )


CNAES = _auxiliar("cnaes", "Cnaes", ".CNAECSV")
MOTIVOS = _auxiliar("motivos", "Motivos", ".MOTICSV")
MUNICIPIOS = _auxiliar("municipios", "Municipios", ".MUNICCSV")
NATUREZAS = _auxiliar("naturezas", "Naturezas", ".NATJUCSV")
PAISES = _auxiliar("paises", "Paises", ".PAISCSV")
QUALIFICACOES = _auxiliar("qualificacoes", "Qualificacoes", ".QUALSCSV")

TABELAS_PRINCIPAIS = (EMPRESAS, ESTABELECIMENTOS, SOCIOS, SIMPLES)
TABELAS_AUXILIARES = (CNAES, MOTIVOS, MUNICIPIOS, NATUREZAS, PAISES, QUALIFICACOES)
TODAS_TABELAS = TABELAS_PRINCIPAIS + TABELAS_AUXILIARES


# --- Domínios codificados -------------------------------------------------

PORTE = {
    "00": "Não informado",
    "01": "Microempresa",
    "03": "Empresa de pequeno porte",
    "05": "Demais",
}

SITUACAO_CADASTRAL = {
    "01": "Nula",
    "02": "Ativa",
    "03": "Suspensa",
    "04": "Inapta",
    "08": "Baixada",
}

MATRIZ_FILIAL = {"1": "Matriz", "2": "Filial"}

# CNAEs cuja atividade obriga a apuração pelo Lucro Real (art. 14, Lei 9.718/98),
# independente do faturamento: instituições financeiras, seguradoras, factoring.
# Comparação por prefixo do CNAE de 7 dígitos.
CNAE_PREFIXOS_LUCRO_REAL_OBRIGATORIO = (
    "6410",  # Banco central
    "6421",  # Bancos comerciais
    "6422",  # Bancos múltiplos
    "6423",  # Caixas econômicas
    "6424",  # Crédito cooperativo
    "6431",  # Bancos de investimento
    "6432",  # Bancos de desenvolvimento
    "6433",  # Agências de fomento
    "6435",  # Crédito imobiliário
    "6436",  # Sociedades de crédito e financiamento
    "6437",  # Crédito e investimento
    "6438",  # Outras instituições de intermediação
    "6440",  # Arrendamento mercantil
    "6450",  # Holdings de instituições financeiras
    "6461",  # Holdings de instituições não-financeiras
    "6462",  # Holdings
    "6463",  # Fundos de investimento
    "6470",  # Fundos de investimento
    "6491",  # Sociedades de fomento mercantil - factoring
    "6492",  # Securitização de créditos
    "6493",  # Administração de consórcios
    "6499",  # Outras atividades de serviços financeiros
    "6511",  # Seguros de vida
    "6512",  # Seguros não-vida
    "6520",  # Resseguros
    "6530",  # Previdência complementar
    "6541",  # Capitalização
)
