-- Apontamentos: os sinais que interessam à contabilidade.
--
-- IMPORTANTE sobre certidões: fontes abertas não emitem certidão. O que este
-- SQL entrega é um PROGNÓSTICO baseado em fatos públicos (inscrição em dívida
-- ativa, situação cadastral irregular). Um CNPJ com inscrição ativa na DAU não
-- tira CND federal negativa, e inscrição na dívida estadual não tira CDT-MG —
-- isso é consequência direta e segura. Mas a ausência de apontamento aqui NÃO
-- garante certidão negativa: pode haver débito não inscrito em dívida ativa,
-- débito municipal, FGTS ou trabalhista. Nomeamos as colunas com "_prognostico"
-- para que ninguém confunda com certidão de verdade.

CREATE OR REPLACE TABLE apontamentos AS
WITH dau AS (
    SELECT
        cnpj_basico,
        count(*)                       AS dau_qtd_inscricoes,
        sum(valor_consolidado)         AS dau_valor_total,
        count(DISTINCT categoria)      AS dau_qtd_categorias,
        max(CASE WHEN upper(COALESCE(indicador_ajuizado, '')) LIKE 'S%'
                 THEN 1 ELSE 0 END)    AS dau_ajuizado,
        string_agg(DISTINCT categoria, ' | ') AS dau_categorias
    FROM divida_ativa_uniao
    GROUP BY cnpj_basico
),
dam AS (
    -- Dívida ativa ESTADUAL de MG (ICMS e outros tributos do estado) — fonte
    -- SEF/AGE-MG, resolução conjunta 5625/22. Independente da dívida federal.
    SELECT
        cnpj_basico,
        count(*)                       AS dam_qtd_inscricoes,
        sum(saldo_cda)                 AS dam_valor_total,
        string_agg(DISTINCT especie, ' | ') AS dam_especies
    FROM divida_ativa_mg
    GROUP BY cnpj_basico
),
sanc AS (
    SELECT
        cnpj_basico,
        count(*)                              AS sancao_qtd,
        string_agg(DISTINCT cadastro, ' | ')   AS sancao_cadastros,
        string_agg(DISTINCT tipo_sancao, ' | ') AS sancao_tipos
    FROM sancoes
    GROUP BY cnpj_basico
)
SELECT
    u.cnpj_basico,
    u.cnpj,

    -- Dívida ativa da União
    COALESCE(d.dau_qtd_inscricoes, 0)          AS dau_qtd_inscricoes,
    COALESCE(d.dau_valor_total, 0.0)           AS dau_valor_total,
    COALESCE(d.dau_ajuizado, 0) = 1            AS dau_ajuizado,
    d.dau_categorias,
    d.dau_qtd_inscricoes IS NOT NULL           AS tem_divida_ativa_uniao,

    -- Dívida ativa estadual (MG)
    COALESCE(dm.dam_qtd_inscricoes, 0)         AS dam_qtd_inscricoes,
    COALESCE(dm.dam_valor_total, 0.0)          AS dam_valor_total,
    dm.dam_especies,
    dm.dam_qtd_inscricoes IS NOT NULL          AS tem_divida_ativa_mg,

    -- Situação cadastral
    u.situacao_cadastral NOT IN ('02')         AS situacao_irregular,
    u.situacao_cadastral = '04'                AS inapta,
    u.situacao_cadastral = '03'                AS suspensa,

    -- Sanções
    COALESCE(s.sancao_qtd, 0)                  AS sancao_qtd,
    s.sancao_cadastros,
    s.sancao_tipos,
    s.sancao_qtd IS NOT NULL                   AS tem_sancao,

    -- Movimentação de regime
    COALESCE(u.saiu_do_simples, FALSE)         AS saiu_do_simples,
    u.data_exclusao_simples,

    -- Prognóstico de CND federal. Ver o aviso no topo do arquivo.
    CASE
        WHEN d.dau_qtd_inscricoes IS NOT NULL AND u.situacao_cadastral = '04'
            THEN 'NEGATIVA IMPROVÁVEL — dívida ativa + inapta'
        WHEN d.dau_qtd_inscricoes IS NOT NULL
            THEN 'NEGATIVA IMPROVÁVEL — inscrição em dívida ativa da União'
        WHEN u.situacao_cadastral = '04'
            THEN 'RISCO ALTO — cadastro inapto'
        WHEN u.situacao_cadastral = '03'
            THEN 'RISCO — cadastro suspenso'
        ELSE 'SEM APONTAMENTO NAS FONTES ABERTAS'
    END AS cnd_federal_prognostico,

    -- Prognóstico de CDT estadual (MG) — mesma lógica, jurisdição diferente:
    -- dívida ativa da União não afeta a CDT estadual, e vice-versa.
    CASE
        WHEN dm.dam_qtd_inscricoes IS NOT NULL AND u.situacao_cadastral = '04'
            THEN 'NEGATIVA IMPROVÁVEL — dívida ativa estadual + inapta'
        WHEN dm.dam_qtd_inscricoes IS NOT NULL
            THEN 'NEGATIVA IMPROVÁVEL — inscrição em dívida ativa estadual (MG)'
        WHEN u.situacao_cadastral = '04'
            THEN 'RISCO ALTO — cadastro inapto'
        WHEN u.situacao_cadastral = '03'
            THEN 'RISCO — cadastro suspenso'
        ELSE 'SEM APONTAMENTO NAS FONTES ABERTAS'
    END AS cdt_estadual_mg_prognostico,

    -- Lista legível para o dashboard e a planilha.
    array_to_string(
        list_filter([
            CASE WHEN d.dau_qtd_inscricoes IS NOT NULL
                 THEN 'Dívida ativa da União (' || d.dau_qtd_inscricoes
                      || CASE WHEN d.dau_qtd_inscricoes = 1
                              THEN ' inscrição, R$ ' ELSE ' inscrições, R$ ' END
                      -- printf devolve 1,250,480.75 (padrão en-US); o '#' é um
                      -- pivô para trocar os separadores sem colidir.
                      || replace(replace(replace(
                             printf('%,.2f', COALESCE(d.dau_valor_total, 0)),
                             ',', '#'), '.', ','), '#', '.')
                      || ')' END,
            CASE WHEN COALESCE(d.dau_ajuizado, 0) = 1 THEN 'Débito ajuizado (execução fiscal)' END,
            CASE WHEN dm.dam_qtd_inscricoes IS NOT NULL
                 THEN 'Dívida ativa estadual MG (' || dm.dam_qtd_inscricoes
                      || CASE WHEN dm.dam_qtd_inscricoes = 1
                              THEN ' inscrição, R$ ' ELSE ' inscrições, R$ ' END
                      || replace(replace(replace(
                             printf('%,.2f', COALESCE(dm.dam_valor_total, 0)),
                             ',', '#'), '.', ','), '#', '.')
                      || COALESCE(' — ' || dm.dam_especies, '')
                      || ')' END,
            CASE WHEN u.situacao_cadastral = '04'
                 THEN 'Cadastro INAPTO' || COALESCE(' — ' || u.motivo_descricao, '') END,
            CASE WHEN u.situacao_cadastral = '03'
                 THEN 'Cadastro SUSPENSO' || COALESCE(' — ' || u.motivo_descricao, '') END,
            CASE WHEN s.sancao_qtd IS NOT NULL
                 THEN 'Sanção: ' || s.sancao_cadastros END,
            -- Datas da Receita vêm como AAAAMMDD; ninguém lê isso numa planilha.
            CASE WHEN COALESCE(u.saiu_do_simples, FALSE)
                 THEN 'Excluída do Simples em ' || COALESCE(
                          substr(u.data_exclusao_simples, 7, 2) || '/'
                          || substr(u.data_exclusao_simples, 5, 2) || '/'
                          || substr(u.data_exclusao_simples, 1, 4), '?') END
        ], x -> x IS NOT NULL),
        ' • '
    ) AS apontamentos_texto
FROM universo u
LEFT JOIN dau  d  USING (cnpj_basico)
LEFT JOIN dam  dm USING (cnpj_basico)
LEFT JOIN sanc s  USING (cnpj_basico);
