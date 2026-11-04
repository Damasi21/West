# Replicação de categorias entre aplicativos OMIE

Entrada: Configurações > Replicar dados, inclusive no menu principal antes de escolher
um CNPJ. Primeira versão manual: matriz, destinos explícitos, comparação atualizada
na OMIE, revisão, seleção, aprovação e histórico por empresa/item. Não monitora
automaticamente alterações na matriz. Departamentos ficam para uma etapa posterior.

## Escopo e acesso

- Superusuário, Adm White Label ou Gestor precisam administrar a matriz e TODOS os
  destinos. Líder/Usuário simples não acessam a rotina, mesmo com acesso aos dashboards.
- No domínio White Label, matriz/destinos/planos se limitam à marca ativa. O link de
  login da marca no domínio principal também mantém o escopo da marca nesta rotina.
- A marca é gravada no plano e restaurada no contexto do worker. Cada execução e cada
  item revalidam usuário ativo, papel, vínculos, CNPJs, marca e integração atuais.
- Um plano do site geral não é exposto pelo domínio de uma marca, mesmo compartilhando
  CNPJs. Administração de outra marca não concede privilégios sobre a marca corrente.
- O grupo de replicação é a lista explícita de destinos; não altera Empresa.grupo e
  não inclui automaticamente os clientes de um parceiro/contabilidade.
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
