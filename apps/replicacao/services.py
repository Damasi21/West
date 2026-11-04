from contextlib import contextmanager
from datetime import timedelta
import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.empresas.auditoria import registrar_acao
from apps.empresas.models import AcaoUsuarioLog, CategoriaOmie, IntegracaoOmie, SincronizacaoOmie
from apps.empresas.omie import _salvar_categorias
from apps.empresas.white_label_domains import _marca_host
from . import omie
from .comparacao import dados, gerar_linhas, compativel, equivalentes, impedimento, normalizar, tipo
from .models import ComparacaoReplicacao, ItemReplicacao, VinculoCategoria
from .permissions import conferir_acesso, contexto_plano


def auditar(plano, usuario, descricao, **dados_log):
    registrar_acao(usuario=usuario, empresa=plano.matriz, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
        descricao=descricao, dados={"plano_replicacao": plano.pk, **dados_log})


def identificar_aplicativos(plano):
    ids = [plano.matriz_id, *plano.destinos.values_list("empresa_id", flat=True)]
    return {str(pk): hashlib.sha256(chave.encode()).hexdigest()
            for pk, chave in IntegracaoOmie.objects.filter(empresa_id__in=ids, ativa=True).values_list("empresa_id", "app_key")}


def conferir_aplicativos(comparacao):
    if comparacao.aplicativos != identificar_aplicativos(comparacao.plano):
        raise ValidationError("A integração de uma empresa mudou após a comparação. Gere uma nova comparação com os aplicativos atuais.")


@contextmanager
def aplicativo_livre(empresa):
    if SincronizacaoOmie.objects.filter(empresa=empresa, status="em_andamento").exists():
        raise ValidationError("Há uma sincronização em andamento nesta empresa. Aguarde a conclusão e compare novamente.")
    integracao = IntegracaoOmie.objects.get(empresa=empresa, ativa=True)
    chave = int.from_bytes(hashlib.blake2b(("rep-categoria:"+integracao.app_key).encode(), digest_size=8).digest(), "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [chave])
        adquirido = cursor.fetchone()[0]
    if not adquirido:
        raise ValidationError("Outra replicação está usando este aplicativo. Aguarde e compare novamente.")
    try:
        yield integracao
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [chave])


def atualizar_catalogo(empresa, integracao):
    itens = omie.listar(integracao)
    with transaction.atomic():
        _salvar_categorias(empresa, itens)
        CategoriaOmie.objects.filter(empresa=empresa).exclude(codigo__in=[str(i['codigo']) for i in itens]).update(ativo_omie=False)
    return list(CategoriaOmie.objects.filter(empresa=empresa, ativo_omie=True).order_by("codigo"))


def solicitar_comparacao(plano, usuario):
    with transaction.atomic():
        plano = type(plano).objects.select_for_update().get(pk=plano.pk)
        conferir_acesso(plano, usuario)
        if plano.comparacoes.filter(status__in=["fila", "comparando", "enviando"]).exists():
            raise ValidationError("Já há uma comparação ou envio em processamento neste plano.")
        comparacao = ComparacaoReplicacao.objects.create(plano=plano, solicitado_por=usuario, aplicativos=identificar_aplicativos(plano))
        auditar(plano, usuario, "Solicitou comparação de categorias", comparacao_id=comparacao.pk)
        return comparacao


def publicar(comparacao, envio=False):
    from .tasks import comparar_categorias, replicar_categorias
    task = replicar_categorias if envio else comparar_categorias
    try:
        task.apply_async(args=[comparacao.pk], queue="omie_replicacao", task_id=str(comparacao.token)+("-envio" if envio else "-comparacao"), retry=False)
        return True
    except Exception:
        ComparacaoReplicacao.objects.filter(pk=comparacao.pk).update(mensagem="Aguardando conexão com o worker de replicação. Use Atualizar situação / reenfileirar.")
        return False


