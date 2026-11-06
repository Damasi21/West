"""Cadastro central por grupo. Consultas antes de escritas, sem reenvio incerto."""
import re
from contextlib import contextmanager
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, connection
from django.utils import timezone

from apps.empresas.models import Empresa, CategoriaOmie
from apps.empresas.services import empresas_permitidas
from apps.empresas.white_label_domains import _marca_host
from . import omie
from .comparacao import dados, normalizar, semelhanca, tipo, sem_observacoes
from .models import CadastroCategoria, CadastroCategoriaEmpresa, ItemReplicacao
from .permissions import conferir_acesso, contexto_plano, empresas_gerenciaveis, planos_permitidos
from .services import aplicativo_livre, atualizar_catalogo, identificar_aplicativos, auditar


OCUPADOS = {"fila", "consultando", "enviando"}


class NovaRevisao(Exception):
    pass


class GrupoIncompativel(ValidationError):
    pass


def empresas_grupo(usuario, grupo):
    if not grupo.strip():
        raise ValidationError("Selecione um grupo cadastrado nas empresas.")
    empresas = list(empresas_permitidas(usuario).filter(grupo__iexact=grupo, ativa=True).order_by("pk"))
    # Include companies invisible to an ordinary manager as well: never silently
    # omit an inaccessible member of a group. Brand scoping is still mandatory.
    from apps.empresas.white_label_domains import marca_host_atual
    marca = marca_host_atual()
    todas = Empresa.objects.filter(grupo__iexact=grupo, ativa=True)
    if marca is not None:
        todas = todas.filter(ambientes_white_label=marca)
    ids = set(todas.values_list("pk", flat=True))
    autorizadas = set(empresas_gerenciaveis(usuario).filter(pk__in=ids).values_list("pk", flat=True))
    if ids != autorizadas or {e.pk for e in empresas} != ids:
        raise PermissionDenied("É necessário administrar todas as empresas ativas deste grupo neste ambiente.")
    if len(empresas) < 2:
        raise ValidationError("O grupo precisa ter ao menos duas empresas ativas.")
    return empresas


def conferir_grupo(plano, usuario):
    conferir_acesso(plano, usuario)
    empresas = empresas_grupo(usuario, plano.grupo)
    previstos = {plano.matriz_id, *plano.destinos.values_list("empresa_id", flat=True)}
    if {e.pk for e in empresas} != previstos:
        raise ValidationError("As empresas do grupo mudaram. Pause esta configuração e cadastre outra com os integrantes atuais.")
    return sorted(empresas, key=lambda e: (e.pk != plano.matriz_id, e.pk))


def conferir_operacao(operacao):
    empresas = conferir_grupo(operacao.plano, operacao.solicitado_por)
    if operacao.aplicativos != identificar_aplicativos(operacao.plano):
        raise ValidationError("Uma integração OMIE mudou. Inicie uma nova solicitação.")
    return empresas


