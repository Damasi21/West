# Auditor: primeira entrega

## Escopo

Leitura do PostgreSQL, sem chamadas a OMIE e sem bloquear, pagar ou alterar registros de origem.
Cinco regras: fornecedor incompleto, possivel duplicidade de titulos, valor atipico,
categoria incomum e alteracao bancaria entre capturas. Regras e parametros sao por empresa.
Evidencias e versoes anteriores sao preservadas nas tabelas `auditor_*`.
Os dados bancarios nas evidencias sao mascarados; a comparacao usa HMAC, nao o valor exposto.
O historico comeca na primeira auditoria. Nao e possivel reconstruir alteracoes intermediarias
nao capturadas, nem identificar o autor OMIE ou o beneficiario pago a partir deste motor.

## Execucao

O botao Executar auditoria envia para a fila Celery `auditor`, consumida apenas pelo
`auditor_worker`. Uma execucao ativa por empresa. Nenhuma execucao automatica apos
sincronizacao esta habilitada nesta primeira entrega. Execute apos concluir as sincronizacoes.
Se Redis falhar, a execucao registra erro e permite nova tentativa. Uma fila sem consumidor
nao executa: confira o worker antes de solicitar uma auditoria.
Esperas ainda nao iniciadas com mais de 30 minutos podem ser encerradas por um gestor
na visao geral; isso nao cancela analises em andamento. Falhas de tarefa reportadas pelo
Celery registram erro. Em queda completa do host, verificar execucoes em andamento antes
de liberar qualquer reprocessamento; nao ha recuperacao automatica desse cenario nesta fase.

Sem Celery, o operador pode executar diretamente:

```bash
python manage.py executar_auditoria --empresa SLUG_DA_EMPRESA
```

## Deploy

Fazer backup do banco e manter uma imagem anterior antes da migracao inicial.
Atualizar app e criar o novo worker; nao reiniciar workers OMIE com tarefas ativas.

```bash
docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml build app
docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml up -d --no-deps app
docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml exec app python manage.py migrate --check
docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml up -d auditor_worker
docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml logs --tail=40 auditor_worker
```

O entrypoint do app aplica migracoes e collectstatic. Se Nginx do host serve uma copia
de staticfiles em vez do volume, atualizar essa copia apos collectstatic. O volume de media
permanece independente e nao deve ser substituido.

## Interpretacao

Disponivel significa que existem registros locais recentemente atualizados, nao que a fonte
esta integralmente sincronizada. Sem dados, historico insuficiente, sincronizacao ativa ou
fontes desatualizadas impedem conclusao de conformidade. Sem alertas nunca significa
ausencia de problemas. Serie fiscal e documento original exigem conferencia nas duplicidades.
Valores e categorias usam somente datas de emissao anteriores, janela configuravel e amostra
minima. Sao heuristicas: nao corrigem sazonalidade nem quantidade/escopo automaticamente.
Tratamentos humanos nao sao reabertos automaticamente por reprocessamento do mesmo sinal.

Gestores/administradores com acesso a tela podem executar, tratar e configurar. Leitores
autorizados podem consultar. Todas as consultas e mutacoes sao limitadas a empresa da URL.
Comentarios, troca de responsavel/status e politicas registram autor e data. Nao ha IA nesta fase.

Proximos passos: coleta incremental apos sincronizacao, historico OMIE de alteracoes,
cruzamento documental completo, extrato bancario independente, correlacao de sinais,
notificacoes e controle de retencao/arquivamento das evidencias. As tabelas append-only sao
preservadas pela aplicacao, mas esta entrega nao fornece armazenamento inviolavel/WORM.
