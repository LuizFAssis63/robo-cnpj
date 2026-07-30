'use strict';

const estado = {
  pagina: 1,
  porPagina: 50,
  busca: '',
  municipio: '',
  regime: '',
  ordenar: 'score',
  chips: { com_divida: false, com_divida_mg: false, irregular: false, com_sancao: false,
           ex_simples: false },
};

const $ = (sel) => document.querySelector(sel);

const inteiro = new Intl.NumberFormat('pt-BR');
const moeda = new Intl.NumberFormat('pt-BR', {
  style: 'currency', currency: 'BRL', maximumFractionDigits: 0,
});
const moedaExata = new Intl.NumberFormat('pt-BR', {
  style: 'currency', currency: 'BRL', minimumFractionDigits: 2,
});

async function buscarJson(url) {
  const resposta = await fetch(url);
  if (!resposta.ok) {
    const corpo = await resposta.json().catch(() => ({}));
    throw new Error(corpo.detail || `HTTP ${resposta.status}`);
  }
  return resposta.json();
}

/* --- Tema ---------------------------------------------------------------- */

$('#botao-tema').addEventListener('click', () => {
  const raiz = document.documentElement;
  const atual = raiz.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  raiz.dataset.theme = atual === 'dark' ? 'light' : 'dark';
});

/* --- Resumo, KPIs e barras ---------------------------------------------- */

function montarKpis(r) {
  // status reflete gravidade; o rótulo textual sempre acompanha a cor.
  const tiles = [
    { valor: inteiro.format(r.com_apontamento), rotulo: 'Com algum apontamento',
      nota: pctDe(r.com_apontamento, r.total), status: 'serious' },
    { valor: inteiro.format(r.com_divida), rotulo: 'Com dívida ativa da União',
      nota: pctDe(r.com_divida, r.total), status: 'critical' },
    { valor: moeda.format(r.valor_divida || 0), rotulo: 'Total em dívida ativa (União)',
      nota: 'Soma das inscrições na PGFN', status: 'critical' },
    { valor: inteiro.format(r.com_divida_mg), rotulo: 'Com dívida ativa estadual (MG)',
      nota: pctDe(r.com_divida_mg, r.total), status: 'critical' },
    { valor: moeda.format(r.valor_divida_mg || 0), rotulo: 'Total em dívida ativa (MG)',
      nota: 'ICMS e outros tributos estaduais, últimos 12 meses', status: 'critical' },
    { valor: inteiro.format(r.irregulares), rotulo: 'Situação cadastral irregular',
      nota: 'Suspensa ou inapta', status: 'serious' },
    { valor: inteiro.format(r.sancionadas), rotulo: 'Com sanção',
      nota: 'CEIS, CNEP ou CEPIM', status: 'warning' },
    { valor: inteiro.format(r.ex_simples), rotulo: 'Excluídas do Simples',
      nota: 'Precisam reenquadrar o regime', status: 'neutro' },
    { valor: inteiro.format(r.lucro_real), rotulo: 'Lucro Real provável',
      nota: pctDe(r.lucro_real, r.total), status: 'neutro' },
    { valor: inteiro.format(r.lucro_presumido), rotulo: 'Lucro Presumido provável',
      nota: pctDe(r.lucro_presumido, r.total), status: 'neutro' },
  ];

  $('#kpis').innerHTML = tiles.map((t) => `
    <div class="cartao kpi" data-status="${t.status}">
      <span class="valor">${t.valor}</span>
      <span class="rotulo">${t.rotulo}</span>
      <span class="nota">${t.nota}</span>
    </div>
  `).join('');
}

function pctDe(parte, total) {
  if (!total) return '—';
  return `${((parte / total) * 100).toFixed(1).replace('.', ',')}% do universo`;
}

function montarBarras(alvo, itens, obterRotulo, obterValor, obterNota) {
  if (!itens.length) {
    alvo.innerHTML = '<p class="secundario">Sem dados.</p>';
    return;
  }
  const maximo = Math.max(...itens.map(obterValor));

  alvo.innerHTML = itens.map((item) => {
    const valor = obterValor(item);
    const largura = maximo ? (valor / maximo) * 100 : 0;
    const rotulo = obterRotulo(item);
    const nota = obterNota ? obterNota(item) : inteiro.format(valor);
    return `
      <div class="barra-linha" title="${escaparAtributo(rotulo)}: ${inteiro.format(valor)}">
        <span class="barra-rotulo">${escapar(rotulo)}</span>
        <span class="trilho"><span class="preenchimento" style="width:${largura}%"></span></span>
        <span class="barra-valor">${nota}</span>
      </div>`;
  }).join('');
}