def solicitar(plano, usuario, descricao="", pai=None, catalogo=False, destinos_ids=None, estrito=True):
    with transaction.atomic():
        plano = type(plano).objects.select_for_update().get(pk=plano.pk)
        empresas = conferir_grupo(plano, usuario)
        if plano.cadastros.filter(status__in=OCUPADOS | {"revisao"}).exists() or plano.comparacoes.filter(status__in=["fila", "comparando", "enviando"]).exists():
            raise ValidationError("Conclua a solicitação em andamento antes de iniciar outra.")
        if destinos_ids is not None:
            if catalogo or not isinstance(destinos_ids, list) or not destinos_ids or any(type(pk) is not int for pk in destinos_ids) or len(destinos_ids) != len(set(destinos_ids)):
                raise ValidationError("Selecione ao menos uma empresa destino, sem repetições.")
            permitidos = set(plano.destinos.values_list("empresa_id", flat=True))
            if not set(destinos_ids).issubset(permitidos):
                raise PermissionDenied("Selecione apenas empresas destino desta configuração. A base PAI já participa como origem.")
            empresas = [e for e in empresas if e.pk == plano.matriz_id or e.pk in destinos_ids]
        pedido = {}
        if not catalogo:
            descricao = descricao.strip()
            if not descricao or len(descricao) > 50:
                raise ValidationError("Informe uma descrição de até 50 caracteres.")
            if not pai or pai.empresa_id != plano.matriz_id or not pai.ativo_omie or pai.conta_inativa or pai.transferencia or not pai.totalizadora:
                raise ValidationError("Escolha um grupo superior ativo da base PAI.")
            if pai.codigo not in {"1", "2"} and not re.fullmatch(r"[12]\.\d{2}", pai.codigo):
                raise ValidationError("Este nível da hierarquia não é suportado pela OMIE nesta rotina.")
            if not tipo(dados(pai)):
                raise ValidationError("O grupo superior deve ser de receita ou despesa.")
            if len(pai.descricao) > 50:
                raise ValidationError("A descrição do grupo superior deve ter até 50 caracteres.")
            pedido = {"descricao": descricao, "pai": dados(pai), "destinos_ids": [e.pk for e in empresas if e.pk != plano.matriz_id]}
            if estrito:
                pedido["estrito"] = True
        op = CadastroCategoria.objects.create(plano=plano, solicitado_por=usuario,
            modo="catalogo" if catalogo else "cadastro", pedido=pedido,
            aplicativos=identificar_aplicativos(plano), progresso_total=len(empresas) * (1 if catalogo else 2),
            mensagem="Aguardando o worker de replicação.")
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op, empresa=e) for e in empresas])
        auditar(plano, usuario, "Solicitou cadastro central de categorias" if not catalogo else "Solicitou atualização de categorias", cadastro_id=op.pk, pedido=pedido)
        return op


def publicar_cadastro(op):
    from .tasks import cadastrar_categoria
    try:
        cadastrar_categoria.apply_async(args=[op.pk], queue="omie_replicacao", retry=False)
    except Exception:
        CadastroCategoria.objects.filter(pk=op.pk).update(mensagem="Worker indisponível. Use Retomar consulta para reenfileirar com segurança.", atualizada_em=timezone.now())


def desejadas(pedido):
    pai = pedido["pai"]
    grupo = pai["codigo"] in {"1", "2"}
    nova = {**pai, "codigo": pai["codigo"] + (".00" if grupo else ".000"),
        "descricao": pedido["descricao"], "totalizadora": grupo, "categoria_superior": pai["codigo"],
        "natureza": "", "tipo_categoria": "", "ativo_omie": True,
        "conta_inativa": False, "transferencia": False}
    return [nova] if grupo else [pai, nova]


