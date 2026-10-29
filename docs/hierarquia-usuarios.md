# Hierarquia de usuarios

Os perfis e a delegacao funcionam por empresa/CNPJ. O cadastro de ambientes de marca
e descrito em `white-label.md`; dominios e editor visual ainda serao implementados.
Nenhum papel concede acesso automatico a outros CNPJs, mesmo que estejam no mesmo grupo.
Dashboards consolidados e exportacoes conferem a permissao daquele dashboard em
cada CNPJ selecionado; pertencer ao grupo nao libera outros modulos automaticamente.

| Perfil | Administrar empresa | Convidar/editar perfis | Identidade visual da plataforma |
| --- | --- | --- | --- |
| Superusuario | Todas | Todos | Permitida |
| Adm White Label | Empresas com vinculo ativo | Adm White Label, Gestor, Lider e Usuario simples | Permitida no seu escopo |
| Gestor | Empresas com vinculo ativo | Gestor, Lider e Usuario simples | Nao permitida |
| Lider | Dashboards autorizados | Somente Usuarios simples que ele convidou | Nao permitida |
| Usuario simples | Dashboards e funcionalidades autorizados | Nenhum | Nao permitida |

`is_staff` permite acesso ao admin Django de acordo com as permissoes desse admin;
nao e mais um passe global para empresas ou dashboards. Apenas `is_superuser`
e o perfil global da plataforma. Convites nunca alteram esses atributos globais.
Responsaveis designados pelo superusuario em um ambiente ativo recebem permissao
efetiva Adm White Label sobre os CNPJs vinculados, sem alterar seus vinculos diretos.

## Delegacao

O formulario e os endpoints validam perfil, empresa e escopo no servidor. Para o
Lider, as opcoes mostram somente seus modulos/dashboards. Campos vazios sao
materializados como uma lista explicita dos acessos que ele pode delegar, sem
transformar uma selecao vazia em acesso irrestrito ao sistema.

`delegado_por` acompanha o pre-cadastro ate o primeiro acesso. A permissao efetiva
do Usuario simples e a intersecao entre seu proprio escopo e o escopo atual do
Lider. Reduzir acessos ou desativar o Lider restringe os delegados imediatamente,
inclusive convites ainda nao utilizados. Desativar a conta do Lider tambem bloqueia
a delegacao. Ampliar o escopo do Lider nao amplia as listas ja concedidas aos filhos.

O Gestor/Adm White Label pode reassumir um acesso delegado: ao salva-lo, remove o
vinculo de delegacao e passa a conceder o escopo diretamente. O Lider deixa de poder
editar aquele acesso. O Lider nao administra outros lideres nem usuarios alheios.

Operadores nao podem editar o proprio acesso nem acessos de superusuarios por esta
tela. O servidor revalida autoridade e escopo sob transacao antes de persistir.
Permissoes de funcionalidades existentes continuam verificadas nos endpoints;
Usuario simples nao significa acesso somente de leitura (por exemplo, pode criar
uma conta local propria quando autorizado ao dashboard correspondente).

## Migracao

`0055_hierarquia_perfis` adiciona os vinculos de delegacao e converte `admin` em
`lider` nos acessos e nos pre-cadastros, preservando as listas de permissoes.
`gestor` continua Gestor; `viewer` passa a ser exibido como Usuario simples.
Nao ha promocao automatica de Lider a Gestor/Adm White Label nem alteracao de
senhas, `is_staff` ou `is_superuser`. Os superusuarios devem designar os responsaveis
master de cada empresa conforme necessario.

Gestor e Adm White Label passam a ter administracao completa e acesso aos dashboards
da empresa vinculada. Restricoes por modulo/dashboard sao destinadas aos Lideres
e Usuarios simples. O logo cadastral do CNPJ e diferente da identidade visual da
plataforma, que sera controlada por `usuario_pode_personalizar_marca` na proxima etapa.

Antes da publicacao: backup, conferir os superusuarios/responsaveis, aplicar
`python manage.py migrate`, atualizar a aplicacao e os processos que importam estes
models (inclusive workers), preservando sincronizacoes em andamento. Nao executar
codigo antigo contra o novo esquema de perfis depois da conversao.
