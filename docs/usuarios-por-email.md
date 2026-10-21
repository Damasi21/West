# Pre-cadastro de acessos por e-mail

## Fluxo

1. Em Configuracoes > Usuarios, o gestor informa nome e e-mail. Perfil e permissoes
   sao opcionais; o padrao e Visualizador, com os modulos/dashboards permitidos pelo
   comportamento atual de listas vazias. Nenhuma conta ou senha e criada neste momento.
2. Em Criar conta, o usuario informa nome e e-mail e recebe um codigo de oito digitos.
3. Confirma o codigo e define sua senha. Os pre-cadastros ativos desse e-mail sao
   vinculados nas empresas ativas, com as permissoes preparadas pelo gestor.
4. Contas existentes exigem login com a senha atual antes da confirmacao. A senha,
   nome e e-mail existentes nao sao substituidos. E-mails ja comprovados podem receber
   novos vinculos no proximo login. Acessos existentes/inativos nunca sao sobrescritos.

O e-mail e normalizado (espacos externos e maiusculas/minusculas). A autorizacao e por
endereco completo, nunca pelo dominio. Um e-mail pode ter pre-cadastro em varias empresas.
Pre-cadastros cancelados ou de empresas inativas nao sao vinculados. Alteracoes e cancelamentos
continuam sujeitos aos papeis do gestor e ao escopo da empresa.

## Seguranca

Os codigos sao armazenados apenas como hash, expiram em 15 minutos e permitem cinco
tentativas. O reenvio tem intervalo minimo de um minuto e limite de cinco envios por e-mail
a cada hora, persistido no PostgreSQL. O ultimo codigo substitui o anterior. A confirmacao
e vinculada a sessao que solicitou o codigo e protegida por CSRF. As contas so sao criadas
apos a prova de posse do e-mail. Perfil, empresa e privilegios nao sao aceitos do cadastro publico.
Sem pre-cadastro, o usuario pode criar uma conta confirmada mas nao recebe acesso a empresa alguma.

Usuarios ja vinculados continuam com o login existente. Configuracoes > Usuarios edita suas
permissoes, nao sua identidade global ou senha. Contas legadas com e-mails duplicados precisam
ser regularizadas pelo administrador antes de receber novos acessos pelo fluxo publico.

## Deploy e e-mail

Aplicar as migracoes `accounts.0002` e `empresas.0053`. Nao ha migracao automatica dos usuarios
existentes para pre-cadastros. As alteracoes do Auditor ainda pendentes devem ser revisadas
separadamente antes de qualquer publicacao.

O container `app` agora recebe a configuracao SMTP do arquivo de ambiente de producao:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=SEU_SERVIDOR_SMTP
EMAIL_PORT=587
EMAIL_HOST_USER=SEU_USUARIO_SMTP
EMAIL_HOST_PASSWORD=SUA_CREDENCIAL_SMTP
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=SEU_REMETENTE_AUTORIZADO
EMAIL_TIMEOUT=15
```

Usar TLS/SSL e porta conforme o provedor, sem habilitar ambos simultaneamente. Nao versionar
credenciais. Validar o recebimento real e o remetente autorizado antes de publicar o fluxo.
O backend console de desenvolvimento mostra a mensagem no terminal e nao entrega e-mail real.
Falhas de envio nao criam usuario ou vinculo e sao exibidas no formulario. O pre-cadastro por si
so nao envia convite: o e-mail e enviado quando o usuario inicia o cadastro/confirmacao.