def montar_passos(op, catalogo, antigos=()):
    """Search the WHOLE application; cross-hierarchy matches require ignoring.

    Only an exact, unique, active and structurally compatible name is reused
    automatically. Near names require a recorded choice against its snapshot.
    """
    pai_estrito = None
    if op.pedido.get("estrito") and op.pedido["pai"]["codigo"] not in {"1", "2"}:
        origem = op.pedido["pai"]
        pais = [c for c in catalogo if c["totalizadora"] and c["ativo_omie"] and not c["conta_inativa"]
            and not c["transferencia"] and tipo(c) == tipo(origem) and c["descricao"] == origem["descricao"]
            and re.fullmatch(r"[12]\.\d{2}", c["codigo"]) and c["categoria_superior"] == c["codigo"][0]]
        if len(pais) != 1:
            raise GrupoIncompativel("Cadastro bloqueado: o grupo superior deve existir uma única vez, ativo, com descrição e tipo idênticos à base PAI. Cadastre ou ajuste o grupo antes de retomar; ele não será criado automaticamente.")
        pai_estrito = pais[0]
    passos = []
    pai_codigo = op.pedido["pai"]["codigo"] if op.pedido["pai"]["codigo"] in {"1", "2"} else None
    for indice, origem in enumerate(desejadas(op.pedido)):
        anterior = deepcopy(antigos[indice]) if indice < len(antigos) else {}
        if anterior.get("status") == "ignorada":
            passos.append(anterior)
            pai_codigo = anterior.get("codigo") if origem["totalizadora"] else pai_codigo
            continue
        if anterior.get("status") == "sucesso":
            alvo = next((c for c in catalogo if c["codigo"] == anterior["codigo"]), None)
            if sem_observacoes(alvo) != sem_observacoes(anterior.get("confirmado")):
                raise ValidationError("Um cadastro já confirmado mudou na OMIE. Revise antes de continuar.")
            passos.append(anterior)
            pai_codigo = alvo["codigo"]
            continue
        if anterior.get("status") in {"executando", "incerto"}:
            raise ValidationError("Há uma escrita sem confirmação. Verifique seu resultado antes de continuar.")
        candidatos = []
        for c in catalogo:
            if pai_estrito and indice == 0 and c["codigo"] != pai_estrito["codigo"]:
                continue
            if c["codigo"] in {"1", "2"} or semelhanca(origem["descricao"], c["descricao"]) < .8:
                continue
            compativel = (c["ativo_omie"] and not c["conta_inativa"] and not c["transferencia"]
                and c["totalizadora"] == origem["totalizadora"] and tipo(c) == tipo(origem)
                and (origem["totalizadora"] or bool(pai_codigo and c["categoria_superior"] == pai_codigo)))
            candidatos.append({"dados": c, "compativel": compativel})
        candidatos.sort(key=lambda c: (-semelhanca(origem["descricao"], c["dados"]["descricao"]), c["dados"]["codigo"]))
        exatos = [c["dados"] for c in candidatos if c["compativel"] and normalizar(c["dados"]["descricao"]) == normalizar(origem["descricao"])]
        passo = {"origem": origem, "candidatos": candidatos, "acao": "criar", "status": "pendente", "alvo": None}
        decisao = anterior.get("decisao", {})
        if len(exatos) == 1:
            passo.update(acao="existente", alvo=exatos[0])
        elif candidatos:
            passo["acao"] = "conflito"
            escolhido = next((c["dados"] for c in candidatos if c["compativel"] and sem_observacoes(c["dados"]) == sem_observacoes(decisao.get("alvo"))), None)
            if decisao.get("acao") == "sobrescrever" and escolhido:
                passo.update(acao="sobrescrever", alvo=escolhido, decisao=decisao)
        passos.append(passo)
        if origem["totalizadora"]:
            pai_codigo = passo["alvo"]["codigo"] if passo["alvo"] else None
    return passos


def progresso(op, mensagem, incremento=0):
    op.mensagem = mensagem
    op.progresso_atual = min(op.progresso_total, op.progresso_atual + incremento)
    op.save(update_fields=["mensagem", "progresso_atual", "atualizada_em"])


def catalogo_dados(empresa, integracao):
    return [dados(c) for c in atualizar_catalogo(empresa, integracao)]


def conferir_sem_incerteza(empresa, propria=None):
    if ItemReplicacao.objects.filter(destino__empresa=empresa, status__in=["executando", "incerto"]).exists():
        raise ValidationError("Há um envio anterior sem confirmação nesta empresa. Verifique o histórico.")
    outros = CadastroCategoriaEmpresa.objects.filter(empresa=empresa, status__in=["executando", "incerto"])
    if propria:
        outros = outros.exclude(pk=propria.pk)
    if outros.exists():
        raise ValidationError("Há um cadastro anterior sem confirmação nesta empresa. Verifique o histórico.")


@contextmanager
def operacao_livre(pk):
    # A live worker owns this lock for the whole job. An old heartbeat alone is
    # never sufficient to reclaim a worker that may still be writing to OMIE.
    chave = f"west-cadastro-categoria:{pk}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [chave])
        if not cursor.fetchone()[0]:
            raise ValidationError("O worker ainda está executando esta solicitação.")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])


def executar_cadastro(pk):
    try:
        with operacao_livre(pk):
            _executar_cadastro(pk)
    except ValidationError:
        # A duplicate Celery delivery must leave the original worker in charge.
        return


