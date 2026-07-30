# Robô CNPJ — prospecção contábil em MG

Encontra empresas de Minas Gerais **fora do Simples Nacional e do MEI** — o
universo Lucro Real / Lucro Presumido — e cruza cada CNPJ com fontes públicas
para levantar apontamentos que a contabilidade usa como gancho comercial:
dívida ativa da União, dívida ativa estadual (MG), situação cadastral
irregular, sanções e exclusão do Simples. Por padrão, só entra na lista final
quem tem pelo menos um desses apontamentos — CNPJ limpo não interessa para
prospecção.

Só fontes abertas oficiais. Nenhum captcha contornado, nenhum scraping de área
autenticada.

---

## Leia isto antes de tudo: duas limitações que definem o projeto

**1. A base pública da Receita não informa o regime tributário.**

Não existe campo "Lucro Real" ou "Lucro Presumido" nos Dados Abertos do CNPJ. O
que existe é o arquivo do Simples, que diz com certeza quem optou pelo Simples e
pelo MEI. Então o robô trabalha por exclusão:

```
todas as empresas de MG
  − Simples ativo
  − MEI ativo
  − naturezas não empresariais (órgãos públicos, associações, pessoas físicas)
  = universo Lucro Real ou Presumido
```

A distinção entre os dois é **inferida**, e a coluna `regime_confianca` diz o
quanto confiar:

| Sinal | Regime | Confiança |
|---|---|---|
| CNAE de banco, seguradora ou factoring | Lucro Real (obrigatório por lei) | **Alta** |
| Porte "Demais" + capital ≥ R$ 1M | Lucro Real provável | Média |
| Porte "Demais" + capital menor | Lucro Presumido provável | Média |
| ME/EPP fora do Simples | Lucro Presumido provável | Baixa |

Só a primeira linha é fato jurídico (art. 14 da Lei 9.718/98). O resto é
heurística — trate como priorização de lista, não como enquadramento.

**2. Fontes abertas não emitem CND/CDT.**

O robô não tira certidão. Ele entrega um **prognóstico** a partir de fatos
públicos, em duas colunas — uma por jurisdição, porque uma não afeta a outra:

- `cnd_federal_prognostico`: CNPJ com inscrição ativa em dívida ativa da
  **União** não tira CND federal negativa. Consequência direta e segura.
- `cdt_estadual_mg_prognostico`: CNPJ com inscrição ativa em dívida ativa
  **estadual (MG)** não tira CDT-MG negativa. Mesma lógica, outro órgão.

