"""Plano por posição: prévia congelada, IDs do destino e escritas reconciliáveis."""
import re
import uuid
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import CategoriaOmie
from apps.empresas.omie import _salvar_categorias
from . import omie
from .comparacao import normalizar, tipo, sem_observacoes
from .estado import catalogo, snapshot
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa, VinculoCategoria
from .services import aplicativo_livre, identificar_aplicativos, auditar


def ordem(c):
    return tuple(int(n) for n in c["codigo"].split("."))


def origem_ativa(categorias):
    """An inactive parent excludes its descendants from the source sequence."""
    ignorados = {c["codigo"] for c in categorias if c["conta_inativa"] or not c.get("ativo_omie", True)}
    while True:
        anteriores = len(ignorados)
        ignorados.update(c["codigo"] for c in categorias if c["categoria_superior"] in ignorados)
        if len(ignorados) == anteriores:
            break
    return [c for c in categorias if c["codigo"] not in ignorados]


def estrutura(categorias, empresa=""):
    # Root totals and transfer accounts are outside the revenue/expense plan.
    itens = [c for c in categorias if c["codigo"] not in {"1", "2"} and tipo(c) and not c["transferencia"]]
    erros = []
    for c in itens:
        for campo, rotulo in (("descricao", "Descrição"),):
            tamanho = len(c[campo])
            if tamanho > 50:
                cadastro = "Grupo" if c["totalizadora"] else "Categoria"
                erros.append(f'{empresa + ": " if empresa else ""}{cadastro} {c["codigo"]} — "{c["descricao"]}". '
                    f'Campo {rotulo}: {tamanho} caracteres; máximo permitido pela OMIE: 50 '
                    f'(excede em {tamanho - 50}). Ajuste esse campo na OMIE e retome a consulta.')
    if erros:
        raise ValidationError("\n".join(erros))
    for c in itens:
        if not re.fullmatch(r"[12]\.\d+" if c["totalizadora"] else r"[12]\.\d+\.\d+", c["codigo"]):
            raise ValidationError("Há uma hierarquia não suportada. Revise os níveis na OMIE antes de padronizar.")
    grupos = sorted([c for c in itens if c["totalizadora"]], key=ordem)
    ids = {g["codigo"] for g in grupos}
    if any(g["categoria_superior"] != g["codigo"].split(".")[0] for g in grupos):
        raise ValidationError("Há grupo superior fora da hierarquia de receitas/despesas. Revise a OMIE antes de padronizar.")
    if any(not c["totalizadora"] and c["categoria_superior"] not in ids for c in itens):
        raise ValidationError("Há categoria sem grupo superior correspondente. Atualize o cadastro na OMIE.")
    return grupos, itens


def liberar_nomes(passos, destino):
    """Reserve colliding names before final writes; every rename is previewed."""
    por_codigo = {p["alvo"]["codigo"]: p for p in passos if p.get("alvo")}
    reservados = {normalizar(c["descricao"]) for c in destino} | {normalizar(p["esperado"]["descricao"]) for p in passos}
    temporarios = {}
    desejados = set()

    def nome_livre(prefixo):
        while True:
            nome = f"{prefixo} {uuid.uuid4().hex[:8]}"
            if normalizar(nome) not in reservados:
                reservados.add(normalizar(nome))
                return nome

    for passo in passos:
        if passo.get("excedente"):
            continue
        pai = passo["esperado"]["categoria_superior"]
        if not passo["grupo"]:
            grupo = passos[passo["pai_indice"]]
            # New groups have no existing children whose names could collide.
            pai = grupo["alvo"]["codigo"] if grupo.get("alvo") else "novo:" + str(passo["pai_indice"])
        chave = (passo["grupo"], pai, normalizar(passo["esperado"]["descricao"]))
        if chave in desejados:
            raise ValidationError("A base PAI possui descrições repetidas no mesmo grupo. Revise os nomes antes de padronizar.")
        desejados.add(chave)
        for atual in destino:
            if atual["totalizadora"] != passo["grupo"] or atual["categoria_superior"] != pai or normalizar(atual["descricao"]) != chave[2]:
                continue
            if passo.get("alvo") and atual["codigo"] == passo["alvo"]["codigo"]:
                continue
            dono = por_codigo.get(atual["codigo"])
            if not dono:
                raise ValidationError(f'O nome "{passo["esperado"]["descricao"]}" está ocupado pelo código {atual["codigo"]}, fora dos cadastros previstos. Revise a OMIE antes de padronizar.')
            if atual["codigo"] not in temporarios:
                transitorio = {**atual, "descricao": nome_livre("REP TMP " + atual["codigo"])}
                temporarios[atual["codigo"]] = {"origem": deepcopy(atual), "alvo": deepcopy(atual),
                    "esperado": transitorio, "acao": "temporario", "temporario": True,
                    "grupo": atual["totalizadora"], "pai_indice": None, "excedente": True,
                    "status": "pendente", "rotulo": "Liberar nome ocupado · " + atual["descricao"]}
                dono["alvo"] = deepcopy(transitorio)
                if dono.get("excedente"):
                    dono["esperado"]["descricao"] = nome_livre("Excedente " + atual["codigo"])
                if dono["acao"] == "manter":
                    dono["acao"] = "inativar" if dono.get("excedente") else "reescrever"
    iniciais = [temporarios[c] for c in sorted(temporarios, key=lambda c: tuple(int(p) for p in c.split(".")))]
    for passo in passos:
        if passo.get("pai_indice") is not None:
            passo["pai_indice"] += len(iniciais)
    return iniciais + passos