def _executar_cadastro(pk):
    with transaction.atomic():
        op = CadastroCategoria.objects.select_for_update(of=("self",)).select_related("plano__matriz", "plano__marca", "solicitado_por").get(pk=pk)
        if op.status != "fila":
            return
        op.status = "consultando"
        op.iniciada_em = timezone.now()
        op.progresso_atual = 0
        op.save()
    token = contexto_plano(op.plano)
    try:
        conferir_operacao(op)
        if op.modo in {"inativar", "reativar"}:
            from .estado import processar
            processar(op)
            return
        if op.modo == "espelho":
            from .padronizacao import processar
            processar(op)
            return
        if op.modo == "cadastro" and "destinos_ids" in op.pedido:
            esperadas = {op.plano.matriz_id, *op.pedido["destinos_ids"]}
            permitidas = {op.plano.matriz_id, *op.plano.destinos.values_list("empresa_id", flat=True)}
            if not esperadas.issubset(permitidas) or set(op.empresas.values_list("empresa_id", flat=True)) != esperadas:
                raise ValidationError("As empresas da solicitação não correspondem aos destinos escolhidos. Inicie uma nova solicitação.")
        for linha in op.empresas.select_related("empresa"):
            progresso(op, f"Consultando categorias de {linha.empresa.nome_fantasia or linha.empresa.nome}.")
            conferir_operacao(op)
            if linha.status in {"sucesso", "ignorada"}:
                progresso(op, op.mensagem, 1)
                continue
            if linha.status == "incerto":
                raise ValidationError("Existe envio sem confirmação. Use Verificar resultado antes de retomar.")
            try:
                with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                    catalogo = catalogo_dados(linha.empresa, integracao)
            except ValidationError as exc:
                linha.status, linha.mensagem = "erro", " ".join(exc.messages)
                linha.save()
                raise
            if op.modo == "catalogo":
                linha.status, linha.mensagem = "sucesso", "Categorias atualizadas no BI."
            else:
                conferir_sem_incerteza(linha.empresa, linha)
                if linha.empresa_id == op.plano.matriz_id:
                    pai = next((c for c in catalogo if c["codigo"] == op.pedido["pai"]["codigo"]), None)
                    if sem_observacoes(pai) != sem_observacoes(op.pedido["pai"]):
                        raise ValidationError("O grupo superior da base PAI mudou. Atualize a árvore e inicie um novo cadastro.")
                try:
                    linha.passos = montar_passos(op, catalogo, linha.passos)
                except GrupoIncompativel as exc:
                    linha.status, linha.mensagem = "bloqueada", " ".join(exc.messages)
                    linha.save()
                    progresso(op, op.mensagem, 1)
                    continue
                linha.status = "revisao" if any(p["acao"] == "conflito" for p in linha.passos) else "pronta"
                linha.mensagem = "Escolha Sobrescrever descrição ou Ignorar nesta empresa." if linha.status == "revisao" else "Varredura concluída."
            linha.save()
            progresso(op, op.mensagem, 1)
        if op.modo == "catalogo":
            op.status = "concluido"
            progresso(op, "Árvore de categorias atualizada a partir dos OMIEs do grupo.")
            return
        if op.empresas.filter(status="revisao").exists():
            op.status = "revisao"
            progresso(op, "Encontramos categorias semelhantes. Resolva os conflitos para continuar; nenhum novo envio foi iniciado.")
            return
        op.status = "enviando"
        op.save()
        for linha in op.empresas.select_related("empresa"):
            if linha.status in {"sucesso", "ignorada", "bloqueada"}:
                progresso(op, op.mensagem, 1)
                continue
            nome = linha.empresa.nome_fantasia or linha.empresa.nome
            progresso(op, f"Aplicando cadastro em {nome}.")
            try:
                conferir_operacao(op)
                conferir_sem_incerteza(linha.empresa, linha)
                with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                    catalogo = catalogo_dados(linha.empresa, integracao)
                    linha.passos = montar_passos(op, catalogo, linha.passos)
                    if any(p["acao"] == "conflito" for p in linha.passos):
                        linha.status, linha.mensagem = "revisao", "O cadastro mudou após a varredura. Revise as novas semelhanças."
                        linha.save()
                        continue
                    linha.status = "executando"
                    linha.save()
                    pai_codigo = op.pedido["pai"]["codigo"] if op.pedido["pai"]["codigo"] in {"1", "2"} else None
                    for indice, passo in enumerate(linha.passos):
                        conferir_operacao(op)
                        if indice and linha.passos[indice-1].get("origem", {}).get("totalizadora") and linha.passos[indice-1].get("status") == "ignorada" and not pai_codigo:
                            linha.passos[indice].update(status="ignorada", motivo_ignorar="Grupo superior ignorado por duplicidade.")
                            linha.save()
                            continue
                        if passo.get("status") != "sucesso":
                            linha.passos = montar_passos(op, catalogo_dados(linha.empresa, integracao), linha.passos)
                            linha.save()
                            if any(p["acao"] == "conflito" for p in linha.passos):
                                raise NovaRevisao
                        progresso(op, f"{nome}: {passo['origem']['descricao']} — {passo['acao']}.")
                        linha.mensagem = f"Processando {passo['origem']['descricao']}."
                        linha.save(update_fields=["mensagem", "atualizada_em"])
                        try:
                            pai_codigo = aplicar_passo(op, linha, indice, integracao, pai_codigo)
                        except omie.OmieRecusada as exc:
                            if not omie.eh_duplicidade(exc):
                                raise
                            linha.passos[indice].update(status="ignorada", codigo_erro="102", motivo_ignorar=exc.detalhe or "Descrição já existente; envio ignorado.")
                            linha.save()
                            if passo["origem"]["totalizadora"]:
                                pai_codigo = None
                    linha.status, linha.mensagem = "sucesso", ("Processamento concluído com duplicidade(s) ignorada(s)." if any(p.get("status") == "ignorada" for p in linha.passos) else "Cadastro confirmado na OMIE e atualizado no BI.")
                    linha.save()
                    auditar(op.plano, op.solicitado_por, "Cadastro central confirmado", cadastro_id=op.pk, empresa_id=linha.empresa_id, passos=linha.passos)
            except GrupoIncompativel as exc:
                linha.status, linha.mensagem = "bloqueada", " ".join(exc.messages)
                linha.save()
            except NovaRevisao:
                linha.status, linha.mensagem = "revisao", "A OMIE mudou antes da gravação. Revise as novas correspondências."
                linha.save()
            except omie.OmieRecusada:
                linha.status, linha.mensagem = "erro", "A OMIE recusou o cadastro. Corrija a causa antes de retomar as pendências."
                linha.save()
            except (ValidationError, PermissionDenied) as exc:
                linha.status = "incerto" if any(p.get("status") == "executando" for p in linha.passos) else "erro"
                linha.mensagem = " ".join(exc.messages) if hasattr(exc, "messages") else "Acesso revogado."
                linha.save()
            except Exception:
                linha.status = "incerto" if any(p.get("status") == "executando" for p in linha.passos) else "erro"
                linha.mensagem = "Resultado sem confirmação. Verifique na OMIE antes de qualquer nova tentativa." if linha.status == "incerto" else "Empresa indisponível. Os demais destinos continuam."
                linha.save()
            finally:
                progresso(op, op.mensagem, 1)
        op.status = "revisao" if op.empresas.filter(status="revisao").exists() else "concluido"
        progresso(op, "Processamento finalizado. Confira o resultado por empresa." if op.status == "concluido" else "Novas diferenças encontradas. Resolva as pendências para continuar.")
    except Exception as exc:
        op.status = "erro"
        mensagem = " ".join(exc.messages) if isinstance(exc, (ValidationError, PermissionDenied)) and hasattr(exc, "messages") else "Não foi possível concluir a varredura. Nenhum novo envio foi iniciado; confira a integração e retome a consulta."
        progresso(op, mensagem)
    finally:
        op.save(update_fields=["status", "atualizada_em"])
        _marca_host.reset(token)


