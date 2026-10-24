# NF na aprovacao de pagamentos

O modal mostra a coluna NF. Quando existe um vinculo inequivoco, o numero abre uma
pagina interna em nova aba com cabecalho, chave de acesso, produtos, totais e parcelas.
O botao de impressao usa o navegador, inclusive sua opcao Salvar como PDF.
Essa pagina e uma visualizacao dos dados sincronizados, nao o DANFE ou XML original.
A API ListarRecebimentos/ConsultarRecebimento nao fornece um PDF nesse retorno.

## Vinculo e sincronizacao

- `cabec.nIdReceb` identifica o recebimento (`RecebimentoNfeOmie.codigo_recebimento`).
- `parcelas.parcelasLista[].nIdTitulo` identifica a conta financeira
  (`ContaPagarOmie.codigo_lancamento_omie`).
- `RecebimentoNfeTituloOmie` indexa essa relacao por recebimento e titulo.
- A sincronizacao substitui os vinculos antigos a cada atualizacao do recebimento.
  A ordem de importacao entre recebimentos e contas a pagar nao interfere.
- Recebimentos estao incluidos em Master, Compras e agora tambem Financeiro.
- A abertura do modal e da nota consulta somente o PostgreSQL, sem novas requisicoes
  a OMIE. A sincronizacao Financeiro passa a consumir tambem as chamadas ja utilizadas
  para listar e detalhar recebimentos, proporcionalmente ao numero de notas.

Nao ha vinculo por coincidencia de numero da nota, valor ou fornecedor. IDs sao sempre
isolados por empresa. Mais de um recebimento ativo para o mesmo titulo, ou fornecedor
explicitamente divergente, impede o link. Sem vinculo, o numero fiscal da conta aparece
sem link; se ausente, aparece um traco.

## Publicacao

Aplicar `python manage.py migrate` (empresas.0054). A migracao preenche o indice usando
as parcelas dos recebimentos ja salvos, sem consultar a OMIE. Quando as parcelas ainda
nao existem na base local, executar sincronizacao Financeiro, Compras ou Master.
Atualizar os arquivos estaticos e os workers que executam sincronizacao conforme o
procedimento habitual. As mudancas pausadas do Auditor nao fazem parte deste ajuste.

O endpoint de visualizacao exige login, empresa ativa autorizada e permissao para
Financeiro > Aprovacao de pagamentos. Revalida tambem os filtros de contas/categorias
visiveis do financeiro e a atividade da conta e do recebimento. Resposta privada, sem cache.