def planejar(fonte, destino, *, empresa_pai="", empresa_filho=""):
    grupos_pai, itens_pai = estrutura(origem_ativa(fonte), empresa_pai)
    if not grupos_pai:
        raise ValidationError("A matriz não possui grupos ativos de receita ou despesa para padronizar. Nenhuma alteração será enviada.")
    grupos_filho, itens_filho = estrutura(destino, empresa_filho)
    passos = []

    def adicionar(origem, alvo, pai_indice=None, excedente=False):
        grupo = (origem or alvo)["totalizadora"]
        esperado = deepcopy(origem or alvo)
        if alvo:
            esperado.update(codigo=alvo["codigo"], categoria_superior=alvo["categoria_superior"])
        else:
            esperado["codigo"] = ""
            esperado["categoria_superior"] = "" if not grupo else origem["categoria_superior"]
        esperado["natureza"] = alvo["natureza"] if alvo else ""
        if grupo:
            esperado["codigo_dre"] = alvo["codigo_dre"] if alvo else ""
        if excedente:
            esperado["conta_inativa"] = True
        if grupo and esperado["conta_inativa"] != (alvo["conta_inativa"] if alvo else False):
            raise ValidationError("A situação de um grupo pai difere da matriz. A API de grupos não oferece ativação/inativação; ajuste esse grupo na OMIE e gere outra prévia.")
        acao = "manter" if sem_observacoes(alvo) == sem_observacoes(esperado) else "inativar" if excedente else "reescrever" if alvo else "criar"
        passos.append({"origem": deepcopy(origem or alvo), "alvo": deepcopy(alvo), "esperado": esperado,
            "acao": acao, "grupo": grupo, "pai_indice": pai_indice, "excedente": excedente, "status": "pendente",
            "rotulo": ("Grupo" if grupo else "Categoria") + " · " + (origem or alvo)["descricao"]})
        return len(passos)-1

    for natureza in ("R", "D"):
        origem_grupos = [g for g in grupos_pai if tipo(g) == natureza]
        destino_grupos = [g for g in grupos_filho if tipo(g) == natureza]
        if len(destino_grupos) > len(origem_grupos):
            raise ValidationError("O destino tem grupos pais excedentes. Sua inativação não é oferecida pela API de grupos; ajuste-os na OMIE antes de padronizar. Nenhuma alteração foi autorizada nesta empresa.")
        for posicao, grupo in enumerate(origem_grupos):
            alvo = destino_grupos[posicao] if posicao < len(destino_grupos) else None
            gi = adicionar(grupo, alvo)
            filhos = sorted([c for c in itens_pai if c["categoria_superior"] == grupo["codigo"]
                and not c["totalizadora"] and normalizar(c["descricao"]) != "<disponivel>"], key=ordem)
            alvos = sorted([c for c in itens_filho if alvo and c["categoria_superior"] == alvo["codigo"] and not c["totalizadora"]], key=ordem)
            for n, filho in enumerate(filhos):
                atual = alvos[n] if n < len(alvos) else None
                adicionar(filho, atual, gi)
            for sobra in alvos[len(filhos):]:
                adicionar(None, sobra, gi, excedente=True)
    return liberar_nomes(passos, destino)