def aplicar_passo(op, linha, indice, integracao, pai_codigo):
    passo = linha.passos[indice]
    if passo.get("status") == "ignorada":
        return passo.get("codigo") if passo["origem"]["totalizadora"] else pai_codigo
    if passo.get("status") == "sucesso":
        return passo["codigo"]
    origem, alvo = passo["origem"], passo["alvo"]
    grupo = origem["totalizadora"]
    if passo["acao"] == "existente":
        passo.update(status="sucesso", codigo=alvo["codigo"], confirmado=alvo)
        linha.save()
        return alvo["codigo"]
    if passo["acao"] not in {"criar", "sobrescrever"}:
        raise ValidationError("Resolva a correspondência antes de gravar.")
    if passo["acao"] == "sobrescrever":
        # Preserve accounting metadata and the existing code. Only the description
        # changes; the API's required fields retain their destination values.
        metodo = "AlterarGrupoCategoria" if grupo else "AlterarCategoria"
        parametros = {"codigo": alvo["codigo"], "descricao": origem["descricao"]}
        if not grupo:
            parametros["tipo_categoria"] = alvo["tipo_categoria"]
    else:
        metodo = "IncluirGrupoCategoria" if grupo else "IncluirCategoria"
        parametros = {"descricao": origem["descricao"]}
        if grupo:
            parametros["tipo_grupo"] = tipo(origem)
        else:
            if not pai_codigo:
                raise ValidationError("Grupo superior não confirmado.")
            parametros.update(categoria_superior=pai_codigo, tipo_categoria=origem["tipo_categoria"])
    passo.update(status="executando", metodo=metodo, parametros=parametros, pai_confirmado=pai_codigo)
    linha.save()  # Intent durable before the single HTTP write.
    try:
        resposta = omie.chamada(integracao, metodo, parametros)
    except omie.OmieRecusada:
        passo["status"] = "erro"
        linha.save()
        raise
    codigo = str(resposta.get("codigo") or "")
    if alvo and codigo != alvo["codigo"]:
        raise omie.OmieIncerta("Código diferente do aprovado.")
    passo["codigo"] = codigo
    linha.save()
    confirmar_passo(linha, indice, integracao)
    return codigo