def executar_comparacao(comparacao_id):
    with transaction.atomic():
        comparacao = ComparacaoReplicacao.objects.select_for_update(of=("self",)).select_related("plano__matriz", "plano__marca", "solicitado_por").get(pk=comparacao_id)
        if comparacao.status != "fila":
            return
        comparacao.status = "comparando"
        comparacao.iniciada_em = timezone.now()
        comparacao.save()
    plano = comparacao.plano
    token = contexto_plano(plano)
    try:
        conferir_acesso(plano, comparacao.solicitado_por)
        conferir_aplicativos(comparacao)
        with aplicativo_livre(plano.matriz) as integracao:
            origens = atualizar_catalogo(plano.matriz, integracao)
        linhas = []
        for destino in plano.destinos.select_related("empresa"):
            conferir_acesso(plano, comparacao.solicitado_por)
            conferir_aplicativos(comparacao)
            ComparacaoReplicacao.objects.filter(pk=comparacao.pk).update(mensagem=f"Consultando categorias de {destino.empresa.nome_fantasia}.", atualizada_em=timezone.now())
            with aplicativo_livre(destino.empresa) as integracao:
                categorias = atualizar_catalogo(destino.empresa, integracao)
            vinculos = destino.vinculos.select_related("origem", "categoria")
            linhas.extend(gerar_linhas(comparacao, destino, origens, categorias, vinculos))
        with transaction.atomic():
            ItemReplicacao.objects.bulk_create(linhas)
            comparacao.status = "pronta"
            comparacao.mensagem = "Cadastros consultados na OMIE. Revise e selecione os itens antes de replicar."
            comparacao.save()
        auditar(plano, comparacao.solicitado_por, "Comparação de categorias concluída", comparacao_id=comparacao.pk, itens=len(linhas))
    except Exception as exc:
        comparacao.status = "erro"
        comparacao.mensagem = " ".join(exc.messages) if isinstance(exc, (ValidationError, PermissionDenied)) and hasattr(exc, "messages") else "Não foi possível concluir as consultas à OMIE. Confira a integração e tente uma nova comparação."
        comparacao.save()
    finally:
        _marca_host.reset(token)


def pai_proposto(item):
    if item.matriz_dados["totalizadora"]:
        return None
    vinculo = VinculoCategoria.objects.filter(destino=item.destino, origem__codigo=item.matriz_dados["categoria_superior"]).select_related("categoria").first()
    if vinculo:
        return vinculo.categoria
    linha = item.comparacao.itens.filter(destino=item.destino, origem__codigo=item.matriz_dados["categoria_superior"]).select_related("categoria").first()
    return linha.categoria if linha else None


def candidatos_item(item):
    pai = pai_proposto(item)
    return [categoria for categoria in CategoriaOmie.objects.filter(empresa=item.destino.empresa, ativo_omie=True).order_by("descricao", "codigo")
            if compativel(item.matriz_dados, dados(categoria), pai.codigo if pai else None)]


def resolver_item(item, usuario, categoria_id=None, criar=False):
    with transaction.atomic():
        comparacao = ComparacaoReplicacao.objects.select_for_update().get(pk=item.comparacao_id)
        conferir_acesso(comparacao.plano, usuario)
        conferir_aplicativos(comparacao)
        item = ItemReplicacao.objects.select_for_update().get(pk=item.pk)
        if comparacao.status not in {"pronta", "concluida"} or item.status != "pendente" or item.situacao == "bloqueado":
            raise ValidationError("Este item não está disponível para resolução.")
        if criar:
            item.categoria = None
            item.destino_dados = {}
            item.situacao = "criar"
            item.mensagem = "Inclusão escolhida explicitamente. A OMIE será consultada novamente antes do envio."
        else:
            candidatos = {c.pk: c for c in candidatos_item(item)}
            categoria = candidatos.get(categoria_id)
            if not categoria:
                raise ValidationError("Escolha um cadastro ativo da empresa destino, do mesmo tipo e grupo superior.")
            if comparacao.itens.filter(destino=item.destino, categoria=categoria).exclude(pk=item.pk).exists():
                raise ValidationError("Este cadastro já está proposto para outra categoria da matriz.")
            item.categoria = categoria
            item.destino_dados = dados(categoria)
            item.situacao = "igual" if equivalentes(item.matriz_dados, item.destino_dados) else "alterar"
            item.mensagem = "Correspondência escolhida. Selecione o item para confirmar o vínculo ou a alteração."
        item.save()
        auditar(comparacao.plano, usuario, "Resolveu correspondência de categoria", item_id=item.pk, destino_categoria=item.categoria_id, criar=criar)


