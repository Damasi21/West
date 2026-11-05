# Replicação de categorias entre aplicativos OMIE

Entrada: Configurações > Replicar dados, inclusive no menu principal antes de escolher
um CNPJ. A configuração é organizada por grupo: escolha o grupo já informado
nos cadastros das empresas e uma base PAI. Todas as outras empresas ativas desse
grupo, no mesmo ambiente, participam. Não monitora automaticamente cadastros feitos
diretamente no OMIE. Departamentos ficam para uma etapa posterior.

## Cadastro central e progresso

### Padronização do plano por sequência

Observações (`natureza` na API) ficam fora da padronização, do cadastro avulso e
das novas alterações de situação. Não são enviadas nem validadas pelo limite de
50 caracteres; não geram divergência entre matriz/destino nem exigem nova prévia
quando mudam isoladamente. A OMIE mantém as observações existentes e define o
padrão dos novos cadastros. Os snapshots guardam o texto para auditoria, sem
tratá-lo como campo replicado. Envios antigos incertos que efetivamente incluíram
`natureza` ainda conferem esse valor original na verificação somente de leitura.

- **Preparar prévia do plano** é uma operação distinta de **Nova categoria ou grupo**.
  Escolha as empresas FILHO por solicitação, inicialmente desmarcadas. A matriz é
  somente origem: não recebe inclusões, alterações nem inativações neste modo.
- A prévia lê categorias atualizadas das APIs, separa receitas e despesas e ordena
  grupos e filhos numericamente pelos códigos OMIE. O primeiro grupo corresponde ao
  primeiro grupo do mesmo tipo, independentemente de nome; seus filhos seguem a
  mesma regra. Vínculos antigos e semelhanças não alteram essa correspondência.
- Somente grupos/categorias ativos da matriz entram na sequência; filhos de grupos
  inativos também são ignorados. Os inativos não ocupam posições nem geram inclusões,
  alterações ou vínculos como origem. Prévias anteriores devem ser encerradas e
  refeitas antes de novos envios.
- Dentro de cada grupo: reescrever os pares existentes, criar os filhos faltantes e
  inativar os filhos excedentes. Preservar os IDs existentes no destino. Copiar
  descrição e, nos filhos, tipo, código DRE OMIE e situação da matriz. O
  vínculo personalizado `conta_dre` do BI permanece local. Raízes 1/2, contas de
  transferência e outros tipos não participam; posições `<Disponível>` da matriz
  não são categorias de negócio a incluir.
- O contrato da API de grupos não oferece `conta_inativa`. Grupos excedentes no
  destino ou grupos com situação diferente da matriz bloqueiam a empresa inteira
  na prévia, com indicação para ajuste no OMIE. Não há promessa de espelhamento
  completo quando a API não permite essa etapa. Não há inclusão de categorias inativas da origem.
- O limite de 50 caracteres da descrição é verificado antes dos envios.
  O erro identifica a base PAI/FILHO e a empresa, cada grupo/categoria com seu código
  e descrição, o campo, o tamanho atual e quanto excede. Todos os excessos encontrados
  na base são listados em linhas separadas, sem truncar nem alterar os cadastros.
  Após corrigir na OMIE, Retomar consulta refaz a leitura e atualiza o diagnóstico.
- A prévia mostra código/nome anterior, descrição/situação desejada e ação de cada
  posição. Exige selecionar novamente as empresas e confirmar o impacto histórico:
  lançamentos anteriores conservam o código, mas passam a exibir a categoria
  reescrita e sua classificação. Pode encerrar a prévia sem novos envios.
- Colisões de descrição no mesmo grupo são resolvidas na prévia: cadastros que
  ocupam um nome necessário recebem primeiro um nome temporário único; depois
  são aplicados os nomes finais. Um excedente que detenha um nome necessário
  recebe nome próprio de excedente e é inativado. Os códigos continuam os mesmos.
  Todas essas ações exigem a confirmação da prévia e aparecem no histórico. Em
  falha parcial, nomes temporários podem permanecer até a conclusão dos passos
  restantes; não existe rollback automático na OMIE. Prévias anteriores precisam
  ser encerradas/refeitas para usar esse tratamento.