def confirmar_passo(linha, indice, integracao, codigo=""):
    if linha.cadastro.modo == "espelho":
        from .padronizacao import confirmar_resultado
        return confirmar_resultado(linha, indice, integracao, codigo)
    if linha.cadastro.modo in {"inativar", "reativar"}:
        from .estado import confirmar_resultado
        return confirmar_resultado(linha, indice, integracao, codigo)
    passo = linha.passos[indice]
    conhecido = passo.get("codigo") or (passo.get("alvo") or {}).get("codigo")
    if conhecido and codigo and codigo != conhecido:
        raise ValidationError("O código difere do envio original.")
    codigo = conhecido or codigo
    if not codigo:
        raise ValidationError("Informe o código confirmado no OMIE para esta inclusão.")
    catalogo = catalogo_dados(linha.empresa, integracao)
    alvo = next((c for c in catalogo if c["codigo"] == codigo), None)
    origem = passo["origem"]
    if not alvo or alvo["descricao"] != origem["descricao"] or alvo["totalizadora"] != origem["totalizadora"] or tipo(alvo) != tipo(origem) or alvo["conta_inativa"] or alvo["transferencia"]:
        raise omie.OmieIncerta("Cadastro ainda não confirmado na OMIE.")
    if not origem["totalizadora"] and alvo["categoria_superior"] != passo.get("pai_confirmado"):
        raise omie.OmieIncerta("Grupo superior divergente.")
    for campo in ["natureza", *([] if origem["totalizadora"] else ["tipo_categoria"])]:
        if campo in passo["parametros"] and alvo[campo] != passo["parametros"][campo]:
            raise omie.OmieIncerta("Dados diferentes dos enviados.")
    passo.update(status="sucesso", codigo=codigo, confirmado=alvo)
    linha.save()


