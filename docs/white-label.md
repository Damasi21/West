# Ambientes White Label

Entrada: Configuracoes > White Label, no menu principal, inclusive antes de selecionar
uma empresa. O cadastro organiza ambientes/marcas e CNPJs. Dentro da marca, Layout,
cores e logos abre o editor de identidade visual. O dominio de acesso identifica
a marca automaticamente; DNS e certificados continuam sendo configurados no servidor.

## Cadastro

O superusuario cadastra nome da marca, tipo (grupo empresarial
ou contabilidade/parceiro), responsavel/contatos de suporte, status e os usuarios
responsaveis. Pelo menos um administrador ativo e obrigatorio no formulario.
O identificador e gerado automaticamente pelo nome, sem campo tecnico no formulario;
nomes com espacos, maiusculas e acentos sao aceitos. Colisoes recebem um sufixo interno.
Renomear uma marca preserva seu identificador e os enderecos existentes. Esse codigo
interno nao representa um dominio validado/publicado.

Os administradores designados recebem o papel efetivo Adm White Label nas empresas
vinculadas enquanto o ambiente e a conta do usuario estiverem ativos. Nao recebem
`is_superuser` ou `is_staff`; nao ha mudanca de senha ou criacao de vinculos diretos
em EmpresaUsuario. Um vinculo direto de menor privilegio nao limita a administracao
concedida explicitamente pelo ambiente. A permissao efetiva e recalculada a cada acesso.

Somente superusuarios criam ambientes, designam os administradores e alteram o
status. O administrador do ambiente edita o cadastro da marca e seus
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

Em um dominio exclusivo ativo, o ambiente do host limita a navegacao, o cadastro,
as consultas de empresas/consolidacao e os downloads privados. Permissoes por CNPJ
continuam obrigatorias; conhecer o endereco da marca nao concede acesso.

## Publicacao

Requer `empresas.0055_hierarquia_perfis` e `0056_ambientes_white_label`. A primeira
converte os perfis legados; conferir os responsaveis antes de aplicar em producao.
Fazer backup e coordenar a atualizacao dos processos que importam os models/permissoes.
Os registros novos nao sao gerados automaticamente para os clientes atuais.

## Identidade visual

`0057_identidade_white_label` adiciona o layout Classico (tres cores: principal,
secundaria e destaque) e Aurora (quatro cores, incluindo o fundo). A identidade e
ativada ao salvar o editor. Marcas existentes nao recebem o novo tema automaticamente.
O Classico preserva a composicao do login atual. Aurora usa um painel de destaque
e um cartao para o formulario. Ambos sao responsivos e exibem a marca no celular.

Superusuario e administradores explicitamente designados podem editar/visualizar
a identidade. Gestor, Lider e Usuario simples nao podem. O endpoint aceita somente
os campos visuais e revalida o acesso ao ambiente sob transacao. Criar marcas continua
sendo uma operacao exclusiva do superusuario.

As cores aceitam somente #RRGGBB. Cores de estados financeiros/alertas nao sao
substituidas. Texto de botoes/cabecalho e links recebe ajuste de contraste; as series
azuis padrao dos graficos seguem a identidade sem substituir cores semanticas de
pagamentos, recebimentos ou alertas.

Os logos de login e navbar sao independentes. Aceitam PNG/JPG/WebP de ate 3 MB e
4096 pixels por lado, validados pelo conteudo e regravados como PNG sem metadados,
com nomes UUID em media/white_label/<id>/. SVG e arquivos invalidos sao rejeitados.
Sem imagem, o nome da marca e exibido. Logos substituidos/removidos nao sao apagados
automaticamente do armazenamento; isso evita quebrar referencias antigas em cache.
O logo cadastral da empresa/CNPJ continua independente.

A previa em iframe exige autenticacao e autorizacao, nao aceita POST, nao altera a
sessao/marca corrente e desabilita o formulario de login. Cores e uploads locais sao
mostrados na previa antes do salvamento; apenas Salvar identidade visual persiste.

Cada marca tem o link /conta/marca/<identificador>/entrar/. Ele seleciona a identidade
na sessao para login, cadastro, recuperacao de senha e paginas do sistema. Logout
retorna ao login da marca. A lista inicial de empresas apresenta somente empresas
autorizadas e vinculadas a marca selecionada. O link nao concede acesso aos dados.
Sem selecao explicita, uma empresa com exatamente uma marca ativa/personalizada
recebe aquela identidade. Havendo varias, e preciso usar o link da marca para escolher.
Ao abrir outro CNPJ autorizado fora da marca selecionada, a identidade e reavaliada
para nao aplicar o logo de uma marca sobre uma empresa alheia.

O contexto visual e distinto do controle de acesso: permissao por CNPJ continua
valendo. O link de marca no site principal seleciona uma identidade na sessao;
ja o dominio exclusivo fixa e restringe o ambiente pelo host validado.
O site geral ELEVDATA permanece com a identidade padrao quando nenhuma marca e escolhida.

