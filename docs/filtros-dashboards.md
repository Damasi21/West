# Filtros por dashboard e por modulo

O DRE Gerencial inicia em competencia. Sessoes antigas que guardaram o padrao implicito
de caixa tambem passam a iniciar em competencia. Uma escolha manual posterior de caixa
ou competencia e preservada para esse dashboard. Limpar filtros restaura o padrao.
A Visao Geral financeira mantem seu padrao de caixa.

Usar no modulo e um botao de ativacao, sem envio imediato. Ligado, fica verde. Ao
clicar em Atualizar, salva os filtros e compartilha com os dashboards compativeis do
mesmo modulo e da mesma empresa-base. O estado de ativacao acompanha a navegacao pelo
modulo. Desligar e clicar em Atualizar aplica apenas no dashboard atual; os demais
mantem a ultima selecao aplicada. Limpar filtros, quando o compartilhamento esta ativo,
tambem compartilha o reset dos controles compativeis.

Periodo (incluindo datas personalizadas), projetos, departamentos, categorias,
vendedores e demais controles so sao enviados a uma tela quando ela oferece aquele
filtro. Uma tela sem vendedor nao apaga a selecao de vendedor de outra. Aprovacao de
pagamentos, cuja barra principal tem apenas categorias, compartilha essas categorias
sem substituir periodo, projetos ou departamentos dos demais dashboards financeiros.
Os filtros especificos dos modais de aprovacao permanecem separados.

Caixa/competencia nunca integra a lista de campos compartilhados, mesmo entre DRE e
Visao Geral. Os codigos compostos por empresa sao validados contra as opcoes permitidas
do usuario. Compartilhar nao concede acesso a empresas nem a dashboards adicionais.

As preferencias ficam na sessao do usuario, com chaves por empresa/modulo/dashboard.
Nao sao preferencias globais para todos os usuarios da empresa e nao exigem migracao.
As antigas URLs com compartilhar_periodo continuam aceitas para compatibilidade.