def resolver_cadastro(op, usuario, escolhas):
    with transaction.atomic():
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_grupo(op.plano, usuario)
        if op.modo != "cadastro":
            raise ValidationError("Use a confirmação de situação para inativar ou reativar categorias.")
        if op.status != "revisao":
            raise ValidationError("Esta solicitação não está aguardando revisão.")
        for linha in op.empresas.filter(status="revisao").select_for_update():
            ignorar = escolhas.get(f"empresa_{linha.pk}") == "ignorar"
            if ignorar:
                linha.status, linha.mensagem = "ignorada", "Ignorada por decisão do usuário; não serão feitos novos envios nesta empresa."
            else:
                grupo_escolhido = False
                for indice, passo in enumerate(linha.passos):
                    if passo["acao"] != "conflito":
                        continue
                    codigo = escolhas.get(f"passo_{linha.pk}_{indice}", "")
                    candidato = next((c["dados"] for c in passo["candidatos"] if c["compativel"] and c["dados"]["codigo"] == codigo), None)
                    if not candidato:
                        if grupo_escolhido and not passo["origem"]["totalizadora"] and not codigo:
                            # Parent resolution changes which children are valid.
                            # Re-scan first, with zero writes until the child is resolved.
                            continue
                        raise ValidationError("Escolha qual descrição sobrescrever ou ignore a empresa. Cadastros de outro tipo ou hierarquia não podem ser sobrescritos.")
                    passo["decisao"] = {"acao": "sobrescrever", "alvo": candidato, "usuario_id": usuario.pk, "em": timezone.now().isoformat()}
                    grupo_escolhido = passo["origem"]["totalizadora"]
                linha.status, linha.mensagem = "pronta", "Decisões registradas; a OMIE será consultada novamente antes do envio."
            linha.save()
        # The actor confirming the current writes must still have every access.
        op.solicitado_por = usuario
        op.status, op.iniciada_em = "fila", None
        op.save()
        auditar(op.plano, usuario, "Resolveu conflitos do cadastro central", cadastro_id=op.pk,
            escolhas={k: escolhas.get(k) for k in escolhas if k.startswith(("empresa_", "passo_"))})
        return op


def retomar(op, usuario):
    with operacao_livre(op.pk):
        return _retomar(op, usuario)


def _retomar(op, usuario):
    # Persist recovery independently of the validation error asking the operator
    # to reconcile an uncertain write. Never turn it back into a retryable step.
    from datetime import timedelta
    with transaction.atomic():
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_grupo(op.plano, usuario)
        if op.status == "cancelada":
            raise ValidationError("Esta requisição foi cancelada. Crie uma nova solicitação para continuar.")
        if op.status in {"consultando", "enviando"} and op.atualizada_em < timezone.now() - timedelta(minutes=30):
            for linha in op.empresas.filter(status="executando"):
                linha.status = "incerto" if any(p.get("status") == "executando" for p in linha.passos) else "erro"
                linha.mensagem = "Worker sem conclusão. Verifique o resultado antes de retomar."
                linha.save()
            op.status = "erro"
            op.save()
    with transaction.atomic():
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_grupo(op.plano, usuario)
        if op.status in {"consultando", "enviando"}:
            raise ValidationError("O worker ainda está processando. Aguarde a conclusão.")
        if op.empresas.filter(status="incerto").exists():
            raise ValidationError("Verifique os envios sem confirmação antes de retomar. Nenhuma escrita será repetida.")
        if op.status == "revisao":
            raise ValidationError("Resolva os conflitos apresentados na tela.")
        if op.status == "concluido" and not op.empresas.filter(status__in=["erro", "bloqueada"]).exists():
            raise ValidationError("Esta solicitação já foi concluída.")
        if op.plano.cadastros.exclude(pk=op.pk).filter(status__in=OCUPADOS | {"revisao"}).exists():
            raise ValidationError("Há outra solicitação em andamento.")
        op.status, op.iniciada_em = "fila", None
        op.solicitado_por = usuario
        op.save()
        return op


