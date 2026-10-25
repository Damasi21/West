# Cadastro local de contas a pagar

No dashboard Contas a pagar, usuarios com acesso podem abrir Nova conta a pagar.
Visualizadores consultam, editam e enviam apenas seus proprios cadastros. Gestores e
administradores podem consultar todos os cadastros da empresa. Essa restricao tambem
vale nas rotas de edicao, envio e download de anexos. Contas a receber nao recebe esse botao.

O modal tem campos e fontes ampliados. O botao Selecionar fornecedor abre uma janela
de busca separada, por nome fantasia, razao social ou CNPJ. A escolha so muda apos
confirmar; cancelar ou pressionar Escape preserva o fornecedor anterior, demais campos
e anexos do cadastro. O seletor continua limitado aos fornecedores ativos da empresa.

Salvar o cadastro cria um rascunho local: nao chama a API da OMIE, nao escreve em
ContaPagarOmie e nao modifica os indicadores dos titulos sincronizados. Cadastros locais
abre uma consulta paginada por empresa, com os campos cadastrados e os anexos.
Rascunhos podem ser editados e enviados individualmente ou em lotes de ate 50 contas,
com confirmacao explicita. Enviar cria o titulo; nao aprova nem efetua pagamento.

## Campos e validacao

Fornecedor ativo da empresa (fornecedor ou ambos), descricao, categoria de despesa
ativa nao totalizadora, centro de custo/departamento ativo, valor positivo com duas
casas, emissao, vencimento, conta corrente ativa da empresa e forma de pagamento sao
obrigatorios. Previsao de pagamento vazia assume o vencimento. Documento/NF e
observacoes sao opcionais. Vencimento nao pode ser anterior a emissao.
Aceita formato monetario brasileiro e valor decimal sem mascara.

Forma de pagamento e uma escolha local (PIX, boleto, transferencia bancaria, dinheiro,
cartao ou outro), ainda sem mapear codigos de integracao OMIE. O valor nao cria baixa.
Todos os cadastros relacionados sao validados novamente no servidor por empresa.
O usuario e a empresa efetivos vem da sessao e da rota autorizada, nao de campos do POST.
Um token UUID por formulario garante que repetir a mesma tentativa nao duplique conta
ou anexos. Conta e metadados dos anexos sao gravados em transacao, com limpeza dos
arquivos ja gravados em caso de falha. Registra autor, data e log de criacao.

## Anexos privados

Aceita ate cinco anexos PDF, PNG ou JPEG, ate 10 MB cada e 25 MB somados. Verifica
extensao, tamanho e assinatura PDF ou integridade/formato da imagem no servidor.
Isso nao substitui uma varredura antivirus de documentos.

Armazena em PRIVATE_FILES_ROOT (padrao private_uploads/), com caminhos aleatorios por
empresa e conta, fora de media/. Nao possui URL publica. O download valida novamente
empresa e permissoes, forca attachment e envia nosniff e Cache-Control private/no-store.
Nao publicar esse diretorio no Nginx nem versionar seus arquivos.

## Envio para OMIE

O envio usa a fila omie_manual e uma chave de integracao permanente por conta local.
Enquanto processa ou aguarda confirmacao, o cadastro fica bloqueado para edicao e novo
envio. Inclusao individual confirmada registra o codigo OMIE e permanece somente para
consulta; alteracoes posteriores devem ser feitas na OMIE. Lotes aceitos precisam de
consulta individual pela chave de integracao, pois a resposta do lote nao confirma
cada titulo. O botao Verificar envio consulta os codigos sem repetir a inclusao.
Quando o worker ainda nao recebeu a tarefa, esse botao pode republicar a mesma tarefa;
a reserva transacional impede sua execucao duplicada. Respostas ambiguas ou timeout
nao provocam nova inclusao automatica. Recusa explicita permite corrigir o rascunho.

Conta corrente, fornecedor e demais referencias sao revalidados antes do envio.
Depois da confirmacao do titulo, os anexos sao enviados separadamente por lcpIncluirAnexo,
no endpoint financas/contapagaranexos/, com nCodTitulo=codigo_lancamento_omie e cNomeArq.
O servico geral/anexo retornou envelopes vazios em producao, sem confirmar a inclusao.
O servico financeiro confirma pela chave de integracao do anexo vinculada ao titulo e
ao nome do arquivo; nao retorna nIdAnexo. Consultas posteriores usam lcpConsultarAnexo.
Cada arquivo tem chave de integracao permanente de ate 20 caracteres, conteudo ZIP em
Base64 e MD5 do texto Base64 enviado em cArquivo (validado pelo retorno real da OMIE).
O nome enviado e limitado a 100 caracteres, sem caminhos
ou pontos extras, preservando o nome original no BI. O conteudo nao e persistido em JSON
nem em logs. Cada anexo registra seu status, codigo OMIE, data e erro independente.

Falha em anexo nao desfaz nem libera edicao da conta ja confirmada. O botao Processar /
verificar anexos envia os pendentes e consulta pela chave os resultados ambiguos, sem
repetir inclusoes incertas. Recusa explicita ou arquivo local indisponivel permite tentar
novamente apenas o anexo. A copia privada no BI e preservada. Cada IncluirAnexo ou
ConsultarAnexo consome uma requisicao adicional, alem das requisicoes do titulo.
Referencia: https://api.omie.com.br/docs/apis/financas/contapagaranexos
Os indicadores passam a considerar o titulo quando a sincronizacao normal o importar
da OMIE, sem somar o rascunho local em duplicidade.

## Deploy

Aplicar dashboards.0003_contas_pagar_locais, 0004_envio_contas_omie e
0005_anexos_contas_pagar_omie, atualizar estaticos
e reconstruir a imagem da aplicacao e dos workers, incluindo omie_worker_manual, para
registrar a nova tarefa Celery. O Dockerfile prepara /app/private_uploads com dono django e o Compose monta
o volume persistente WEST_PRIVATE (sobrescrevivel por PRIVATE_VOLUME_NAME) no app e no
omie_worker_manual (neste ultimo, somente leitura, para envio dos arquivos privados).
Nao recriar ou apagar esse volume no deploy. Inclui-lo nos backups junto com o banco,
pois pg_dump nao contem os arquivos.
Os workers iniciam sem reaplicar migracoes; o setup e executado pelo app.
