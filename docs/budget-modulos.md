# Budget por módulo

Compras mantém as configurações e os controles por família de produtos (com os produtos dentro de cada família) e fornecedor. Financeiro recebe o dashboard Budget e as configurações por projeto, departamento e categoria. As chaves e os limites existentes são preservados nas mesmas tabelas; não há migração de dados nem duplicação de orçamentos. As ações de cada tela só alteram as vertentes daquele módulo.

## Consumo financeiro

O período usa exclusivamente a data de previsão de pagamento da conta a pagar. Títulos sem essa data não são reposicionados para emissão ou vencimento. O realizado usa somente o valor efetivamente pago dos movimentos financeiros ativos de natureza pagar, com data de pagamento e vínculo pelo código do título na mesma empresa. O pagamento pode ocorrer em outro mês: sua parcela paga compõe o período da previsão do título, conforme a regra solicitada. Pagamentos parciais usam somente o valor pago. Não há inferência de quitação por saldo zero ou status do título; sem pagamento confirmado sincronizado, não há consumo.

Títulos e movimentos cancelados, excluídos ou estornados não participam. As regras financeiras de contas ocultas e transferências são respeitadas. Projetos, departamentos e categorias usam os filtros do Financeiro, incluindo compartilhamento “Usar no módulo”. Rateios de categoria e departamento são aplicados à parcela efetivamente paga. A consolidação mantém a empresa junto aos códigos para não cruzar títulos ou duplicar gastos entre bases.

Os limites mensais explícitos são somados somente para os meses do período e exibidos numa linha por referência, sem repetir o gasto em cada mês. Os limites mensais antigos com mês zero mantêm a regra de meses configurados, até existirem limites mensais explícitos para a referência.

## Acesso e configuração

O novo dashboard usa a permissão `financeiro:budget`; a visualização exige o acesso correspondente, e a edição dos limites continua restrita ao gestor, Adm White Label e superuser. O Budget do Financeiro é configurado em `parametros/budget/financeiro/`; a rota antiga `parametros/budget/` permanece para Compras. Ambos têm atalho “Configurar Budget” no dashboard para quem pode administrar. As configurações gerais mostram os atalhos de Compras e Financeiro.