- O worker recebe um plano congelado, não recalcula os pares depois de uma inclusão.
  Revalida matriz, destino, permissões e integrações. Alterações externas interrompem
  os novos envios; gere outra prévia. Cada intenção é persistida antes da única
  chamada de escrita e confirmada por consulta. Incluídos sem resposta ficam incertos
  e precisam do código encontrado na OMIE para verificação somente de leitura.
- Retomadas pulam ações já confirmadas. Nenhuma ação incerta é reenviada. Uma falha
  em um FILHO não interrompe os demais. A barra conta ações confirmadas, com nome da
  empresa e categoria atual; pendências aparecem no resultado por empresa. A leitura
  final também confirma que os códigos atribuídos pela OMIE mantiveram a sequência.
- Vínculos anteriores do destino são auditados e invalidados antes da reescrita,
  evitando reutilizar correspondências antigas numa execução parcial. Ao concluir,
  os vínculos são refeitos conforme os pares confirmados do plano.
- Usa `CadastroCategoria.modo=espelho` e a mesma fila `omie_replicacao`. A migração
  `0006_alter_cadastrocategoriaempresa_status` acrescenta o estado Bloqueada às opções
  do modelo. Publicação requer atualizar app e drenar/recriar `replicacao_worker`,
  aplicar migrations e publicar estáticos. Não exige reiniciar os workers de sync.


### Inativar e reativar categorias

- A árvore exibe **Inativar** para categorias filhas ativas e **Reativar** para
  inativas. A ação abre uma tela para escolher as empresas participantes (inclusive
  a base PAI). Apenas empresas da configuração podem ser selecionadas.
- A primeira etapa apenas consulta os OMIEs e prepara uma prévia. Correspondências
  usam vínculos existentes ou descrição exata e única no mesmo grupo superior e
  tipo. Código igual ou nome semelhante sozinho nunca autoriza a alteração.
- Na prévia, confira explicitamente cada empresa/código. Semelhanças e duplicidades
  não são pré-selecionadas. É possível escolher uma categoria compatível, desmarcar
  uma empresa ou encerrar a solicitação sem novos envios. Categorias ausentes nunca
  são criadas por esta rotina.
- Confirmada a prévia, o mesmo worker `omie_replicacao` aplica `AlterarCategoria`
  com `conta_inativa=S/N`. Código, descrição, natureza, tipo e código DRE do destino
  são preservados. Os lançamentos anteriores não são reclassificados nem excluídos.
- O estado é confirmado por nova consulta antes de marcar sucesso. Mudanças nos
  dados entre a prévia e o envio exigem nova confirmação. Estado já desejado não
  gera escrita. Resultados incertos só admitem verificação de leitura; nunca retry
  automático. O progresso e o histórico continuam por solicitação e empresa.
- Reativação exige grupo superior ativo no destino. Grupos totalizadores e contas
  de transferência não são alterados nesta etapa: o contrato documentado de
  `AlterarGrupoCategoria` não expõe `conta_inativa`, ao contrário de `AlterarCategoria`.
- Sem migração nova: utiliza modos `inativar/reativar` nas solicitações existentes.
  No deploy é necessário atualizar **app e replicacao_worker**, drenando o worker
  antes de recriá-lo; os demais workers podem permanecer em execução.

Contrato: https://api.omie.com.br/docs/apis/geral/categorias

### Configuração e cadastro