def solicitar(plano, usuario, destinos_ids):
    from .central import conferir_grupo, OCUPADOS
    with transaction.atomic():
        plano = PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        conferir_grupo(plano, usuario)
        if not isinstance(destinos_ids, list) or not destinos_ids or any(type(pk) is not int for pk in destinos_ids) or len(destinos_ids) != len(set(destinos_ids)):
            raise ValidationError("Selecione ao menos uma empresa FILHO, sem repetições.")
        if not set(destinos_ids).issubset(set(plano.destinos.values_list("empresa_id", flat=True))):
            raise PermissionDenied("Escolha somente empresas FILHO desta configuração.")
        if plano.cadastros.filter(status__in=OCUPADOS | {"revisao"}).exists() or plano.comparacoes.filter(status__in=["fila", "comparando", "enviando"]).exists():
            raise ValidationError("Conclua a solicitação em andamento antes de padronizar.")
        op = CadastroCategoria.objects.create(plano=plano, solicitado_por=usuario, modo="espelho",
            pedido={"descricao": "Padronização por sequência", "etapa": "consulta", "destinos_ids": destinos_ids},
            aplicativos=identificar_aplicativos(plano), progresso_total=len(destinos_ids)+1,
            mensagem="Aguardando o worker para preparar a prévia. A base PAI será somente consultada.")
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op, empresa_id=pk) for pk in destinos_ids])
        auditar(plano, usuario, "Solicitou prévia de padronização por posição", cadastro_id=op.pk, destinos=destinos_ids)
        return op


def confirmar(op, usuario, escolhas):
    from .central import conferir_grupo, conferir_operacao
    with transaction.atomic():
        PlanoReplicacao.objects.select_for_update().get(pk=op.plano_id)
        op = CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_grupo(op.plano, usuario)
        conferir_operacao(op)
        if op.modo != "espelho" or op.status != "revisao" or op.pedido.get("etapa") != "consulta":
            raise ValidationError("Esta prévia não está disponível para confirmação.")
        cancelar = escolhas.get("cancelar") == "sim"
        if not cancelar and not op.pedido.get("somente_ativas"):
            raise ValidationError("Encerre esta prévia anterior sem novos envios e gere outra com apenas as contas ativas da base PAI.")
        if not cancelar and op.pedido.get("versao_nomes") != 2:
            raise ValidationError("Encerre esta prévia sem novos envios e gere outra para tratar nomes já ocupados no destino antes de executar.")
        if not cancelar and escolhas.get("confirmar") != "sim":
            raise ValidationError("Confirme que os nomes dos lançamentos históricos também acompanharão as categorias reescritas.")
        if not cancelar and not any(escolhas.get(f"aplicar_{pk}") == "sim" for pk in op.empresas.values_list("pk", flat=True)):
            raise ValidationError("Marque ao menos uma empresa FILHO para aplicar ou encerre sem novos envios.")
        for linha in op.empresas.select_for_update():
            aplicar = not cancelar and escolhas.get(f"aplicar_{linha.pk}") == "sim"
            if aplicar and linha.status != "revisao":
                raise ValidationError("Não é possível aplicar uma empresa bloqueada ou sem prévia completa.")
            linha.status = "pronta" if aplicar else "ignorada"
            linha.mensagem = "Prévia autorizada; aguardando o worker." if aplicar else "Ignorada; nenhuma alteração autorizada."
            linha.save()
        op.pedido["etapa"] = "envio"
        op.pedido["confirmado_em"] = timezone.now().isoformat()
        op.solicitado_por = usuario
        op.status = "fila" if op.empresas.filter(status="pronta").exists() else "concluido"
        op.iniciada_em = None
        op.save()
        auditar(op.plano, usuario, "Confirmou prévia de padronização", cadastro_id=op.pk,
            empresas=list(op.empresas.values("empresa_id", "status", "passos")))
        return op


def iguais(a, b):
    return sorted(map(sem_observacoes, a), key=lambda c: c["codigo"]) == sorted(map(sem_observacoes, b), key=lambda c: c["codigo"])


