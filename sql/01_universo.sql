-- Universo de leads: empresas de {uf} que NÃO são Simples/MEI.
--
-- Premissa central do projeto: a base pública da Receita não traz o regime
-- tributário. O que ela traz com certeza é quem optou pelo Simples e pelo MEI.
-- Logo, o universo "Lucro Real ou Presumido" é obtido por exclusão, e a
-- distinção entre os dois é INFERIDA (ver coluna regime_provavel e o README).

CREATE OR REPLACE VIEW vw_simples_situacao AS
SELECT
    cnpj_basico,
    opcao_pelo_simples,
    opcao_mei,
    -- Datas vêm como AAAAMMDD em texto; '0' e '00000000' significam "sem data".
    NULLIF(NULLIF(data_exclusao_simples, '0'), '00000000') AS data_exclusao_simples,
    NULLIF(NULLIF(data_exclusao_mei, '0'), '00000000')     AS data_exclusao_mei,
    NULLIF(NULLIF(data_opcao_simples, '0'), '00000000')    AS data_opcao_simples,

    -- Simples ATIVO = optou e não há data de exclusão.
    (opcao_pelo_simples = 'S'
     AND NULLIF(NULLIF(data_exclusao_simples, '0'), '00000000') IS NULL) AS simples_ativo,

    (opcao_mei = 'S'
     AND NULLIF(NULLIF(data_exclusao_mei, '0'), '00000000') IS NULL) AS mei_ativo,

    -- Já foi Simples e saiu: lead quente. Precisa de contador para reenquadrar.
    (opcao_pelo_simples = 'S'
     AND NULLIF(NULLIF(data_exclusao_simples, '0'), '00000000') IS NOT NULL) AS saiu_do_simples
FROM simples;


CREATE OR REPLACE TABLE universo AS
WITH base AS (
    SELECT
        est.cnpj_basico,
        est.cnpj_basico || est.cnpj_ordem || est.cnpj_dv AS cnpj,
        emp.razao_social,
        NULLIF(est.nome_fantasia, '')                    AS nome_fantasia,
        est.identificador_matriz_filial,
        est.situacao_cadastral,
        est.data_situacao_cadastral,
        est.motivo_situacao_cadastral,
        est.data_inicio_atividade,
        est.cnae_fiscal_principal,
        est.cnae_fiscal_secundaria,
        est.uf,
        est.municipio                                    AS municipio_codigo,
        est.bairro,
        est.cep,
        NULLIF(est.correio_eletronico, '')               AS email,
        CASE WHEN est.ddd_1 <> '' AND est.telefone_1 <> ''
             THEN '(' || est.ddd_1 || ') ' || est.telefone_1 END AS telefone,
        emp.natureza_juridica,
        emp.porte_empresa,
        -- capital_social usa vírgula decimal no CSV da Receita.
        TRY_CAST(replace(emp.capital_social, ',', '.') AS DOUBLE) AS capital_social,
        s.simples_ativo,
        s.mei_ativo,
        s.saiu_do_simples,
        s.data_exclusao_simples
    FROM estabelecimentos est
    JOIN empresas emp USING (cnpj_basico)
    LEFT JOIN vw_simples_situacao s USING (cnpj_basico)
    WHERE est.uf = '{uf}'
)
SELECT
    b.*,
    mun.descricao  AS municipio,
    cn.descricao   AS cnae_descricao,
    nat.descricao  AS natureza_descricao,
    mot.descricao  AS motivo_descricao
FROM base b
LEFT JOIN municipios mun ON mun.codigo = b.municipio_codigo
LEFT JOIN cnaes      cn  ON cn.codigo  = b.cnae_fiscal_principal
LEFT JOIN naturezas  nat ON nat.codigo = b.natureza_juridica
LEFT JOIN motivos    mot ON mot.codigo = b.motivo_situacao_cadastral
WHERE
    -- Fora do Simples e do MEI: é o recorte que a contabilidade pediu.
    -- COALESCE porque quem nunca optou não aparece na tabela `simples`.
    COALESCE(b.simples_ativo, FALSE) = FALSE
    AND COALESCE(b.mei_ativo, FALSE) = FALSE
    AND b.situacao_cadastral IN {situacoes_cadastrais}
    AND b.natureza_juridica LIKE '{prefixo_natureza_juridica}%'
    AND ({somente_matriz} = FALSE OR b.identificador_matriz_filial = '1');