def aprovar(comparacao, usuario, ids):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)):
        raise ValidationError("Selecione de 1 a 200 itens distintos.")
    with transaction.atomic():
        type(comparacao.plano).objects.select_for_update().get(pk=comparacao.plano_id)
        comparacao = ComparacaoReplicacao.objects.select_for_update().get(pk=comparacao.pk)
        conferir_acesso(comparacao.plano, usuario)
        conferir_aplicativos(comparacao)
        if comparacao.plano.comparacoes.exclude(pk=comparacao.pk).filter(status__in=["fila", "comparando", "enviando"]).exists():
            raise ValidationError("Outra comparação ou envio está em processamento neste plano.")
        if comparacao.status not in {"pronta", "concluida"}:
            raise ValidationError("A comparação não está disponível para envio.")
        itens = list(comparacao.itens.select_for_update(of=("self",)).filter(pk__in=ids).select_related("origem", "destino__empresa", "categoria"))
        if len(itens) != len(ids):
            raise PermissionDenied
        if ItemReplicacao.objects.filter(destino__empresa_id__in=[i.destino.empresa_id for i in itens], status__in=["executando", "incerto"]).exists():
            raise ValidationError("Há um envio sem confirmação em uma das empresas selecionadas. Verifique esse histórico antes de novos envios para ela.")
        for item in itens:
            if item.status != "pendente" or item.situacao in {"ambiguo", "bloqueado"}:
                raise ValidationError("Resolva os vínculos pendentes antes de selecionar estes itens.")
            if dados(item.origem) != item.matriz_dados or (item.categoria and dados(item.categoria) != item.destino_dados):
                raise ValidationError("Um cadastro mudou depois da comparação. Gere uma nova comparação.")
            if ItemReplicacao.objects.filter(destino__empresa=item.destino.empresa, origem=item.origem, status__in=["fila", "executando", "incerto"]).exclude(pk=item.pk).exists():
                raise ValidationError("Há outro envio ou resultado sem confirmação para este cadastro. Verifique o histórico antes de continuar.")
            if not item.matriz_dados["totalizadora"]:
                vinculado = VinculoCategoria.objects.filter(destino=item.destino, origem__codigo=item.matriz_dados["categoria_superior"]).exists()
                if not vinculado and not any(p.destino_id == item.destino_id and p.origem.codigo == item.matriz_dados["categoria_superior"] for p in itens):
                    raise ValidationError(f"Selecione também o grupo superior de {item.origem.descricao}, ou confirme esse grupo primeiro.")
            if item.categoria and VinculoCategoria.objects.filter(destino=item.destino, categoria=item.categoria).exclude(origem=item.origem).exists():
                raise ValidationError("Uma categoria destino já está vinculada a outra origem.")
        for item in itens:
            item.status = "fila"
            item.aprovado_por = usuario
            item.aprovado_em = timezone.now()
            item.save()
        comparacao.status = "enviando"
        comparacao.iniciada_em = None
        comparacao.mensagem = "Itens selecionados aguardando o worker de replicação."
        comparacao.save()
        auditar(comparacao.plano, usuario, "Aprovou replicação de categorias", comparacao_id=comparacao.pk, itens=ids)
        return comparacao


def parametros_item(item):
    origem = item.matriz_dados
    payload = {"descricao": origem["descricao"], "natureza": origem["natureza"]}
    if item.categoria_id:
        payload["codigo"] = item.categoria.codigo
        metodo = "AlterarGrupoCategoria" if origem["totalizadora"] else "AlterarCategoria"
    elif origem["totalizadora"]:
        payload["tipo_grupo"] = tipo(origem)
        metodo = "IncluirGrupoCategoria"
    else:
        pai = VinculoCategoria.objects.filter(destino=item.destino, origem__codigo=origem["categoria_superior"]).select_related("categoria").first()
        if not pai:
            raise ValidationError("O grupo superior ainda não foi confirmado no destino. Compare novamente após tratar o grupo.")
        payload["categoria_superior"] = pai.categoria.codigo
        metodo = "IncluirCategoria"
    if not origem["totalizadora"]:
        payload["tipo_categoria"] = origem["tipo_categoria"]
    return metodo, payload