Mas a **ausência** de apontamento em qualquer uma delas **não garante**
certidão negativa. Pode haver débito ainda não inscrito em dívida ativa, débito
municipal, FGTS ou débito trabalhista — nada disso aparece nas fontes usadas, e
a dívida estadual só cobre os últimos 12 meses (ver [Fontes de dados](#fontes-de-dados)).

Para certidão de fato (CND federal, CDT-MG, CRF do FGTS, CNDT) é preciso uma API
oficial ou paga. Ver [Próximos passos](#próximos-passos).

---

## Status desta carga (29/07/2026)

Números de uma execução real contra MG, para dar noção de escala — não é um
resultado fixo do projeto, cada carga nova gera números diferentes:

| Fonte | Registros carregados (MG) |
|---|---|
| Dívida ativa da União — PGFN (geral + previdenciária + FGTS) | 3.100.336 |
| Sanções — CEIS/CNEP/CEPIM | 15.844 |
| Dívida ativa estadual — SEF/AGE-MG (últimos 12 meses) | 42.257 |
| Base de empresas — Receita Federal | ⏳ pendente — `dadosabertos.rfb.gov.br` fora do ar nesta execução |

Sem a base de empresas, `universo`/`apontamentos`/`leads` não podem ser
recalculados com dados reais — são as tabelas que cruzam CNPJ com os
apontamentos acima. O dashboard, quando aberto agora, mostra a última leva
processada (a amostra sintética ou uma carga anterior), não este estado. Assim
que a Receita voltar, `ingerir --fonte receita && transformar && exportar`
fecha o ciclo com esses ~3,1 milhões de inscrições já prontas.

---

## Fontes de dados

| Fonte | O que traz | Atualização | Cobertura carregada |
|---|---|---|---|
| [Dados Abertos CNPJ — Receita Federal](https://dadosabertos.rfb.gov.br/CNPJ/) | Empresas, estabelecimentos, sócios, Simples/MEI | Mensal | Tudo |
| [Dívida Ativa da União — PGFN](https://www.gov.br/pgfn/pt-br/assuntos/divida-ativa-da-uniao/transparencia-fiscal-1/dados-abertos) | Inscrições, valor, ajuizamento (geral, previdenciária, FGTS) | Trimestral | Tudo |
| [CEIS / CNEP / CEPIM — Portal da Transparência](https://portaldatransparencia.gov.br/sancoes) | Empresas inidôneas, punidas, entidades impedidas | Diária | Tudo |
| [Dívida Ativa Estadual — SEF/AGE-MG](https://www.fazenda.mg.gov.br/transparencia/divida-ativa) | Inscrições em CDA por CNPJ, ICMS e outros tributos estaduais | Não informada pela SEF | **Últimos 12 meses** (`mg_divida.janela_dias`) |

A dívida estadual vem de um único arquivo (`.xlsb`, ~300 mil inscrições desde os
anos 2000) publicado sob a Resolução Conjunta SEF/AGE nº 5.625/2022 — sem API,
sem paginação, sem separação por competência. Carregar tudo despejaria dívida de
20+ anos atrás no banco sem ganho de sinal comercial, por isso o corte padrão de
1 ano (ajustável em `config.yml`).

**Nota sobre o servidor da Receita:** `dadosabertos.rfb.gov.br` é conhecido por
ficar fora do ar por períodos longos sob demanda alta. O ingestor tenta de novo
automaticamente com espera crescente (30s até 5min, por até ~1h50 antes de
desistir) — ver [Robustez de rede](#robustez-de-rede).

---

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
```

No Linux/macOS: `source .venv/bin/activate` e `export PYTHONPATH=$PWD/src`.

## Conhecendo a interface em 30 segundos

Antes de baixar nada, popule o banco com dados fictícios:

```powershell
python -m robo_cnpj amostra
python -m robo_cnpj servir      # http://127.0.0.1:8000
```

> **Cuidado:** `amostra` faz `CREATE OR REPLACE` nas tabelas de cada fonte.
> Se você já tiver dados reais carregados, rodar `amostra` de novo apaga o que
> foi ingerido de verdade nas fontes que ela recria (Receita, PGFN, dívida
> estadual, Transparência) — não a tabela `leads` isoladamente, as fontes
> inteiras. Recarregar depois é rápido (os ZIPs/arquivos ficam em cache em
> `data/brutos/`, então `ingerir` não baixa de novo, só reprocessa), mas é fácil
> esquecer. Use `amostra` só em um banco que você não vá usar para dados reais,
> ou recarregue as fontes atingidas logo em seguida.

## Rodando com dados reais

```powershell
# 1. Baixa e carrega tudo. Demora: ~5GB de download, 30-90 min conforme a conexão
#    (mais, se o servidor da Receita estiver instável — ver nota acima).
python -m robo_cnpj ingerir

# Ou uma fonte por vez:
python -m robo_cnpj ingerir --fonte receita
python -m robo_cnpj ingerir --fonte pgfn
python -m robo_cnpj ingerir --fonte mg_divida
python -m robo_cnpj ingerir --fonte transparencia

# 2. Monta universo, apontamentos, regime e score.
python -m robo_cnpj transformar

# 3. Planilha para a contabilidade.
python -m robo_cnpj exportar
python -m robo_cnpj exportar --min-apontamentos 1 -n 500   # só os leads mais quentes

# 4. Dashboard.
python -m robo_cnpj servir
```

`python -m robo_cnpj tudo` roda os passos 1-3 em sequência.

**Dica para desenvolver:** em `config.yml`, baixe `receita.fatias` de `10` para
`1`. A Receita divide Empresas/Estabelecimentos/Sócios em 10 arquivos; um deles
já dá dezenas de milhares de empresas mineiras para trabalhar, com um décimo do
download.

## Verificando que tudo funciona

```powershell
python tests\test_pipeline.py    # offline, não precisa de banco
python tests\test_api.py         # precisa de banco: rode `amostra` antes
```

`test_pipeline.py` gera fixtures sintéticas no formato exato das fontes
oficiais (incluindo uma amostra do `.xlsb` da dívida estadual, sem precisar
fabricar um arquivo binário de verdade), roda o pipeline duas vezes — com e
sem o filtro de apontamento — e confere quase 50 regras de negócio: exclusão
do Simples, inferência de regime, conversão de valores no formato brasileiro,
corte de 1 ano na dívida estadual, cálculo de score, detecção de layout
divergente. Roda offline em segundos.

`test_api.py` exercita os endpoints e, principalmente, **dispara 60 requisições
concorrentes**. Esse teste existe porque a primeira versão compartilhava uma
única conexão DuckDB entre requisições: como os endpoints são síncronos e rodam
em threadpool, duas chamadas simultâneas embaralhavam os resultados e a página
quebrava com erro 500 ao carregar — ela pede `/api/resumo` e `/api/municipios`
em paralelo. A correção foi dar um cursor por requisição.

---

## Como o score funciona

Cada lead recebe 0-100 somando os pesos de `config.yml` (o `least(100, …)` no
SQL trava o teto — os pesos somam mais que 100 de propósito, para que acumular
apontamentos sempre empurre para o topo sem precisar reequilibrar a mão):

| Apontamento | Peso padrão | Por que importa |
|---|---|---|
| Dívida ativa da União | 30 | Impede CND federal; empresa precisa de regularização |
| Dívida ativa estadual (MG) | 25 | Impede CDT-MG; ICMS é o tributo mais sensível para o cliente mineiro |
| Situação cadastral irregular | 25 | Inapta ou suspensa — problema fiscal em curso |
| Excluída do Simples | 20 | Precisa reenquadrar o regime **agora**; lead mais quente |
| Sanção (CEIS/CNEP/CEPIM) | 15 | Impedimento de licitar; risco reputacional |
| Porte "Demais" | 10 | Faturamento maior, honorário maior |

Ajuste os pesos conforme o que a contabilidade valoriza — se o foco é ganhar
cliente novo em vez de resolver passivo, suba `peso_saiu_do_simples` e desça
`peso_divida_ativa_uniao`.

## Estrutura

```
config.yml                    UF, competência da PGFN, janela da dívida MG, pesos do score
sql/
  01_universo.sql             filtra MG e exclui Simples/MEI
  02_apontamentos.sql         dívida ativa (União + MG), situação, sanções, prognósticos
  03_leads.sql                regime inferido + score + filtro de apontamento → tabela `leads`
src/robo_cnpj/
  schemas.py                  layout oficial dos CSVs da Receita
  db.py                       DuckDB, validação de layout, erro de banco ocupado
  ingest/http.py              download com retomada, retry/backoff, cache de zip corrompido
  ingest/receita.py           base CNPJ
  ingest/pgfn.py              dívida ativa da União
  ingest/mg_divida.py         dívida ativa estadual (SEF/AGE-MG)
  ingest/transparencia.py     CEIS/CNEP/CEPIM
  transform.py                orquestra os SQLs
  export.py                   planilha Excel
  api.py                      API do dashboard
  cli.py                      linha de comando
web/                          dashboard (HTML/CSS/JS, sem build step)
tests/
  amostra.py                  fixtures sintéticas no formato das fontes oficiais
  test_pipeline.py            pipeline ponta a ponta, offline
  test_api.py                 endpoints + concorrência
data/                         banco e brutos (fora do git)
exports/                      planilhas geradas (fora do git)
```

### Por que DuckDB

A base da Receita tem dezenas de GB em CSV. DuckDB lê CSV direto, roda os joins
em disco sem carregar tudo na memória e não precisa de servidor — o banco é um
arquivo em `data/`. Postgres daria o mesmo resultado com muito mais cerimônia.

### A validação de layout

`db.conferir_largura` conta as colunas de cada CSV antes de carregar e aborta se
divergir do declarado em `schemas.py`. Sem isso, uma coluna nova no meio do
arquivo faria a carga entrar deslocada — razão social caindo no campo de natureza
jurídica — de forma silenciosa. A Receita já mudou esse layout antes; quando
mudar de novo, o robô falha alto e aponta o PDF oficial.

### Robustez de rede

`dadosabertos.rfb.gov.br` fica fora do ar com frequência — não é bug do robô,
é o histórico real do servidor. `ingest/http.py` trata isso em três frentes:

- **Retry com backoff exponencial** (`repetir_com_backoff`): 30s, 60s, 120s,
  240s, depois trava em 5min — até 25 tentativas, ~1h50 de paciência total
  antes de desistir com um erro claro (`ConexaoIndisponivelError`). Vale para
  qualquer chamada de rede do projeto, não só a Receita.
- **Cache de ZIP corrompido** (`_zip_valido`): se uma execução anterior morreu
  no meio de um download, o arquivo pode ficar corrompido; a próxima execução
  detecta isso com `zipfile.is_zipfile` e baixa de novo em vez de confiar
  cegamente no cache.
- **Cache da competência** (`receita.py`): a pasta do mês corrente (ex.
  `2026-07`) é descoberta uma vez e salva em
  `data/brutos/receita/_competencia.txt` — não bate no índice do site de novo
  a cada execução.

Isso significa que `python -m robo_cnpj ingerir --fonte receita` pode ficar
"parado" por minutos imprimindo `tentativa N/25` — é o comportamento esperado
quando o servidor está fora do ar, não um travamento. Se o processo já baixou
parte dos arquivos antes de cair, uma nova execução retoma de onde parou (não
rebaixa do zero).

---

## Próximos passos

**Certidões de verdade.** A camada mais valiosa que falta. CND federal, CDT-MG,
CRF do FGTS e CNDT existem via API paga (Infosimples, Serpro e similares), que
resolvem o captcha legalmente. O caminho: um módulo `enrich/certidoes.py`
consultando **só os leads de score alto** — são centenas de milhares de empresas
no universo, então consultar tudo é caro e desnecessário.

**Parcelamentos estaduais (PTA/Res. 5625).** A mesma resolução que publica a
dívida ativa de MG também publica quem já está em parcelamento ou acordo
(`Resolucao_5625_22_PARCELAMENTO_PJ.xlsb`, ~8,8 mil registros). Cruzar com
`divida_ativa_mg` separaria quem está regularizando (lead mais frio) de quem
simplesmente não tocou no assunto (lead mais quente) — hoje o robô não usa
esse arquivo.

**Histórico.** Hoje cada execução sobrescreve o banco. Guardar snapshots por
competência permitiria detectar *mudança* — empresa que entrou em dívida ativa no
último trimestre é um lead muito mais quente que uma inadimplente antiga. Vale
tanto para a dívida federal quanto para a estadual.

**Exclusões do Simples.** A Receita publica listas de exclusão por débito.
Cruzar com o universo separaria quem saiu por crescimento (bom cliente) de quem
saiu por inadimplência (cliente de regularização).

**Carga do `divida_ativa_mg` em paralelo.** O arquivo da SEF-MG tem ~300 mil
linhas e é lido linha a linha em Python puro (`pyxlsb` não tem alternativa
vetorizada) — a carga leva alguns minutos. Não é gargalo hoje, mas se a SEF
aumentar o histórico publicado, vale paralelizar ou trocar por leitura em lote.

---

## Nota legal

Todos os dados usados são públicos e de acesso livre, publicados sob licença
aberta pela Receita Federal, PGFN, CGU e SEF/AGE-MG. Ainda assim, os dados
incluem informação sobre pessoas jurídicas identificadas: use para prospecção
legítima, não redistribua as bases brutas e trate os apontamentos como indício
a confirmar na fonte oficial antes de qualquer afirmação ao cliente.
