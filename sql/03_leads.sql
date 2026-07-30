-- Tabela final: universo + apontamentos + regime inferido + score.
-- É o que a API e a planilha consomem.

CREATE OR REPLACE TABLE leads AS
WITH regime AS (
    SELECT
        u.cnpj_basico,

        -- Inferência de regime. NÃO é dado oficial — a base pública da Receita
        -- não informa regime. A ordem dos CASEs vai do sinal mais forte ao mais fraco.
        CASE
            -- Atividade que obriga Lucro Real por lei, independente de faturamento
            -- (art. 14 da Lei 9.718/98: bancos, seguradoras, factoring).
            WHEN list_contains({cnaes_lucro_real}, substr(u.cnae_fiscal_principal, 1, 4))
                THEN 'Lucro Real (obrigatório por atividade)'

            -- Porte "Demais" + capital alto: perfil de faturamento acima do limite
            -- do Presumido, ou empresa que opta pelo Real por margem baixa.
            WHEN u.porte_empresa = '05' AND u.capital_social >= {capital_lucro_real}
                THEN 'Lucro Real (provável)'

            -- Porte "Demais" e capital menor: cenário típico de Lucro Presumido.
            WHEN u.porte_empresa = '05'
                THEN 'Lucro Presumido (provável)'

            -- ME/EPP fora do Simples: quase sempre Presumido. Inclui quem foi
            -- excluído do Simples e ainda não reenquadrou o porte.
            WHEN u.porte_empresa IN ('01', '03')
                THEN 'Lucro Presumido (provável — ME/EPP fora do Simples)'

            ELSE 'Indeterminado'
        END AS regime_provavel,

        CASE
            WHEN list_contains({cnaes_lucro_real}, substr(u.cnae_fiscal_principal, 1, 4)) THEN 'Alta'
            WHEN u.porte_empresa = '05' THEN 'Média'
            WHEN u.porte_empresa IN ('01', '03') THEN 'Baixa'
            ELSE 'Nenhuma'
        END AS regime_confianca
    FROM universo u
),
leads_completo AS (
    SELECT
        u.cnpj,
        u.cnpj_basico,
        -- CNPJ formatado para a planilha e a tela.
        substr(u.cnpj, 1, 2) || '.' || substr(u.cnpj, 3, 3) || '.' || substr(u.cnpj, 6, 3)
            || '/' || substr(u.cnpj, 9, 4) || '-' || substr(u.cnpj, 13, 2) AS cnpj_formatado,
        u.razao_social,
        u.nome_fantasia,
        u.municipio,
        u.uf,
        u.bairro,
        u.cep,
        u.telefone,
        u.email,

        u.cnae_fiscal_principal,
        u.cnae_descricao,
        u.natureza_descricao,
        CASE u.porte_empresa
            WHEN '00' THEN 'Não informado'
            WHEN '01' THEN 'Microempresa'
            WHEN '03' THEN 'Empresa de pequeno porte'
            WHEN '05' THEN 'Demais'
        END AS porte,
        u.capital_social,
        CASE u.situacao_cadastral
            WHEN '02' THEN 'Ativa'
            WHEN '03' THEN 'Suspensa'
            WHEN '04' THEN 'Inapta'
        END AS situacao,
        u.motivo_descricao,
        u.data_inicio_atividade,

        r.regime_provavel,
        r.regime_confianca,

        a.tem_divida_ativa_uniao,
        a.dau_qtd_inscricoes,
        a.dau_valor_total,
        a.dau_ajuizado,
        a.dau_categorias,
        a.tem_divida_ativa_mg,
        a.dam_qtd_inscricoes,
        a.dam_valor_total,
        a.dam_especies,
        a.situacao_irregular,
        a.inapta,
        a.suspensa,
        a.tem_sancao,
        a.sancao_cadastros,
        a.sancao_tipos,
        a.saiu_do_simples,
        a.data_exclusao_simples,
        a.cnd_federal_prognostico,
        a.cdt_estadual_mg_prognostico,
        a.apontamentos_texto,

        -- Score 0-100: quão relevante é abordar este CNPJ.
        -- Pesos vêm de config.yml; least() trava o teto em 100.
        least(100,
              CASE WHEN a.tem_divida_ativa_uniao THEN {peso_divida_ativa_uniao} ELSE 0 END
            + CASE WHEN a.tem_divida_ativa_mg    THEN {peso_divida_ativa_mg}   ELSE 0 END
            + CASE WHEN a.situacao_irregular     THEN {peso_situacao_irregular}  ELSE 0 END
            + CASE WHEN a.tem_sancao             THEN {peso_sancao}              ELSE 0 END
            + CASE WHEN a.saiu_do_simples        THEN {peso_saiu_do_simples}     ELSE 0 END
            + CASE WHEN u.porte_empresa = '05'   THEN {peso_porte_demais}        ELSE 0 END
        ) AS score,

        -- Quantos apontamentos distintos — critério de corte e desempate de score.
        (CASE WHEN a.tem_divida_ativa_uniao THEN 1 ELSE 0 END
         + CASE WHEN a.tem_divida_ativa_mg  THEN 1 ELSE 0 END
         + CASE WHEN a.situacao_irregular   THEN 1 ELSE 0 END
         + CASE WHEN a.tem_sancao           THEN 1 ELSE 0 END
         + CASE WHEN a.saiu_do_simples      THEN 1 ELSE 0 END) AS qtd_apontamentos
    FROM universo u
    JOIN apontamentos a USING (cnpj_basico)
    JOIN regime       r USING (cnpj_basico)
)
-- Empresa sem nenhum apontamento não interessa à contabilidade: é só um CNPJ
-- fora do Simples, sem gancho comercial. `somente_com_apontamento` em
-- config.yml controla o corte; desligar volta a trazer o universo inteiro.
SELECT * FROM leads_completo
WHERE {somente_com_apontamento} = FALSE OR qtd_apontamentos > 0;

CREATE INDEX IF NOT EXISTS idx_leads_score ON leads (score);
CREATE INDEX IF NOT EXISTS idx_leads_municipio ON leads (municipio);
CREATE INDEX IF NOT EXISTS idx_leads_cnpj ON leads (cnpj);