def verificar_cadastro(linha_id, usuario_id, codigo=""):
    from django.contrib.auth import get_user_model
    linha = CadastroCategoriaEmpresa.objects.select_related("cadastro__plano__marca", "empresa").get(pk=linha_id)
    op = linha.cadastro
    token = contexto_plano(op.plano)
    try:
        conferir_grupo(op.plano, get_user_model().objects.get(pk=usuario_id))
        if op.aplicativos != identificar_aplicativos(op.plano):
            raise ValidationError("Integração alterada; confira o envio no aplicativo original.")
        with operacao_livre(op.pk), aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
            op.refresh_from_db()
            linha.refresh_from_db()
            if linha.status != "incerto":
                return
            for indice, passo in enumerate(linha.passos):
                if passo.get("status") in {"executando", "incerto"}:
                    confirmar_passo(linha, indice, integracao, codigo)
                    break
            linha.status = "sucesso" if all(p.get("status") in {"sucesso", "ignorada"} for p in linha.passos) else "erro"
            linha.mensagem = "Resultado confirmado. Retome a consulta para concluir os passos restantes." if linha.status == "erro" else "Cadastro confirmado na OMIE."
            if op.modo == "espelho":
                linha.status = "erro"
                linha.mensagem = "Resultado confirmado sem reenviar. Retome para concluir os passos restantes e validar a sequência final."
            if op.status == "cancelada":
                linha.status = "ignorada"
                linha.mensagem = "Envio verificado sem reenviar. A requisição permanece cancelada; as etapas restantes não serão executadas."
            if any(p.get("status") in {"executando", "incerto"} for p in linha.passos):
                linha.status = "incerto"
                linha.mensagem = "Ainda há envio sem confirmação. Verifique os resultados restantes sem reenviar."
            linha.save()
            auditar(op.plano, get_user_model().objects.get(pk=usuario_id), "Verificou cadastro central sem repetir escrita", cadastro_id=op.pk, empresa_id=linha.empresa_id)
    except Exception:
        CadastroCategoriaEmpresa.objects.filter(pk=linha.pk, status="incerto").update(mensagem="A OMIE ainda não confirmou o resultado. Confira o código e verifique novamente; nenhum envio foi repetido.")
    finally:
        _marca_host.reset(token)


def situacao(op):
    linhas = list(op.empresas.select_related("empresa"))
    return {"status": op.status, "rotulo": op.get_status_display(), "mensagem": op.mensagem, "atual": op.progresso_atual, "total": op.progresso_total,
        "percentual": min(100, round(op.progresso_atual * 100 / max(1, op.progresso_total))),
        "ativo": op.status in OCUPADOS,
        "empresas": [{"id": l.pk, "nome": l.empresa.nome_fantasia or l.empresa.nome, "status": l.status, "mensagem": l.mensagem} for l in linhas]}


def cancelar(op, usuario):
    """Stop future work only; uncertain sends remain visible and block that app."""
    with operacao_livre(op.pk), transaction.atomic():
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        usuario.refresh_from_db(fields=["is_active"])
        if not usuario.is_active or not planos_permitidos(usuario).filter(pk=op.plano_id).exists():
            raise PermissionDenied("É necessário administrar todas as empresas desta configuração.")
        if op.status == "cancelada":
            return op
        if op.status == "concluido" and not op.empresas.exclude(status__in=["sucesso", "ignorada"]).exists():
            raise ValidationError("Esta requisição já foi concluída sem pendências.")
        antes = list(op.empresas.values("empresa_id", "status", "passos"))
        for linha in op.empresas.select_for_update():
            incerta = False
            for passo in linha.passos:
                if passo.get("status") in {"executando", "incerto"}:
                    passo["status"] = "incerto"
                    incerta = True
                elif passo.get("status") not in {"sucesso", "ignorada"}:
                    passo["status"] = "cancelada"
            if incerta:
                linha.status, linha.mensagem = "incerto", "Requisição cancelada. Este envio continua sem confirmação; verifique seu resultado sem reenviar."
            elif linha.status not in {"sucesso", "ignorada"}:
                linha.status, linha.mensagem = "ignorada", "Etapas restantes canceladas. Alterações já confirmadas foram preservadas."
            linha.save()
        op.status = "cancelada"
        op.pedido["cancelamento"] = {"usuario_id": usuario.pk, "em": timezone.now().isoformat()}
        op.mensagem = "Requisição cancelada. Nenhuma etapa restante será enviada; as alterações confirmadas foram preservadas."
        if op.empresas.filter(status="incerto").exists():
            op.mensagem += " Há envio sem confirmação que ainda precisa de verificação."
        op.save()
        auditar(op.plano, usuario, "Cancelou requisição sem desfazer alterações OMIE", cadastro_id=op.pk, antes=antes)
        return op