async function carregarResumo() {
  const r = await buscarJson('/api/resumo');
  $('#hero-total').textContent = inteiro.format(r.total);
  montarKpis(r);

  montarBarras(
    $('#barras-municipio'), r.por_municipio,
    (m) => m.municipio, (m) => m.total,
    (m) => `${inteiro.format(m.total)} · ${inteiro.format(m.com_apontamento)}`,
  );

  montarBarras(
    $('#barras-regime'), r.por_regime,
    (x) => x.regime, (x) => x.total,
  );
}

async function carregarMunicipios() {
  const lista = await buscarJson('/api/municipios');
  const select = $('#municipio');
  for (const nome of lista) {
    const opcao = document.createElement('option');
    opcao.value = nome;
    opcao.textContent = nome;
    select.append(opcao);
  }
}

/* --- Tabela -------------------------------------------------------------- */

function etiquetasDe(lead) {
  const etiquetas = [];
  if (lead.tem_divida_ativa_uniao) {
    etiquetas.push(['critical', `Dívida União · ${moeda.format(lead.dau_valor_total || 0)}`]);
  }
  if (lead.dau_ajuizado) etiquetas.push(['critical', 'Ajuizado']);
  if (lead.tem_divida_ativa_mg) {
    etiquetas.push(['critical', `Dívida MG · ${moeda.format(lead.dam_valor_total || 0)}`]);
  }
  if (lead.inapta) etiquetas.push(['serious', 'Inapta']);
  if (lead.suspensa) etiquetas.push(['serious', 'Suspensa']);
  if (lead.tem_sancao) etiquetas.push(['warning', `Sanção · ${lead.sancao_cadastros || ''}`]);
  if (lead.saiu_do_simples) etiquetas.push(['neutro', 'Saiu do Simples']);
  if (!etiquetas.length) etiquetas.push(['good', 'Sem apontamento']);
  return etiquetas;
}

function urlLeads() {
  const p = new URLSearchParams({
    pagina: estado.pagina,
    por_pagina: estado.porPagina,
    ordenar: estado.ordenar,
  });
  if (estado.busca) p.set('busca', estado.busca);
  if (estado.municipio) p.set('municipio', estado.municipio);
  if (estado.regime) p.set('regime', estado.regime);
  for (const [chave, ativo] of Object.entries(estado.chips)) {
    if (ativo) p.set(chave, 'true');
  }
  return `/api/leads?${p}`;
}

async function carregarLeads() {
  const corpo = $('#corpo-tabela');
  corpo.innerHTML = '<tr><td colspan="6" class="carregando">Carregando…</td></tr>';

  let dados;
  try {
    dados = await buscarJson(urlLeads());
  } catch (erro) {
    corpo.innerHTML = `<tr><td colspan="6" class="vazio">${escapar(erro.message)}</td></tr>`;
    return;
  }

  if (!dados.itens.length) {
    corpo.innerHTML = '<tr><td colspan="6" class="vazio">Nenhum lead com esses filtros.</td></tr>';
  } else {
    corpo.innerHTML = dados.itens.map((lead) => `
      <tr data-cnpj="${lead.cnpj}" tabindex="0">
        <td>
          <div class="razao">${escapar(lead.razao_social || '—')}</div>
          ${lead.nome_fantasia
            ? `<div class="secundario">${escapar(lead.nome_fantasia)}</div>` : ''}
          <div class="cnpj">${escapar(lead.cnpj_formatado)}</div>
        </td>
        <td class="secundario">${escapar(lead.municipio || '—')}</td>
        <td class="secundario">
          ${escapar(lead.regime_provavel)}
          <div class="cnpj">confiança ${escapar(lead.regime_confianca)}</div>
        </td>
        <td>${etiquetasDe(lead).map(([s, t]) =>
          `<span class="etiqueta" data-status="${s}">${escapar(t)}</span>`).join('')}</td>
        <td class="num">${lead.dau_valor_total
          ? moedaExata.format(lead.dau_valor_total) : '—'}</td>
        <td>
          <span class="score">
            <span class="score-trilho">
              <span class="score-preenchimento" style="width:${lead.score}%"></span>
            </span>
            <span class="score-num">${lead.score}</span>
          </span>
        </td>
      </tr>
    `).join('');
  }

  const inicio = dados.total ? (dados.pagina - 1) * dados.por_pagina + 1 : 0;
  const fim = Math.min(dados.pagina * dados.por_pagina, dados.total);
  $('#contagem').textContent = dados.total
    ? `${inteiro.format(inicio)}–${inteiro.format(fim)} de ${inteiro.format(dados.total)}`
    : 'Nenhum resultado';
  $('#anterior').disabled = dados.pagina <= 1;
  $('#proximo').disabled = dados.pagina >= dados.paginas;
}