def esperado_catalogo(op, linha):
    itens = {c["codigo"]: deepcopy(c) for c in op.pedido["destinos"][str(linha.empresa_id)]}
    for passo in linha.passos:
        if passo.get("status") == "sucesso":
            itens[passo["codigo"]] = passo["confirmado"]
    return list(itens.values())


def processar(op):
    from .central import conferir_operacao, conferir_sem_incerteza, progresso
    empresas = conferir_operacao(op)
    linhas = list(op.empresas.select_related("empresa"))
    ids = {l.empresa_id for l in linhas}
    if not ids or ids != set(op.pedido["destinos_ids"]) or not ids.issubset({e.pk for e in empresas} - {op.plano.matriz_id}):
        raise PermissionDenied("Os destinos não correspondem às empresas FILHO escolhidas.")
    if op.pedido["etapa"] == "envio" and not op.pedido.get("somente_ativas"):
        raise ValidationError("Esta prévia foi gerada pela regra anterior, que incluía contas inativas. Gere uma nova prévia com apenas as contas ativas da base PAI antes de enviar. Os envios já confirmados permanecem registrados.")
    if op.pedido["etapa"] == "envio" and op.pedido.get("versao_nomes") != 2:
        raise ValidationError("Esta prévia precisa ser refeita para tratar colisões de nomes. Gere outra prévia; as alterações já confirmadas permanecem registradas.")
    with aplicativo_livre(op.plano.matriz, aguardar_sincronizacao=False) as integracao:
        fonte = catalogo(op.plano.matriz, integracao)
    if op.pedido["etapa"] == "consulta":
        grupos_fonte, _ = estrutura(origem_ativa(fonte), "Base PAI — " + (op.plano.matriz.nome_fantasia or op.plano.matriz.nome))
        if not grupos_fonte:
            raise ValidationError("A matriz não possui grupos ativos de receita ou despesa para padronizar. Nenhuma alteração será enviada.")
        op.pedido.update(fonte=fonte, destinos={}, somente_ativas=True, versao_nomes=2)
        progresso(op, "Base PAI consultada; preparando a sequência por empresa.", 1)
        for linha in linhas:
            conferir_operacao(op)
            conferir_sem_incerteza(linha.empresa, linha)
            progresso(op, f"Preparando prévia de {linha.empresa.nome_fantasia or linha.empresa.nome}.")
            try:
                with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                    atual = catalogo(linha.empresa, integracao)
                op.pedido["destinos"][str(linha.empresa_id)] = atual
                linha.passos = planejar(fonte, atual,
                    empresa_pai="Base PAI — " + (op.plano.matriz.nome_fantasia or op.plano.matriz.nome),
                    empresa_filho="Base FILHO — " + (linha.empresa.nome_fantasia or linha.empresa.nome))
                linha.status, linha.mensagem = "revisao", "Prévia por posição pronta; nenhuma alteração enviada."
            except ValidationError as exc:
                linha.status, linha.mensagem = "bloqueada", " ".join(exc.messages)
                linha.passos = []
            linha.save()
            progresso(op, op.mensagem, 1)
        op.status = "revisao"
        op.save()
        progresso(op, "Confira a prévia e confirme as empresas FILHO. Apenas contas ativas da base PAI compõem a sequência, separando receitas e despesas pelos códigos OMIE.")
        return
    if op.pedido["etapa"] != "envio" or not op.pedido.get("confirmado_em"):
        raise ValidationError("Padronização sem confirmação de prévia.")
    if not iguais(origem_ativa(fonte), origem_ativa(op.pedido["fonte"])):
        raise ValidationError("A base PAI mudou após a prévia. Encerre esta solicitação e prepare outra prévia; nenhuma nova escrita foi iniciada.")
    op.status = "enviando"
    op.progresso_total = sum(len(l.passos) for l in linhas if l.status != "ignorada") or 1
    op.progresso_atual = 0
    op.save()
    for linha in linhas:
        if linha.status == "ignorada":
            continue
        try:
            conferir_operacao(op)
            conferir_sem_incerteza(linha.empresa, linha)
            if linha.status == "incerto" or any(p.get("status") in {"executando", "incerto"} for p in linha.passos):
                raise ValidationError("Verifique o envio sem confirmação antes de retomar; nenhuma escrita será repetida.")
            with aplicativo_livre(op.plano.matriz, aguardar_sincronizacao=False) as origem_integracao:
                if not iguais(origem_ativa(catalogo(op.plano.matriz, origem_integracao)), origem_ativa(op.pedido["fonte"])):
                    raise ValidationError("A base PAI mudou. Nenhuma nova escrita será enviada nesta empresa; gere outra prévia.")
            with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                atual = catalogo(linha.empresa, integracao)
                if not iguais(atual, esperado_catalogo(op, linha)):
                    raise ValidationError("O destino mudou após a prévia ou a última confirmação. Nenhuma nova escrita foi enviada nesta empresa. Encerre a solicitação e gere uma nova prévia.")
                linha.status = "executando"
                linha.save()
                for indice, passo in enumerate(linha.passos):
                    conferir_operacao(op)
                    progresso(op, f"{linha.empresa.nome_fantasia or linha.empresa.nome}: {indice+1}/{len(linha.passos)} · {passo['rotulo']} · {passo['acao']}.")
                    if passo.get("status") != "sucesso":
                        aplicar(linha, indice, integracao)
                    progresso(op, op.mensagem, 1)
                # The final complete read also catches unexpected structural changes.
                final = catalogo(linha.empresa, integracao)
                if not iguais(final, esperado_catalogo(op, linha)):
                    raise ValidationError("O cadastro mudou durante a execução. Confira a OMIE e gere outra prévia para as diferenças.")
                if any(p["acao"] != "manter" for p in planejar(fonte, final)):
                    raise ValidationError("Os códigos atribuídos pela OMIE não mantiveram a sequência prevista. Confira a ordem e gere outra prévia para ajustar; os envios já confirmados não serão repetidos.")
                linha.status, linha.mensagem = "sucesso", "Sequência confirmada na OMIE e atualizada no BI."
                linha.save()
                atualizar_vinculos(op, linha)
                auditar(op.plano, op.solicitado_por, "Concluiu padronização por posição", cadastro_id=op.pk, empresa_id=linha.empresa_id, passos=linha.passos)
        except Exception as exc:
            incerto = any(p.get("status") in {"executando", "incerto"} for p in linha.passos)
            linha.status = "incerto" if incerto else "erro"
            linha.mensagem = ("Resultado sem confirmação. Verifique sem reenviar." if incerto else
                " ".join(exc.messages) if isinstance(exc, ValidationError) else "A OMIE recusou a operação ou está indisponível. Confira antes de retomar.")
            detalhe = getattr(exc, "detalhe", "")
            if detalhe:
                linha.mensagem += "\n" + detalhe
                for passo in linha.passos:
                    if passo.get("status") in {"executando", "incerto", "erro"}:
                        passo["motivo_seguro"] = detalhe
                        break
            linha.save()
    op.status = "concluido"
    pendentes = op.empresas.exclude(status__in=["sucesso", "ignorada"]).exists()
    progresso(op, "Execução interrompida com pendências. As etapas confirmadas foram preservadas; confira o resultado por empresa antes de retomar." if pendentes else "Padronização concluída e confirmada nas empresas selecionadas.")