def confirmar_item(item, integracao):
    codigo = item.codigo_confirmado or (item.categoria.codigo if item.categoria_id else "")
    if not codigo:
        raise omie.OmieIncerta("Inclusão sem código confirmado. Consulte a OMIE e resolva o vínculo no histórico; não será reenviada.")
    registros = omie.listar(integracao, descricao=item.matriz_dados["descricao"])
    registro = next((r for r in registros if str(r.get("codigo")) == codigo), None)
    if registro is None:
        raise omie.OmieIncerta("A consulta ainda não confirmou o cadastro enviado. Verifique novamente.")
    with transaction.atomic():
        _salvar_categorias(item.destino.empresa, [registro])
        categoria = CategoriaOmie.objects.get(empresa=item.destino.empresa, codigo=codigo)
        pai = pai_proposto(item)
        if not compativel(item.matriz_dados, dados(categoria), pai.codigo if pai else None) or not equivalentes(item.matriz_dados, dados(categoria)):
            raise omie.OmieIncerta("A OMIE retornou dados diferentes do que foi aprovado. Revise o cadastro antes de confirmar.")
        if VinculoCategoria.objects.filter(destino=item.destino, categoria=categoria).exclude(origem=item.origem).exists():
            raise omie.OmieIncerta("O destino já está vinculado a outra categoria. Revise o histórico.")
        VinculoCategoria.objects.update_or_create(destino=item.destino, origem=item.origem,
            defaults={"categoria": categoria, "confirmado_por": item.aprovado_por})
        item.categoria = categoria
        item.codigo_confirmado = codigo
        item.status = "sucesso"
        item.mensagem = "Cadastro e vínculo confirmados na OMIE."
        item.save()
    auditar(item.comparacao.plano, item.aprovado_por, "Replicação de categoria confirmada", item_id=item.pk, destino_empresa=item.destino.empresa_id, codigo=codigo, metodo=item.metodo)


def executar_item(item, integracao, fontes, alvos):
    conferir_acesso(item.comparacao.plano, item.aprovado_por)
    conferir_aplicativos(item.comparacao)
    if fontes.get(item.origem.codigo) != item.matriz_dados:
        raise ValidationError("A matriz mudou após a aprovação. Gere uma nova comparação.")
    if item.categoria and alvos.get(item.categoria.codigo) != item.destino_dados:
        raise ValidationError("O destino mudou após a comparação. Gere uma nova comparação.")
    if not item.matriz_dados["totalizadora"]:
        pai = pai_proposto(item)
        if not pai or pai.codigo not in alvos or not alvos[pai.codigo]["totalizadora"] or alvos[pai.codigo]["conta_inativa"]:
            raise ValidationError("O grupo superior não está disponível no destino. Confirme o grupo primeiro.")
        if item.categoria and not compativel(item.matriz_dados, item.destino_dados, pai.codigo):
            raise ValidationError("A correspondência de hierarquia mudou. Compare novamente.")
    if item.categoria and item.situacao == "igual":
        item.codigo_confirmado = item.categoria.codigo
        item.metodo = "ListarCategorias"
        item.save()
        confirmar_item(item, integracao)
        return
    metodo, payload = parametros_item(item)
    if not item.categoria_id:
        if ItemReplicacao.objects.filter(destino__empresa=item.destino.empresa, status__in=["incerto", "executando"], metodo__startswith="Incluir").exclude(pk=item.pk).exists():
            raise ValidationError("Há uma inclusão sem confirmação neste destino. Verifique o histórico antes de novas inclusões.")
        possiveis = [d for d in alvos.values() if d["totalizadora"] == item.matriz_dados["totalizadora"] and tipo(d) == tipo(item.matriz_dados) and normalizar(d["descricao"]) == normalizar(payload["descricao"]) and (d["totalizadora"] or d["categoria_superior"] == payload.get("categoria_superior"))]
        if possiveis:
            raise ValidationError("Um cadastro equivalente já existe no destino. Compare novamente para vincular, evitando duplicidade.")
    item.metodo = metodo
    item.parametros = payload
    item.save()
    # Persist intent before the single HTTP write. Even a worker loss cannot
    # turn an unconfirmed inclusion back into a retryable pending item.
    resposta = omie.chamada(integracao, metodo, payload)
    codigo = str(resposta.get("codigo") or "").strip()
    if item.categoria and codigo != item.categoria.codigo:
        raise omie.OmieIncerta("Código retornado diferente do cadastro aprovado.")
    item.codigo_confirmado = codigo
    item.save()
    confirmar_item(item, integracao)
    alvos[codigo] = dados(item.categoria)


