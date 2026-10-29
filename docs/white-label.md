# Ambientes White Label

Entrada: Configuracoes > White Label, no menu principal, inclusive antes de selecionar
uma empresa. Esta etapa cadastra os ambientes/marcas e seus CNPJs. Nao altera a marca
atual do site, nao configura DNS e nao cria hosts. Editor visual e resolucao do
ambiente pelo dominio serao implementados separadamente.

## Cadastro

O superusuario cadastra nome da marca, identificador unico, tipo (grupo empresarial
ou contabilidade/parceiro), responsavel/contatos de suporte, status e os usuarios
responsaveis. Pelo menos um administrador ativo e obrigatorio no formulario.
O identificador e interno: nao representa um dominio validado/publicado.

Os administradores designados recebem o papel efetivo Adm White Label nas empresas
vinculadas enquanto o ambiente e a conta do usuario estiverem ativos. Nao recebem
`is_superuser` ou `is_staff`; nao ha mudanca de senha ou criacao de vinculos diretos
em EmpresaUsuario. Um vinculo direto de menor privilegio nao limita a administracao
concedida explicitamente pelo ambiente. A permissao efetiva e recalculada a cada acesso.

Somente superusuarios criam ambientes, designam os administradores e alteram o
identificador/status. O administrador do ambiente edita o cadastro da marca e seus
CNPJs. Gestores, Lideres e Usuarios simples nao administram o ambiente da marca.
Ter o papel White Label em um CNPJ isolado nao permite assumir ambientes existentes;
o responsavel deve ser designado pelo superusuario.

## Empresas/CNPJs

As relacoes sao muitos-para-muitos: uma marca possui varios CNPJs e um CNPJ pode
estar em mais de uma marca, sem duplicar as tabelas de negocio ou sincronizacoes.
Nenhum vinculo e criado automaticamente para outras marcas ou seus clientes.

O superusuario pode vincular empresas cadastradas na plataforma. O administrador
de ambiente so pode selecionar empresas que ja administra por um ambiente ativo ou
por vinculo direto de perfil White Label. IDs adulterados sao rejeitados no servidor.
Remover um CNPJ retira apenas a relacao com o ambiente. Nao exclui dados, empresas,
integracoes ou usuarios. Direitos diretos em EmpresaUsuario e direitos de outra marca
continuam validos.

Depois de salvar o ambiente, Cadastrar novo CNPJ abre um cadastro de empresa com
razao social, nome fantasia, CNPJ, grupo, logo cadastral e status. O cadastro valida
duplicidade com/sem mascara, cria a empresa e seu vinculo ao ambiente em transacao.
Nao cria integracao OMIE, agendamento nem sincronizacao automatica. As credenciais e
acessos dos demais usuarios continuam sendo configurados pelas rotinas existentes.

O grupo de consolidacao dos dashboards permanece independente da marca. Vincular
CNPJs ao White Label nao altera esse campo nem consolida dados automaticamente.

## Controle de acesso e rastreabilidade

Listagem/edicao/cadastro de CNPJ conferem acesso ao ambiente no servidor. Escritas
revalidam acesso sob transacao e bloqueio do registro. Alteracoes geram AcaoUsuarioLog
com o ambiente, operador e IDs vinculados; o cadastro de CNPJ tambem identifica a empresa.
Sem ambiente ativo ou apos remocao do responsavel/CNPJ, os direitos decorrentes daquele
ambiente deixam de valer. A desativacao nao suspende direitos diretos independentes.

Quando a resolucao por dominio for implementada, sera necessario limitar tambem a
sessao, o cadastro, as consultas e os arquivos ao ambiente ativo. Esta etapa nao deve
ser tratada como isolamento completo por host ou como publicacao de uma nova marca.

## Publicacao

Requer `empresas.0055_hierarquia_perfis` e `0056_ambientes_white_label`. A primeira
converte os perfis legados; conferir os responsaveis antes de aplicar em producao.
Fazer backup e coordenar a atualizacao dos processos que importam os models/permissoes.
Os registros novos nao sao gerados automaticamente para os clientes atuais.