/* --- Painel de detalhe --------------------------------------------------- */

function campo(rotulo, valor) {
  return `<div class="campo"><span class="rotulo">${escapar(rotulo)}</span>
          <span class="valor">${escapar(valor ?? '—')}</span></div>`;
}

// A Receita entrega AAAAMMDD; a PGFN entrega AAAA-MM-DD. Cobrimos os dois.
function dataBr(valor) {
  if (!valor) return '—';
  const texto = String(valor).trim();

  const compacta = /^(\d{4})(\d{2})(\d{2})$/.exec(texto);
  if (compacta) return `${compacta[3]}/${compacta[2]}/${compacta[1]}`;

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(texto);
  if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`;

  return texto;
}

async function abrirDetalhe(cnpj) {
  const painel = $('#painel');
  $('#detalhe-corpo').innerHTML = '<p class="carregando">Carregando…</p>';
  painel.showModal();

  let d;
  try {
    d = await buscarJson(`/api/leads/${cnpj}`);
  } catch (erro) {
    $('#detalhe-corpo').innerHTML = `<p class="vazio">${escapar(erro.message)}</p>`;
    return;
  }

  $('#detalhe-razao').textContent = d.razao_social || '—';
  $('#detalhe-cnpj').textContent = d.cnpj_formatado;

  const secoes = [];

  secoes.push(`<h3>Cadastro</h3><div class="campos">
    ${campo('Nome fantasia', d.nome_fantasia)}
    ${campo('Município', d.municipio)}
    ${campo('Bairro', d.bairro)}
    ${campo('Situação cadastral', d.situacao)}
    ${campo('Motivo', d.motivo_descricao)}
    ${campo('Início de atividade', dataBr(d.data_inicio_atividade))}
    ${campo('Natureza jurídica', d.natureza_descricao)}
    ${campo('Porte', d.porte)}
    ${campo('Capital social', d.capital_social != null
        ? moedaExata.format(d.capital_social) : '—')}
    ${campo('Telefone', d.telefone)}
    ${campo('E-mail', d.email)}
  </div>`);

  secoes.push(`<h3>Atividade principal</h3>
    <p style="margin:0">${escapar(d.cnae_fiscal_principal || '')} —
    ${escapar(d.cnae_descricao || '—')}</p>`);

  secoes.push(`<h3>Regime tributário</h3><div class="campos">
    ${campo('Regime provável', d.regime_provavel)}
    ${campo('Confiança da inferência', d.regime_confianca)}
    ${campo('Excluída do Simples em', d.saiu_do_simples
        ? dataBr(d.data_exclusao_simples) : 'Não se aplica')}
  </div>`);

  secoes.push(`<h3>Apontamentos</h3>
    <p style="margin:0 0 8px">${etiquetasDe(d).map(([s, t]) =>
      `<span class="etiqueta" data-status="${s}">${escapar(t)}</span>`).join('')}</p>
    <div class="campos">
      ${campo('Prognóstico de CND federal', d.cnd_federal_prognostico)}
      ${campo('Prognóstico de CDT estadual (MG)', d.cdt_estadual_mg_prognostico)}
    </div>`);

  if (d.inscricoes_divida?.length) {
    secoes.push(`<h3>Inscrições em dívida ativa da União (${d.inscricoes_divida.length})</h3>
      <table><thead><tr>
        <th scope="col">Categoria</th><th scope="col">Receita</th>
        <th scope="col">Inscrição</th><th scope="col" class="num">Valor</th>
      </tr></thead><tbody>
      ${d.inscricoes_divida.map((i) => `<tr>
        <td class="secundario">${escapar(i.categoria || '—')}</td>
        <td class="secundario">${escapar(i.receita_principal || '—')}</td>
        <td class="secundario">${escapar(dataBr(i.data_inscricao))}</td>
        <td class="num">${i.valor_consolidado != null
          ? moedaExata.format(i.valor_consolidado) : '—'}</td>
      </tr>`).join('')}
      </tbody></table>`);
  }

  if (d.inscricoes_divida_mg?.length) {
    secoes.push(`<h3>Inscrições em dívida ativa estadual — MG (${d.inscricoes_divida_mg.length})</h3>
      <table><thead><tr>
        <th scope="col">Tributo</th><th scope="col">CDA</th>
        <th scope="col">Inscrição</th><th scope="col" class="num">Saldo</th>
      </tr></thead><tbody>
      ${d.inscricoes_divida_mg.map((i) => `<tr>
        <td class="secundario">${escapar(i.especie || '—')}</td>
        <td class="secundario">${escapar(i.numero_cda || '—')}</td>
        <td class="secundario">${escapar(dataBr(i.data_inscricao))}</td>
        <td class="num">${i.saldo_cda != null
          ? moedaExata.format(i.saldo_cda) : '—'}</td>
      </tr>`).join('')}
      </tbody></table>`);
  }

  if (d.sancoes?.length) {
    secoes.push(`<h3>Sanções (${d.sancoes.length})</h3>
      ${d.sancoes.map((s) => `<div class="campos" style="margin-bottom:12px">
        ${campo('Cadastro', s.cadastro)}
        ${campo('Tipo', s.tipo_sancao)}
        ${campo('Órgão', s.orgao_sancionador)}
        ${campo('Vigência', `${dataBr(s.data_inicio)} a ${dataBr(s.data_fim)}`)}
      </div>`).join('')}`);
  }

  if (d.socios?.length) {
    secoes.push(`<h3>Quadro societário (${d.socios.length})</h3>
      <table><thead><tr>
        <th scope="col">Nome</th><th scope="col">Qualificação</th><th scope="col">Entrada</th>
      </tr></thead><tbody>
      ${d.socios.map((s) => `<tr>
        <td>${escapar(s.nome || '—')}</td>
        <td class="secundario">${escapar(s.qualificacao || '—')}</td>
        <td class="secundario">${escapar(dataBr(s.data_entrada_sociedade))}</td>
      </tr>`).join('')}
      </tbody></table>`);
  }

  $('#detalhe-corpo').innerHTML = secoes.join('');
}

/* --- Escapes ------------------------------------------------------------- */

function escapar(valor) {
  if (valor === null || valor === undefined) return '—';
  return String(valor).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
const escaparAtributo = escapar;

/* --- Eventos ------------------------------------------------------------- */

let debounce;
$('#busca').addEventListener('input', (e) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    estado.busca = e.target.value.trim();
    estado.pagina = 1;
    carregarLeads();
  }, 300);
});

for (const [id, chave] of [['#municipio', 'municipio'], ['#regime', 'regime'],
                           ['#ordenar', 'ordenar']]) {
  $(id).addEventListener('change', (e) => {
    estado[chave] = e.target.value;
    estado.pagina = 1;
    carregarLeads();
  });
}

for (const chip of document.querySelectorAll('.chip')) {
  chip.addEventListener('click', () => {
    const chave = chip.dataset.filtro;
    estado.chips[chave] = !estado.chips[chave];
    chip.setAttribute('aria-pressed', String(estado.chips[chave]));
    estado.pagina = 1;
    carregarLeads();
  });
}

$('#anterior').addEventListener('click', () => {
  if (estado.pagina > 1) { estado.pagina -= 1; carregarLeads(); }
});
$('#proximo').addEventListener('click', () => {
  estado.pagina += 1;
  carregarLeads();
});

$('#corpo-tabela').addEventListener('click', (e) => {
  const linha = e.target.closest('tr[data-cnpj]');
  if (linha) abrirDetalhe(linha.dataset.cnpj);
});
$('#corpo-tabela').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const linha = e.target.closest('tr[data-cnpj]');
  if (linha) abrirDetalhe(linha.dataset.cnpj);
});
$('#fechar-painel').addEventListener('click', () => $('#painel').close());

/* --- Início -------------------------------------------------------------- */

(async function iniciar() {
  try {
    await Promise.all([carregarResumo(), carregarMunicipios()]);
  } catch (erro) {
    $('#kpis').innerHTML =
      `<div class="cartao kpi" data-status="critical">
         <span class="rotulo">${escapar(erro.message)}</span>
       </div>`;
  }
  carregarLeads();
})();