- Falhas de consulta identificam a empresa e o motivo seguro na solicitação e na
  linha da empresa. Cota diária esgotada não é tratada como erro genérico de
  integração. O HTTP 429 por limite diário encerra a consulta sem novas tentativas
  automáticas; limites por minuto e consumo redundante mantêm a espera existente.
  A cota é controlada pela OMIE e não pode ser liberada pelo BI. Nenhuma credencial
  ou resposta bruta da API é exibida na tela. Isso não altera a regra de escrita
  única nem a verificação obrigatória de envios sem confirmação.

- Na lista, **Excluir configuração** aparece somente quando não existe nenhuma
  solicitação de cadastro, atualização de árvore ou comparação, nem vínculo de
  categorias. Solicitações com erro também impedem exclusão. A ação exige uma
  confirmação e POST com CSRF, respeita as permissões e o ambiente White Label,
  registra auditoria e remove somente o plano e seus destinos. Configurações
  pausadas sem uso também podem ser excluídas. O backend bloqueia o plano e
  reconsulta o histórico, usando o mesmo lock da criação de solicitações.

- A tela mostra a árvore local de pais/filhos da base PAI. **Atualizar árvore**
  consulta os OMIEs do grupo por worker e atualiza as categorias no PostgreSQL.
- **Nova categoria** permite escolher um grupo superior ativo. Selecionar a raiz
  Receitas/Despesas cria um grupo; selecionar um grupo cria uma categoria filha.
  O modal exige marcar ao menos uma empresa destino para cada novo cadastro. A base
  PAI participa como origem. Os destinos começam desmarcados e a escolha não altera
  a configuração nem é reaproveitada na próxima categoria.
- O worker consulta a base PAI e somente os destinos marcados naquela solicitação
  antes da primeira escrita. Empresas desmarcadas não são consultadas nem recebem
  inclusões/alterações do cadastro. Atualizar árvore continua consultando as empresas
  da configuração. A seleção fica gravada na solicitação e é preservada em revisão
  e retomada; o worker rejeita linhas que não correspondam à seleção original.
  Correspondências exatas e únicas, do mesmo tipo/hierarquia, são aproveitadas.
  Semelhanças, duplicidades e nomes em outra hierarquia interrompem o envio para
  decisão. A busca inclui categorias inativas ou de outro tipo, mas elas não podem
  ser sobrescritas.
- O usuário pode escolher **Sobrescrever descrição** em um cadastro compatível ou
  **Ignorar nesta empresa**. Ignorar não renomeia nem cria uma categoria alternativa.
  Sobrescrever preserva código, natureza, tipo, DRE e dados contábeis do destino.
  Nas solicitações anteriores à regra estrita, um grupo superior ambíguo conserva
  a revisão anterior. Nos novos cadastros avulsos, ele bloqueia aquela empresa.
- No cadastro avulso novo, o grupo superior precisa existir uma única vez no destino,
  ativo, com descrição literalmente igual e o mesmo tipo (receita/despesa) da matriz.
  Grupo ausente, diferente ou ambíguo bloqueia somente aquela empresa, sem criar
  ou renomear o grupo. Corrigido o grupo, Retomar processa as empresas bloqueadas
  sem repetir os cadastros confirmados. Selecionar a raiz ainda permite criar um
  novo grupo. Solicitações antigas mantêm a regra original para não alterar uma
  decisão já registrada. Não se copiam códigos entre bases. Nova leitura antes de
  cada escrita detecta mudanças posteriores à decisão.
- A barra atualiza automaticamente, a cada três segundos, via endpoint autenticado
  sem cache. Ela conta etapas reais: consulta por empresa e conclusão por empresa.
  Mostra fase, empresa atual, quantidade concluída e resultado por base. 100% indica
  processamento encerrado; falhas e envios sem confirmação continuam discriminados.
- Escritas fazem uma tentativa HTTP. Resultado perdido permanece incerto. A opção
  **Verificar resultado sem reenviar** consulta o cadastro pelo código confirmado
  na OMIE. Só depois é possível retomar passos não enviados; sucessos não se repetem.