def atualizar_vinculos(op, linha):
    destino = op.plano.destinos.get(empresa=linha.empresa)
    por_origem = {}
    for passo in linha.passos:
        if not passo.get("excedente"):
            por_origem[passo["origem"]["codigo"]] = passo["codigo"]
    with transaction.atomic():
        VinculoCategoria.objects.filter(destino=destino).delete()
        for origem_codigo, alvo_codigo in por_origem.items():
            origem = CategoriaOmie.objects.get(empresa=op.plano.matriz, codigo=origem_codigo)
            alvo = CategoriaOmie.objects.get(empresa=linha.empresa, codigo=alvo_codigo)
            VinculoCategoria.objects.create(destino=destino, origem=origem, categoria=alvo, confirmado_por=op.solicitado_por)


def aplicar(linha, indice, integracao):
    passo = linha.passos[indice]
    esperado = deepcopy(passo["esperado"])
    referencia = passo.get("referencia")
    alvo = passo["alvo"]
    if referencia is not None:
        alvo = linha.passos[referencia]["confirmado"]
        esperado.update(codigo=alvo["codigo"], categoria_superior=alvo["categoria_superior"])
    pai_indice = passo.get("pai_indice")
    if pai_indice is not None:
        esperado["categoria_superior"] = linha.passos[pai_indice]["codigo"]
    if alvo:
        registros = omie.listar(integracao, descricao=alvo["descricao"])
        registro = next((c for c in registros if str(c.get("codigo")) == alvo["codigo"]), None)
        if not registro:
            raise ValidationError("A categoria de destino mudou. Gere outra prévia.")
        with transaction.atomic():
            _salvar_categorias(linha.empresa, [registro])
            atual = snapshot(CategoriaOmie.objects.get(empresa=linha.empresa, codigo=alvo["codigo"]))
            if sem_observacoes(atual) != sem_observacoes(alvo):
                raise ValidationError("Os dados do destino mudaram. Gere outra prévia antes de continuar.")
    if sem_observacoes(alvo) == sem_observacoes(esperado):
        passo.update(status="sucesso", codigo=alvo["codigo"], confirmado=atual)
        linha.save()
        return
    metodo = ("Alterar" if alvo else "Incluir") + ("GrupoCategoria" if passo["grupo"] else "Categoria")
    payload = {"descricao": esperado["descricao"]}
    if alvo:
        payload["codigo"] = alvo["codigo"]
    elif passo["grupo"]:
        payload["tipo_grupo"] = tipo(passo["origem"])
    else:
        payload["categoria_superior"] = esperado["categoria_superior"]
    if not passo["grupo"] and not passo.get("temporario"):
        payload.update(tipo_categoria=esperado["tipo_categoria"], codigo_dre=esperado["codigo_dre"])
        if alvo:
            payload["conta_inativa"] = "S" if esperado["conta_inativa"] else "N"
    passo.update(status="executando", metodo=metodo, parametros=payload, esperado=esperado)
    with transaction.atomic():
        linha.save()
        antigos = VinculoCategoria.objects.filter(destino__plano=linha.cadastro.plano, destino__empresa=linha.empresa)
        registros = list(antigos.values("origem_id", "categoria_id"))
        if registros:
            auditar(linha.cadastro.plano, linha.cadastro.solicitado_por, "Substituiu vínculos anteriores pela padronização", cadastro_id=linha.cadastro_id, empresa_id=linha.empresa_id, vinculos_anteriores=registros)
            antigos.delete()
    try:
        resposta = omie.chamada(integracao, metodo, payload)
    except omie.OmieRecusada:
        passo["status"] = "erro"
        linha.save()
        raise
    codigo = str(resposta.get("codigo") or "")
    if alvo and codigo != alvo["codigo"]:
        raise omie.OmieIncerta("Código retornado diferente do aprovado.")
    passo["codigo"] = codigo
    linha.save()
    confirmar_resultado(linha, indice, integracao)