def executar_envio(comparacao_id):
    with transaction.atomic():
        comparacao = ComparacaoReplicacao.objects.select_for_update(of=("self",)).select_related("plano__matriz", "plano__marca").get(pk=comparacao_id)
        if comparacao.status != "enviando" or comparacao.iniciada_em is not None:
            return
        comparacao.iniciada_em = timezone.now()
        comparacao.save()
    plano = comparacao.plano
    token = contexto_plano(plano)
    try:
        aprovador = comparacao.itens.filter(status="fila").first()
        if not aprovador:
            return
        conferir_acesso(plano, aprovador.aprovado_por)
        conferir_aplicativos(comparacao)
        with aplicativo_livre(plano.matriz) as integracao:
            fontes = {c.codigo: dados(c) for c in atualizar_catalogo(plano.matriz, integracao)}
        for destino in plano.destinos.select_related("empresa"):
            ComparacaoReplicacao.objects.filter(pk=comparacao.pk).update(mensagem=f"Processando selecionados de {destino.empresa.nome_fantasia}.", atualizada_em=timezone.now())
            pendentes = comparacao.itens.filter(destino=destino, status="fila").select_related("origem", "categoria", "aprovado_por", "destino__empresa", "comparacao__plano").order_by("-origem__totalizadora", "origem__codigo")
            try:
                with aplicativo_livre(destino.empresa) as integracao:
                    alvos = {c.codigo: dados(c) for c in atualizar_catalogo(destino.empresa, integracao)}
                    for item in pendentes:
                        if not ItemReplicacao.objects.filter(pk=item.pk, status="fila").update(status="executando", atualizado_em=timezone.now()):
                            continue
                        item.status = "executando"
                        try:
                            executar_item(item, integracao, fontes, alvos)
                        except (ValidationError, PermissionDenied) as exc:
                            item.status = "erro"
                            item.mensagem = " ".join(exc.messages) if hasattr(exc, "messages") else "Acesso revogado antes do envio."
                            item.save()
                        except omie.OmieRecusada:
                            item.status = "erro"
                            item.mensagem = "A OMIE recusou esta operação. Revise e gere uma nova comparação."
                            item.save()
                        except Exception:
                            item.status = "incerto"
                            item.mensagem = "Resultado sem confirmação. Use Verificar envio; a operação não será repetida."
                            item.save()
            except Exception:
                comparacao.itens.filter(destino=destino, status="fila").update(status="erro", mensagem="Destino indisponível, ocupado ou sem consulta completa. Nenhum envio destes itens foi feito.")
    except Exception:
        comparacao.itens.filter(status="fila").update(status="erro", mensagem="Matriz indisponível ou acesso revogado. Nenhum envio destes itens foi feito.")
    finally:
        comparacao.status = "concluida"
        comparacao.mensagem = "Processamento finalizado. Confira o resultado individual; resultados incertos não são reenviados."
        comparacao.save()
        _marca_host.reset(token)


def verificar_item(item, usuario, codigo=None):
    conferir_acesso(item.comparacao.plano, usuario)
    conferir_aplicativos(item.comparacao)
    with transaction.atomic():
        item = ItemReplicacao.objects.select_for_update(of=("self",)).select_related("categoria", "destino__empresa", "comparacao__plano", "aprovado_por").get(pk=item.pk)
        if item.status != "incerto" and not (item.status == "executando" and item.atualizado_em < timezone.now()-timedelta(minutes=30)):
            raise ValidationError("Aguarde o processamento ou selecione um envio sem confirmação.")
        if codigo:
            conhecido = item.codigo_confirmado or (item.categoria.codigo if item.categoria_id else "")
            if conhecido and conhecido != codigo:
                raise ValidationError("O código informado difere do código original deste envio.")
            # Explicit operator reconciliation for an inclusion whose HTTP result
            # was lost. The read-only confirmation still validates type/parent/data.
            item.codigo_confirmado = codigo
        item.status = "incerto"
        item.save()
    token = contexto_plano(item.comparacao.plano)
    try:
        with aplicativo_livre(item.destino.empresa) as integracao:
            confirmar_item(item, integracao)
        auditar(item.comparacao.plano, usuario, "Verificou resultado de replicação", item_id=item.pk)
    except Exception:
        ItemReplicacao.objects.filter(pk=item.pk, status__in=["incerto", "executando"]).update(mensagem="A OMIE ainda não confirmou os dados. Confira o código no aplicativo destino e verifique novamente. Nenhum novo envio foi realizado.", atualizado_em=timezone.now())
    finally:
        _marca_host.reset(token)
