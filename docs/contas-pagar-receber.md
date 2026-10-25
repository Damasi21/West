# Dashboards de contas a pagar e contas a receber

Rotas do Financeiro: `contas-a-pagar` e `contas-a-receber`. Usam a mesma navegacao,
permissoes por dashboard e filtros persistidos de periodo/empresa/projeto/departamento/
categoria do BI. Consultam exclusivamente a base local PostgreSQL.

## Indicadores

Os quatro indicadores sao Total em aberto, Vencido, Vence hoje e A vencer no periodo.
O periodo filtra a DATA DE VENCIMENTO, inclusive nas datas inicial e final. Os tres
status sao calculados pela data local atual, independentemente do periodo escolhido:
vencido antes de hoje, vence hoje na data atual, a vencer depois de hoje. Somados,
reconciliam com o Total em aberto e com o fluxo e a composicao por categoria.

Usam o saldo `valor_a_pagar` ou `valor_a_receber`, nunca retornam ao valor original
quando o saldo e zero. Assim, pagamentos/recebimentos parciais usam somente o residual.
Saldos zero ou negativos, registros inativos, empresas inativas e titulos com status
fechado/cancelado sao excluidos. Os status sao normalizados por espacos e caixa.
Aplicam tambem as exclusoes padrao do financeiro para contas/categorias ocultas.

Nao ha reconstrucao do saldo em uma data passada. Uma selecao de mes anterior mostra
o que continua aberto hoje com vencimento naquele mes. Nao sao exibidas variacoes
historicas ou percentuais ficticios de pagamento/recebimento.

## Filtros e graficos

Projetos e categorias usam codigos compostos por empresa quando selecionados, evitando
cruzamento de codigos identicos entre empresas. O filtro de departamento usa o rateio
`distribuicao`: aplica `nPerDep` ao saldo residual ou, na ausencia desse percentual,
deriva a proporcao de `nValDep / valor_documento`. Selecoes multiplas somam as fracoes,
limitadas a 100%. Titulos sem rateio correspondente ficam fora dessa selecao.

O fluxo respeita o tipo de periodo: ano e trimestre mostram os meses; mes mostra os
dias. Intervalos personalizados de ate 62 dias mostram dias; os maiores mostram meses,
sempre somando somente as datas dentro dos limites escolhidos. A categoria mostra ate
seis maiores mais Outras categorias quando ha mais
de sete categorias. O ranking mostra cinco maiores saldos por fornecedor/cliente,
separando identidades por empresa e codigo. Todos os graficos e indicadores utilizam
o mesmo universo filtrado. A secao Vencimentos do periodo foi removida.

## Publicacao

Nao requer migracao de banco, chamada extra a OMIE ou alteracao de workers. Atualizar
a aplicacao e os estaticos. O Auditor continua pendente e nao faz parte deste ajuste.