def confirmar_resultado(linha, indice, integracao, codigo=""):
    passo = linha.passos[indice]
    conhecido = passo.get("codigo") or (passo.get("alvo") or {}).get("codigo")
    if conhecido and codigo and conhecido != codigo:
        raise ValidationError("O código difere da escrita originalmente enviada.")
    codigo = conhecido or codigo
    if not codigo:
        raise ValidationError("Informe o código confirmado na OMIE; a inclusão não será repetida.")
    if passo["acao"] == "criar":
        antigos = linha.cadastro.pedido["destinos"][str(linha.empresa_id)]
        if any(c["codigo"] == codigo for c in antigos) or any(p is not passo and p.get("codigo") == codigo for p in linha.passos):
            raise ValidationError("O código informado já pertence a outro cadastro da prévia. Confira a inclusão na OMIE sem reenviar.")
    esperado = {**passo["esperado"], "codigo": codigo}
    registros = omie.listar(integracao, descricao=esperado["descricao"])
    registro = next((c for c in registros if str(c.get("codigo")) == codigo), None)
    if not registro:
        raise omie.OmieIncerta("Resultado ainda não localizado na OMIE.")
    with transaction.atomic():
        _salvar_categorias(linha.empresa, [registro])
        atual = snapshot(CategoriaOmie.objects.get(empresa=linha.empresa, codigo=codigo))
        # Old uncertain writes must still verify any observation actually sent.
        comparar = (lambda c: c) if "natureza" in passo.get("parametros", {}) else sem_observacoes
        if comparar(atual) != comparar(esperado):
            raise omie.OmieIncerta("Dados diferentes da prévia autorizada.")
        passo.update(status="sucesso", codigo=codigo, confirmado=atual)
        linha.save()