- O worker usa lock PostgreSQL por solicitação e o lock por aplicativo já existente.
  O cadastro central não espera a sincronização geral da empresa (que apenas lê os
  dados da OMIE); atualizar a árvore, cadastrar e verificar resultados continuam
  disponíveis enquanto aquela sincronização roda. O lock exclusivo entre
  replicações e as proteções de envios incertos continuam obrigatórios. A comparação
  antiga mantém sua regra anterior de aguardar a sincronização.
  Entregas duplicadas não iniciam um segundo processamento. Um worker vivo não é
  recuperado somente por heartbeat antigo. Perda de worker converte intenções sem
  confirmação em pendências de verificação, jamais em inclusões repetíveis.
- Usuários, composição do grupo e aplicativos são revalidados durante o processo.
  Para alterar os participantes, pause a configuração e crie outra. O histórico
  anterior permanece acessível. Não existe varredura ou cadastro em bases externas
  ao grupo/ambiente autorizado.

Migração: `0005_planoreplicacao_grupo_cadastrocategoria_and_more`. Adiciona estruturas
de cadastro e grupo com default persistente no banco (compatibilidade com versão
anterior). Configurações anteriores só recebem grupo automaticamente quando sua
matriz/destinos já correspondem exatamente a todas as empresas ativas daquele grupo.
As demais continuam na rotina anterior e exibem instrução para criar uma configuração
por grupo. No deploy, atualizar app e `replicacao_worker`; aguardar a drenagem do
worker antes de recriá-lo. As novas tarefas permanecem na fila `omie_replicacao`.

## Rotina anterior: comparação em lote e histórico

## Escopo e acesso

- Superusuário, Adm White Label ou Gestor precisam administrar a matriz e TODOS os
  destinos. Líder/Usuário simples não acessam a rotina, mesmo com acesso aos dashboards.
- No domínio White Label, matriz/destinos/planos se limitam à marca ativa. O link de
  login da marca no domínio principal também mantém o escopo da marca nesta rotina.
- A marca é gravada no plano e restaurada no contexto do worker. Cada execução e cada
  item revalidam usuário ativo, papel, vínculos, CNPJs, marca e integração atuais.
- Um plano do site geral não é exposto pelo domínio de uma marca, mesmo compartilhando
  CNPJs. Administração de outra marca não concede privilégios sobre a marca corrente.
- Na rotina anterior os destinos eram escolhidos individualmente. Novas configurações
  exigem Empresa.grupo e todos os integrantes ativos no ambiente; clientes de outros
  grupos ou de outras marcas não são incluídos.
- Os aplicativos OMIE devem ser distintos. Hashes das App Keys identificam os
  aplicativos da comparação, sem registrar chaves/segredos nos itens ou nas telas.
  Trocar aplicativo invalida a prévia/envio: exige nova comparação.
- Não há cadeias, ciclos ou múltiplas matrizes efetivas para um destino ativo.
  Matriz/destinos ficam fixados no plano para preservar histórico. Para mudar o
  conjunto, pause e crie outra configuração; resultados incertos precisam ser
  verificados antes de pausar. Configurações pausadas podem ser reativadas se não
  houver conflito com outro fluxo ativo.

## Contrato OMIE utilizado

Endpoint fixo: https://app.omie.com.br/api/v1/geral/categorias/

- ListarCategorias: paginação completa, contagem/duplicidade e envelope validados.
- IncluirGrupoCategoria: descrição, natureza, tipo_grupo R/D. Código atribuído pela OMIE.
- IncluirCategoria: categoria_superior DO DESTINO, descrição, natureza, tipo_categoria.
- AlterarGrupoCategoria: código DO DESTINO, descrição, natureza.
- AlterarCategoria: código DO DESTINO, descrição, natureza, tipo_categoria.