## Dominio de acesso (0058_dominio_white_label)

Em Configuracoes > White Label > Gerenciar ambiente, somente o superusuario edita
Dominio de acesso e Ativar acesso pelo dominio. Adm White Label ve o endereco em modo
de leitura; POST forjado nao altera os campos. Um dominio pertence a uma unica marca.
O endereco e normalizado para minusculas/IDNA, sem ponto final. URLs, portas, caminhos,
wildcards, IPs e os hosts principais sao rejeitados. Sem dominio, a marca continua
acessivel pelo link existente. Salvar um dominio nao valida DNS, emite SSL ou publica Nginx.

O middleware usa request.get_host() e ALLOWED_HOSTS, nunca parametros do cliente ou
X-Forwarded-Host. Hosts exclusivos desconhecidos, inativos ou desativados retornam 404;
nao caem silenciosamente no login ELEVDATA. O host tem prioridade sobre a sessao e links
de outras marcas. CNPJs externos sao negados antes das views, inclusive para superusers.
Consultas centralizadas e consolidacoes ficam restritas aos CNPJs da marca. Convites
consumidos no cadastro/login sao apenas os do ambiente; recuperacao de senha nao opera
sobre usuarios externos. Administracao global, Django Admin e trial independente sao
acessados somente pelo host principal. Administradores de marca nao ganham direitos
por serem administradores de outra marca, mesmo havendo CNPJ compartilhado.

Escopo em ContextVar e reiniciado ao final de cada request/erro e de cada trecho de
exportacao streaming. Workers e agendamentos continuam independentes do host, sem
mudanca de filas, concorrencia, sincronizacao ou base de dados. Cookies de sessao/CSRF
permanecem host-only (nao usar SESSION_COOKIE_DOMAIN ou CSRF_COOKIE_DOMAIN compartilhados).
Respostas da aplicacao em dominio de marca sao privadas/no-store. Logos e assets sao
publicos; anexos financeiros continuam privados e autorizados por CNPJ/usuario.

### Publicar app.revee.elevdata.com.br

1. Backup do BD/configuracoes; publicar codigo e aplicar migrate empresas (0058).
   Migracao aditiva, sem ativar dominios nas marcas existentes. Coordenar app/worker
   conforme mudancas do deploy; esta funcionalidade nao exige interromper sincronizacoes.
2. Confirmar a zona DNS autoritativa: em 29/10/2026 os NS publicos de elevdata.com.br
   eram hadlee.ns.cloudflare.com e shane.ns.cloudflare.com. O subdominio retornou
   NXDOMAIN em consultas local, Google DNS e no servidor. Um registro criado apenas na
   HostGator nao publica a zona mantida na Cloudflare. Criar registro A, nome app.revee,
   valor 187.127.129.222 na zona ativa; conferir tambem AAAA/CNAME conflitantes.
3. Adicionar app.revee.elevdata.com.br a ALLOWED_HOSTS e a origem HTTPS a
   CSRF_TRUSTED_ORIGINS, preservando os hosts/origens atuais. Configurar
   WHITE_LABEL_PRIMARY_HOSTS apenas com os enderecos gerais da plataforma, nunca com
   dominios de marcas. Padrao: app.elevdata.com.br,localhost,127.0.0.1,testserver.
   Reiniciar app para carregar ambiente. Nunca usar ALLOWED_HOSTS=* para contornar isso.
4. Configurar um virtual host HTTP dedicado com server_name exato e webroot ACME
   /var/www/certbot. Conferir DNS/porta 80; emitir um certificado proprio com Certbot
   (certonly --webroot -w /var/www/certbot -d app.revee.elevdata.com.br). O certificado
   atual de app.elevdata.com.br cobre apenas aquele nome, nao o novo subdominio.
5. Apos emitir, preparar virtual host HTTPS conforme
   .docker/nginx.white-label.conf.example. Este e um modelo do Nginx DO HOST; nao subir
   o proxy Compose, pois as portas 80/443 ja sao usadas pelo Nginx existente. Revisar
   paths e permissao de leitura; nginx -t antes de systemctl reload nginx.
6. No cadastro GRUPO REVEE, salvar o dominio exato e habilitar acesso. Testar HTTPS,
   login/paleta/logo, usuarios, CNPJs, consolidacao, anexos privados e logout. Testar
   tambem negacao de outra marca/CNPJ e continuidade do endereco principal.
7. Conferir renovacao automatica do certificado. Em futuras marcas, repetir DNS,
   certificado, host permitido e vinculo, sem duplicar instalacao/BD/workers.

Nao ha provisionamento automatico de infraestrutura ou chamadas externas ao salvar
o formulario. Se a publicacao falhar, desativar acesso do dominio pelo site principal;
o vinculo da marca/CNPJs e seus dados permanecem intactos.
