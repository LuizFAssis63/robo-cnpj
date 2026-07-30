"""Gera CSVs sintéticos no formato exato das fontes oficiais.

Serve para exercitar todo o pipeline sem baixar os ~5GB da Receita — inclusive
offline. Os casos foram escolhidos para cobrir cada ramo das regras de negócio:
Simples ativo, MEI, ex-Simples, inapta, dívida ativa, sanção, CNAE de banco.
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path

from robo_cnpj import schemas

_EPOCH_EXCEL = datetime.date(1899, 12, 30)


def _serial(data: datetime.date) -> int:
    return (data - _EPOCH_EXCEL).days

# (cnpj_basico, razao_social, natureza, qualif, capital, porte, ente)
EMPRESAS = [
    ("10000001", "METALURGICA HORIZONTE LTDA", "2062", "49", "5000000,00", "05", ""),
    ("10000002", "PADARIA PAO DE MINAS LTDA", "2062", "49", "80000,00", "01", ""),
    ("10000003", "BANCO MINEIRO DE INVESTIMENTO SA", "2054", "10", "250000000,00", "05", ""),
    ("10000004", "TRANSPORTADORA SERRA AZUL LTDA", "2062", "49", "300000,00", "05", ""),
    ("10000005", "MERCEARIA DONA CLARA ME", "2135", "50", "15000,00", "01", ""),
    ("10000006", "CONSULTORIA VALE VERDE LTDA", "2062", "49", "120000,00", "03", ""),
    ("10000007", "CONSTRUTORA PAMPULHA SA", "2054", "10", "12000000,00", "05", ""),
    ("10000008", "ASSOCIACAO CULTURAL MINEIRA", "3999", "16", "0,00", "05", ""),
    ("10000009", "COMERCIO SAO PAULO DISTRIB LTDA", "2062", "49", "900000,00", "05", ""),
]

# (basico, ordem, dv, matriz_filial, fantasia, situacao, data_sit, motivo, uf, municipio, cnae)
ESTABELECIMENTOS = [
    ("10000001", "0001", "55", "1", "METALURGICA HORIZONTE", "02", "20100315", "00", "MG", "4123", "2512300"),
    ("10000002", "0001", "12", "1", "PAO DE MINAS", "02", "20150620", "00", "MG", "4123", "1091102"),
    ("10000003", "0001", "88", "1", "BANCO MINEIRO", "02", "20050101", "00", "MG", "4123", "6431000"),
    ("10000004", "0001", "31", "1", "SERRA AZUL LOG", "04", "20220810", "01", "MG", "5209", "4930202"),
    ("10000005", "0001", "77", "1", "", "02", "20180405", "00", "MG", "5209", "4712100"),
    ("10000006", "0001", "44", "1", "VALE VERDE", "02", "20190912", "00", "MG", "4557", "7020400"),
    ("10000007", "0001", "20", "1", "CONSTRUTORA PAMPULHA", "03", "20210505", "01", "MG", "4123", "4120400"),
    ("10000008", "0001", "63", "1", "ACM", "02", "20120101", "00", "MG", "4123", "9493600"),
    ("10000009", "0001", "09", "1", "SAO PAULO DISTRIB", "02", "20170303", "00", "SP", "7107", "4639701"),
    # Filial em MG — deve ser descartada por somente_matriz.
    ("10000001", "0002", "36", "2", "HORIZONTE FILIAL", "02", "20140101", "00", "MG", "5209", "2512300"),
]

# (basico, opcao_simples, data_opcao, data_exclusao, opcao_mei, data_opcao_mei, data_excl_mei)
SIMPLES = [
    ("10000002", "S", "20150620", "00000000", "N", "00000000", "00000000"),  # Simples ativo → fora
    ("10000005", "S", "20180405", "00000000", "S", "20180405", "00000000"),  # MEI ativo → fora
    ("10000006", "S", "20190912", "20240131", "N", "00000000", "00000000"),  # saiu → lead quente
    ("10000004", "S", "20200101", "20230630", "N", "00000000", "00000000"),  # saiu + inapta
]

SOCIOS = [
    ("10000001", "2", "JOSE ALVES PEREIRA", "***456789**", "49", "20100315", "", "", "", "", "5"),
    ("10000001", "2", "MARIA SOUZA LIMA", "***112233**", "22", "20120801", "", "", "", "", "4"),
    ("10000007", "2", "CARLOS EDUARDO ROCHA", "***998877**", "49", "20210505", "", "", "", "", "6"),
]

MUNICIPIOS = [("4123", "BELO HORIZONTE"), ("5209", "UBERLANDIA"),
              ("4557", "JUIZ DE FORA"), ("7107", "SAO PAULO")]

CNAES = [
    ("2512300", "Fabricação de estruturas metálicas"),
    ("1091102", "Fabricação de produtos de panificação"),
    ("6431000", "Bancos de investimento"),
    ("4930202", "Transporte rodoviário de carga"),
    ("4712100", "Comércio varejista de mercadorias em geral"),
    ("7020400", "Atividades de consultoria em gestão empresarial"),
    ("4120400", "Construção de edifícios"),
    ("9493600", "Atividades de organizações associativas"),
    ("4639701", "Comércio atacadista de produtos alimentícios"),
]

NATUREZAS = [("2062", "Sociedade Empresária Limitada"),
             ("2054", "Sociedade Anônima Fechada"),
             ("2135", "Empresário Individual"),
             ("3999", "Associação Privada")]

MOTIVOS = [("00", ""), ("01", "Extinção por encerramento liquidação voluntária")]

PAISES = [("105", "BRASIL")]

QUALIFICACOES = [("49", "Sócio-Administrador"), ("22", "Sócio"),
                 ("10", "Diretor"), ("50", "Empresário"), ("16", "Presidente")]

# Dívida ativa: CSV COM cabeçalho, valor no formato brasileiro.
DAU_CABECALHO = [
    "CPF_CNPJ", "TIPO_PESSOA", "TIPO_DEVEDOR", "NOME_DEVEDOR",
    "UF_UNIDADE_RESPONSAVEL", "UNIDADE_RESPONSAVEL", "NUMERO_INSCRICAO",
    "TIPO_SITUACAO_INSCRICAO", "SITUACAO_INSCRICAO", "RECEITA_PRINCIPAL",
    "DATA_INSCRICAO", "INDICADOR_AJUIZADO", "VALOR_CONSOLIDADO",
]
DAU_LINHAS = [
    ["10000001000155", "PJ", "PRINCIPAL", "METALURGICA HORIZONTE LTDA", "MG",
     "PRFN 6A REGIAO", "80.1.24.000123-45", "1", "Em cobrança", "IRPJ",
     "2024-03-15", "Sim", "1.250.480,75"],
    ["10000001000155", "PJ", "PRINCIPAL", "METALURGICA HORIZONTE LTDA", "MG",
     "PRFN 6A REGIAO", "80.1.24.000124-46", "1", "Em cobrança", "COFINS",
     "2024-06-20", "Não", "348.900,10"],
    ["10000004000131", "PJ", "PRINCIPAL", "TRANSPORTADORA SERRA AZUL LTDA", "MG",
     "PRFN 6A REGIAO", "80.6.23.000987-11", "1", "Ajuizada", "CSLL",
     "2023-11-02", "Sim", "97.320,00"],
    # Outro estado — deve ser filtrado.
    ["10000009000109", "PJ", "PRINCIPAL", "COMERCIO SAO PAULO LTDA", "SP",
     "PRFN 3A REGIAO", "80.3.22.000111-00", "1", "Em cobrança", "IRPJ",
     "2022-01-10", "Não", "55.000,00"],
]

SANCOES_CABECALHO = [
    "CPF OU CNPJ DO SANCIONADO", "NOME INFORMADO PELO ÓRGÃO SANCIONADOR",
    "TIPO DE SANÇÃO", "DATA INÍCIO SANÇÃO", "DATA FINAL SANÇÃO",
    "ÓRGÃO SANCIONADOR", "UF DO SANCIONADO", "FUNDAMENTAÇÃO LEGAL",
]
SANCOES_LINHAS = [
    ["10000007000120", "CONSTRUTORA PAMPULHA SA", "Impedimento",
     "01/02/2025", "01/02/2027", "MINISTERIO DA INFRAESTRUTURA", "MG",
     "Art. 87, inciso III, Lei 8.666/93"],
]


def divida_mg_linhas(hoje: datetime.date | None = None) -> list[list]:
    """Linhas sintéticas no formato bruto do .xlsb da SEF-MG (já sem cabeçalho).

    Datas relativas a `hoje` (ou datetime.date.today() se omitido) para que o
    corte de 1 ano continue válido não importa quando o teste rodar. `pyxlsb`
    entrega datas de Excel como float — reproduzimos isso aqui para o teste
    exercitar exatamente o mesmo formato que o ingestor recebe na vida real.
    """
    hoje = hoje or datetime.date.today()
    recente = hoje - datetime.timedelta(days=30)
    antiga = hoje - datetime.timedelta(days=800)  # fora da janela padrão de 1 ano

    return [
        # Consultoria Vale Verde: só tinha "saiu do Simples" — ganha 2º apontamento.
        ["10.000006/0001-44", "CONSULTORIA VALE VERDE LTDA", "0100000099001",
         float(_serial(recente)), "ICMS", 45230.80, 45230.80],
        # Metalúrgica Horizonte: dívida ANTIGA — deve ser descartada pelo corte de 1 ano.
        ["10.000001/0001-55", "METALURGICA HORIZONTE LTDA", "0100000012345",
         float(_serial(antiga)), "ICMS", 999999.99, 999999.99],
        # CNPJ que não existe no universo (nenhuma empresa da amostra usa esse
        # básico) — precisa carregar sem erro e simplesmente não virar lead.
        ["99.999999/0001-00", "EMPRESA FORA DO UNIVERSO LTDA", "0100000055555",
         float(_serial(recente)), "ICMS", 1000.00, 1000.00],
    ]


def _escrever(caminho: Path, linhas, cabecalho=None) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding=schemas.ENCODING, newline="") as fh:
        w = csv.writer(fh, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL,
                       lineterminator="\n")
        if cabecalho:
            w.writerow(cabecalho)
        w.writerows(linhas)
    return caminho


def _preencher(linhas: list[tuple], largura: int, posicoes: dict[int, int]) -> list[list[str]]:
    """Expande tuplas curtas para a largura real do layout.

    `posicoes` mapeia índice-na-tupla → índice-na-linha-final; o resto vai vazio.
    """
    saida = []
    for linha in linhas:
        completa = [""] * largura
        for origem, destino in posicoes.items():
            completa[destino] = linha[origem]
        saida.append(completa)
    return saida


def gerar(destino: Path) -> dict[str, Path]:
    """Escreve todos os CSVs e devolve {nome_tabela: caminho}."""
    arquivos: dict[str, Path] = {}

    arquivos["empresas"] = _escrever(destino / "AMOSTRA.EMPRECSV", EMPRESAS)

    # Estabelecimentos tem 30 colunas; a fixture declara 11 posições relevantes.
    est = _preencher(
        ESTABELECIMENTOS,
        largura=len(schemas.ESTABELECIMENTOS.colunas),
        posicoes={0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7,
                  8: 19, 9: 20, 10: 11},
    )
    # data_inicio_atividade (idx 10) e telefone/email para ficar realista.
    for i, linha in enumerate(est):
        linha[10] = ESTABELECIMENTOS[i][6]
        linha[18] = "30110000"
        linha[21] = "31"
        linha[22] = f"3300{1000 + i}"
        linha[27] = f"contato{i}@exemplo.com.br"
    arquivos["estabelecimentos"] = _escrever(destino / "AMOSTRA.ESTABELE", est)

    arquivos["simples"] = _escrever(destino / "AMOSTRA.SIMPLES.CSV", SIMPLES)
    arquivos["socios"] = _escrever(destino / "AMOSTRA.SOCIOCSV", SOCIOS)
    arquivos["municipios"] = _escrever(destino / "AMOSTRA.MUNICCSV", MUNICIPIOS)
    arquivos["cnaes"] = _escrever(destino / "AMOSTRA.CNAECSV", CNAES)
    arquivos["naturezas"] = _escrever(destino / "AMOSTRA.NATJUCSV", NATUREZAS)
    arquivos["motivos"] = _escrever(destino / "AMOSTRA.MOTICSV", MOTIVOS)
    arquivos["paises"] = _escrever(destino / "AMOSTRA.PAISCSV", PAISES)
    arquivos["qualificacoes"] = _escrever(destino / "AMOSTRA.QUALSCSV", QUALIFICACOES)

    arquivos["dau"] = _escrever(destino / "amostra_dau.csv", DAU_LINHAS, DAU_CABECALHO)
    arquivos["sancoes"] = _escrever(destino / "amostra_ceis.csv", SANCOES_LINHAS,
                                    SANCOES_CABECALHO)
    return arquivos