Descrição/natureza limitadas a 50 caracteres. Os níveis principais da estrutura
(ex.: 1/2) não são replicados. Grupos suportados têm formato 1.xx/2.xx e as categorias
precisam de grupo superior válido. Itens inativos, transferências e hierarquias
incompatíveis ficam bloqueados para revisão. Não são enviadas exclusões/inativações,
vínculos DRE, dados contábeis ou classificações financeiras de lançamentos anteriores.
ContaDRE personalizada do BI permanece independente e é preservada nos refreshes.

## Comparação e correspondências

Os dados são lidos da OMIE em tarefa de fundo e atualizam as tabelas locais pelo
mesmo salvador de categorias da sincronização existente. Cadastros ausentes são
marcados como não presentes, sem excluir registros referenciados pelo histórico.

Para detectar correspondências sem vínculo, considera-se nome normalizado, tipo
receita/despesa e grupo superior. O mesmo código com descrição diferente não é
adotado automaticamente. Nomes repetidos exigem escolha explícita. Uma coincidência
única apenas PROPOE um vínculo; ele só é persistido depois da seleção/aprovação e
confirmação na OMIE. Os códigos dos aplicativos não precisam ser iguais.

### Sugestões por semelhança de nomes (0003)

Plural, acentos e grafias próximas (ex.: Aluguel / Aluguéis) geram sugestões para
revisão. A comparação usa regras locais de grafia e similaridade textual, sem IA
ou chamadas extras à OMIE. Não infere sinônimos ou equivalência contábil. Siglas
curtas diferentes e nomes com números distintos não são aproximados.

Só entram candidatos ativos da empresa destino, do mesmo tipo receita/despesa,
nível grupo/categoria e grupo superior resolvido. São destacados até cinco nomes,
em ordem de proximidade. A igualdade exata ou um vínculo já confirmado tem prioridade.
Uma semelhança apenas coloca o item como correspondência ambígua, sem pré-selecionar,
vincular, renomear ou incluir. O usuário abre Resolver vínculo e escolhe o cadastro.
Ao aprovar a padronização depois, AlterarCategoria usa o código existente do destino.

Se os nomes representam cadastros distintos, o usuário pode escolher Criar novo.
Essa decisão registra operador, data e assinatura dos candidatos revisados. Se um
candidato mudar ou aparecer outro semelhante antes do envio, é necessária nova
revisão. Prévias antigas também são revalidadas para evitar inclusões não revisadas.
Para ver as sugestões na grade de comparações anteriores, gere nova comparação.

Publicar requer aplicar replicacao.0003/0004, atualizar app e o replicacao_worker. A
0004 mantém um padrão no banco para permitir a transição/retorno de versões que ainda
não enviam o novo campo de revisão. Drenar
graciosamente tarefas em curso desse worker antes de recriá-lo. Os demais workers
podem continuar executando as sincronizações existentes.

O vínculo persistente é único por destino+origem e destino+categoria correspondente.
Mudanças de hierarquia/tipo em um vínculo existente exigem revisão; esta versão não
move uma categoria para outro grupo. O usuário pode selecionar um correspondente
ativo do grupo correto ou declarar inclusão nova. Antes de incluir, o worker consulta
o destino e impede duplicidade quando um equivalente já existe.

Cada comparação conserva o estado matriz/destino, caminho, classificação, seleção,
aprovador/data, método, parâmetros não secretos, código confirmado, mensagem e status.
Grupos são processados antes das categorias. O filho só é incluído após confirmar o
código de seu grupo no destino; selecione ambos, ou confirme primeiro o grupo.
Itens já correspondentes apenas confirmam o vínculo, sem escrita na OMIE.

## Envio e recuperação

- Comparar/enviar são POST autenticados com CSRF. Enviar exige seleção de até 200
  itens e confirmação explícita no formulário. Filtros/paginação exibem 100 por página.
- A aprovação serializa o plano e congela os itens. Tasks repetidas não repetem um
  envio já reivindicado no banco. Reenfileirar um trabalho que ainda não iniciou é
  permitido, inclusive após falha de publicação no broker.
- Fonte e destinos são consultados novamente antes da escrita. Cadastro ou aplicativo
  alterado após a prévia bloqueia o envio para revisão. Permissões são reavaliadas.
- PostgreSQL advisory lock por aplicativo serializa as tarefas de replicação que usam
  o mesmo aplicativo. Sincronização em andamento impede iniciar aquela consulta/envio;
  o usuário é orientado a aguardar. Não interrompe workers nem sincronizações de outros
  clientes. Este lock não transforma APIs externas em transações e não bloqueia uma
  edição manual feita diretamente no OMIE após a revalidação.
- Consultas reutilizam o tratamento existente para limites/redundância da OMIE.
  Escritas fazem UMA tentativa HTTP, sem repetição automática em timeout, 429,
  resposta vazia ou erro de transporte. Apenas status de sucesso explícito com código
  permite seguir para a confirmação. Recusas explícitas ficam separadas de incertezas.
- Após escrever, ListarCategorias filtrado pela descrição confirma código, dados,
  tipo e grupo. Só então salva o cadastro/vínculo confirmado no BI e marca sucesso.
- Um destino com resultado incerto impede novos envios para ele até verificar. Os
  outros destinos continuam sendo processados. Não existe rollback global na OMIE:
  itens confirmados permanecem aplicados se outro falhar.
- Verificar envio é uma tarefa SOMENTE DE LEITURA na OMIE. Quando a resposta de uma
  inclusão não trouxe código, o operador informa o código encontrado no aplicativo
  destino; os dados/hierarquia ainda são validados. Código já conhecido não pode ser
  substituído. A verificação não repete inclusões ou alterações.
- Após 30 minutos sem conclusão, Atualizar situação permite fechar a espera:
  itens que iniciaram ficam incertos e os não iniciados ficam não enviados. Não
  libera automaticamente a repetição de uma inclusão de resultado desconhecido.
- Listagens, inclusões e confirmações consomem requisições da OMIE. A rotina não
  dispara uma sincronização master para cada alteração; consulta apenas categorias.

## Publicação

1. Fazer backup do banco/configurações. Adicionar apps.replicacao a INSTALLED_APPS já
   faz parte do código. Aplicar migrations replicacao.0001_initial e 0002.
2. Construir a imagem do app e recriar app para carregar o menu, telas e estáticos.
3. Subir o NOVO serviço replicacao_worker (fila omie_replicacao, concorrência 1):

   docker compose --env-file .docker/.env.production -f .docker/docker-compose.production.yaml up -d --no-deps replicacao_worker

   O broker deve estar ativo. Esta fila não é consumida por omie_manual/fast/full/
   normal nem auditor. Não exige reiniciar os workers ocupados para esta funcionalidade.
4. Copiar os estáticos ao diretório servido pelo Nginx do host, validar aplicação,
   ambos os domínios, permissões e presença do novo worker. Sem worker, os trabalhos
   continuam aguardando no broker; reenfileirar não substitui iniciar o serviço.
5. Validar inicialmente em aplicativos OMIE de teste: comparação; grupo novo; categoria
   nova; descrição alterada; vínculo ambíguo; falha por destino; confirmação de resultado.
   Os testes automatizados e a conferência visual utilizam exclusivamente API simulada.

Testes: apps.replicacao.tests. São cobertos vínculos/parentesco, DRE local, isolamento
por marca, autorização adulterada/revogada, idempotência, falha de broker, mudança
remota/credenciais após aprovação, escrita sem repetição e verificação somente leitura.

Resultados parciais exibem "Processamento interrompido: há pendências", inclusive
no histórico e no polling. Erros de escrita guardam somente a mensagem estruturada
do provedor, com credenciais redigidas. HTTP 500 com codigo_status não zero e código
de cadastro vazio é recusa explícita; sem esse contrato continua incerto. Em ambos
os casos não há repetição automática. Verificação de um resultado desconhecido
continua obrigatoriamente somente de leitura.
