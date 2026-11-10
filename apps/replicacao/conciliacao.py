"""Conciliação por identidade, com preparação antes das inativações e sem renomear."""
from copy import deepcopy
from html import unescape

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import CategoriaOmie
from apps.empresas.omie import _salvar_categorias
from . import omie
from .plano_completo import conferir as conferir_ativo
from .comparacao import normalizar, semelhanca, tipo, sem_observacoes
from .estado import catalogo, snapshot
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa
from .padronizacao import (origem_ativa, estrutura, ordem, conferir_destino_unico,
                          iguais, esperado_catalogo, confirmar_resultado, atualizar_vinculos)
from .services import aplicativo_livre, identificar_aplicativos, auditar

VERSAO = 1


def nome(c):
    return normalizar(unescape(c["descricao"]))


def compativel(a, b):
    return (nome(a) == nome(b) and tipo(a) == tipo(b)
            and a["tipo_categoria"] == b["tipo_categoria"] and a["codigo_dre"] == b["codigo_dre"])


def opcao(valor, rotulo, alvo=None, compativel=True):
    return {"valor": valor, "rotulo": rotulo, "alvo": alvo, "compativel": compativel}


def prever(fonte, destino):
    grupos, itens = estrutura(origem_ativa(fonte), "Base PAI")
    grupos_destino, itens_destino = estrutura(destino, "Base FILHO")
    if not grupos:
        raise ValidationError("A base PAI não possui grupos ativos de receitas ou despesas.")
    linhas, candidatos_usados = [], set()
    for grupo in grupos:
        candidatos = [g for g in grupos_destino if nome(g) == nome(grupo) and tipo(g) == tipo(grupo)]
        ativos = [g for g in candidatos if not g["conta_inativa"]]
        opcoes = [opcao("usar:" + g["codigo"], f'Reaproveitar {g["codigo"]} · {unescape(g["descricao"])}', g) for g in ativos]
        if not candidatos:
            opcoes.append(opcao("criar", "Criar novo grupo com o nome do PAI"))
        opcoes.append(opcao("ignorar", "Ignorar este grupo do PAI e seus filhos"))
        gi = len(linhas)
        linhas.append({"secao": "origem", "grupo": True, "origem": grupo, "pai_indice": None,
            "situacao": "Grupo correspondente encontrado" if ativos else "Grupo de mesmo nome inativo: resolver na OMIE ou ignorar" if candidatos else "Grupo não existe no FILHO",
            "opcoes": opcoes, "escolha": "usar:" + ativos[0]["codigo"] if len(ativos) == 1 else ""})
        candidatos_usados.update(g["codigo"] for g in ativos)
        for item in sorted([c for c in itens if not c["totalizadora"] and c["categoria_superior"] == grupo["codigo"] and nome(c) != "<disponivel>"], key=ordem):
            pais = {g["codigo"] for g in ativos}
            candidatos = [c for c in itens_destino if not c["totalizadora"] and c["categoria_superior"] in pais
                and (nome(c) == nome(item) or semelhanca(unescape(c["descricao"]), unescape(item["descricao"])) >= .8)]
            candidatos.sort(key=lambda c: (not compativel(item,c), c["conta_inativa"], ordem(c)))
            opcoes = [opcao("usar:" + c["codigo"],
                f'{"Reativar" if c["conta_inativa"] else "Reaproveitar"} {c["codigo"]} · {unescape(c["descricao"])} · DRE {c["codigo_dre"] or "sem vínculo"} · tipo {c["tipo_categoria"] or "não informado"}'
                + (" · DADOS DIFERENTES: preservar dados do FILHO" if not compativel(item,c) else ""), c, compativel(item,c)) for c in candidatos]
            # Creation is checked again against the selected parent when approved.
            if not ativos or any(not any(nome(c)==nome(item) and c["categoria_superior"]==g["codigo"] for c in itens_destino if not c["totalizadora"]) for g in ativos):
                opcoes.append(opcao("criar", "Criar nova categoria com os dados do PAI"))
            opcoes.append(opcao("ignorar", "Ignorar este item do PAI"))
            exatos = [c for c in candidatos if compativel(item,c) and not c["conta_inativa"]]
            linhas.append({"secao": "origem", "grupo": False, "origem": item, "pai_indice": gi,
                "situacao": "Correspondência compatível" if len(exatos)==1 else "Decisão necessária: cadastros semelhantes, inativos ou divergentes" if candidatos else "Categoria não existe no grupo de destino",
                "opcoes": opcoes, "escolha": "usar:" + exatos[0]["codigo"] if len(exatos)==1 else "",
                "tem_divergencias": any(not o["compativel"] for o in opcoes)})
            candidatos_usados.update(c["codigo"] for c in candidatos)
    for atual in sorted(itens_destino,key=ordem):
        pode_inativar = not atual["totalizadora"] and not atual["conta_inativa"] and nome(atual)!="<disponivel>"
        opcoes = [opcao("manter", "Manter cadastro e situação atuais", atual)]
        if pode_inativar:
            opcoes.append(opcao("inativar", "Inativar somente após preparar e conferir o novo plano", atual))
        sugerida = pode_inativar and atual["codigo"] not in candidatos_usados
        linhas.append({"secao":"destino", "grupo":atual["totalizadora"], "origem":atual, "pai_indice":None,
            "situacao":"Grupo preservado; inativação de grupos não é automatizada" if atual["totalizadora"] else "Já inativa" if atual["conta_inativa"] else "Não possui correspondência sugerida no PAI: decidir manter ou inativar" if sugerida else "Pode ser usada no novo plano; não inativar se reaproveitada",
            "opcoes":opcoes, "escolha":"" if sugerida else "manter"})
    return linhas


def solicitar(plano, usuario, destinos_ids):
    conferir_ativo()
    from .central import conferir_empresas, OCUPADOS
    with transaction.atomic():
        plano=PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        conferir_empresas(plano,usuario)
        if not isinstance(destinos_ids,list) or len(destinos_ids)!=1 or type(destinos_ids[0]) is not int:
            raise ValidationError("Escolha uma única empresa FILHO para esta conciliação.")
        if not plano.destinos.filter(empresa_id=destinos_ids[0]).exists():
            raise PermissionDenied("Escolha uma empresa FILHO desta configuração.")
        if plano.cadastros.filter(status__in=OCUPADOS|{"revisao"}).exists() or plano.comparacoes.filter(status__in=["fila","comparando","enviando"]).exists():
            raise ValidationError("Conclua a solicitação atual antes de preparar outra prévia.")
        op=CadastroCategoria.objects.create(plano=plano,solicitado_por=usuario,modo="conciliacao",
            pedido={"descricao":"Conciliação do plano de categorias","etapa":"consulta","versao":VERSAO,"destinos_ids":destinos_ids},
            aplicativos=identificar_aplicativos(plano),progresso_total=2,
            mensagem="Aguardando leitura do PAI e do FILHO. Nenhuma alteração foi autorizada.")
        CadastroCategoriaEmpresa.objects.create(cadastro=op,empresa_id=destinos_ids[0])
        auditar(plano,usuario,"Solicitou conciliação sem renomear cadastros",cadastro_id=op.pk,destinos=destinos_ids)
        return op


def compilar(previa, escolhas, linha_id):
    passos, grupos, usados, origens_ativas, novos = [], {}, set(), set(), set()
    for indice, item in enumerate(previa):
        if item["secao"]!="origem":
            continue
        valor=escolhas.get(f"decisao_{linha_id}_{indice}","")
        pai=grupos.get(item["pai_indice"]) if not item["grupo"] else None
        if pai is not None and pai["acao"]=="ignorar":
            valor="ignorar"
        escolha=next((o for o in item["opcoes"] if o["valor"]==valor),None)
        if not escolha:
            raise ValidationError(f'Escolha uma ação para {unescape(item["origem"]["descricao"])}.')
        alvo=deepcopy(escolha["alvo"])
        if valor.startswith("usar:"):
            if alvo["codigo"] in usados:
                raise ValidationError("Um mesmo cadastro do FILHO não pode atender a dois itens do PAI nesta prévia.")
            if not item["grupo"] and (not pai.get("alvo") or alvo["categoria_superior"]!=pai["alvo"]["codigo"]):
                raise ValidationError("A categoria escolhida não pertence ao grupo de destino selecionado. Revise as decisões.")
            if not escolha["compativel"] and escolhas.get(f"aceitar_{linha_id}_{indice}")!="sim":
                raise ValidationError("Confirme explicitamente a divergência para reaproveitar preservando os dados do FILHO.")
            usados.add(alvo["codigo"])
        if valor=="criar" and not item["grupo"] and pai.get("alvo"):
            ocupados=[r["origem"] for r in previa if r["secao"]=="destino" and not r["grupo"] and r["origem"]["categoria_superior"]==pai["alvo"]["codigo"] and nome(r["origem"])==nome(item["origem"])]
            if ocupados:
                raise ValidationError("O nome já existe no grupo selecionado, inclusive entre inativos. Reaproveite, reative ou ignore; não será criado um duplicado.")
        esperado=deepcopy(alvo or item["origem"])
        acao="ignorar" if valor=="ignorar" else "criar" if valor=="criar" else "reativar" if alvo["conta_inativa"] else "manter"
        if acao=="criar":
            chave=(tipo(item["origem"]), "grupo" if item["grupo"] else pai["indice"], nome(item["origem"]))
            if chave in novos:
                raise ValidationError("As decisões criariam nomes duplicados no mesmo grupo. Ignore um dos itens ou revise a origem antes de enviar.")
            novos.add(chave)
        if acao=="reativar" and item["grupo"]:
            raise ValidationError("A reativação de grupos não é automatizada.")
        if acao=="criar":
            esperado.update(codigo="",natureza="",conta_inativa=False,codigo_dre="" if item["grupo"] else esperado["codigo_dre"])
            if not item["grupo"]:esperado["categoria_superior"]=""
        elif acao=="reativar":esperado["conta_inativa"]=False
        passo={"origem":deepcopy(item["origem"]),"alvo":alvo,"esperado":esperado,"acao":acao,
            "grupo":item["grupo"],"pai_indice":None if item["grupo"] else pai["indice"],"excedente":False,
            "status":"ignorada" if acao=="ignorar" else "pendente","rotulo":unescape(item["origem"]["descricao"]),
            "motivo_ignorar":"Item preservado por decisão do usuário ou grupo de origem ignorado.",
            "divergencia_aceita":not escolha["compativel"]}
        if item["grupo"]:
            grupos[indice]={**passo,"indice":len(passos)}
        elif acao!="ignorar":origens_ativas.add(tipo(item["origem"]))
        passos.append(passo)
    for indice,item in enumerate(previa):
        if item["secao"]!="destino":continue
        valor=escolhas.get(f"decisao_{linha_id}_{indice}","")
        if valor not in {o["valor"] for o in item["opcoes"]}:
            raise ValidationError(f'Decida manter ou inativar o cadastro {item["origem"]["codigo"]}.')
        if valor!="inativar":continue
        alvo=deepcopy(item["origem"])
        if alvo["codigo"] in usados:
            raise ValidationError("Uma categoria reaproveitada no novo plano não pode ser inativada.")
        if tipo(alvo) not in origens_ativas:
            raise ValidationError("Não é permitido inativar categorias sem preparar ao menos uma categoria ativa do mesmo tipo de receita/despesa.")
        passos.append({"origem":alvo,"alvo":alvo,"esperado":{**alvo,"conta_inativa":True},"acao":"inativar",
            "grupo":False,"pai_indice":None,"excedente":True,"status":"pendente","rotulo":unescape(alvo["descricao"])})
    return passos


def confirmar(op, usuario, escolhas):
    from .central import conferir_operacao, conferir_empresas, operacao_livre
    with operacao_livre(op.pk),transaction.atomic():
        PlanoReplicacao.objects.select_for_update().get(pk=op.plano_id)
        op=CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        conferir_empresas(op.plano,usuario)
        conferir_operacao(op);conferir_destino_unico(op)
        if op.modo!="conciliacao" or op.status!="revisao" or op.pedido.get("etapa")!="consulta" or op.pedido.get("versao")!=VERSAO:
            raise ValidationError("Gere uma nova prévia de conciliação para confirmar este plano.")
        if escolhas.get("confirmar")!="sim":
            raise ValidationError("Confirme as decisões e o impacto das inativações antes de enviar.")
        linha=op.empresas.select_for_update().get()
        if linha.status!="revisao":raise ValidationError("A empresa está bloqueada ou sem prévia completa.")
        op.pedido["previa_aprovada"]=deepcopy(linha.passos)
        linha.passos=compilar(linha.passos,escolhas,linha.pk)
        linha.status="pronta";linha.mensagem="Decisões aprovadas; primeiro será preparado o novo plano."
        linha.save()
        op.pedido.update(etapa="envio",confirmado_em=timezone.now().isoformat(),decisoes={k:escolhas.get(k) for k in escolhas if k.startswith(("decisao_","aceitar_"))})
        op.status="fila";op.iniciada_em=None;op.solicitado_por=usuario;op.save()
        auditar(op.plano,usuario,"Aprovou conciliação e inativações somente após preparo",cadastro_id=op.pk,passos=linha.passos)
        return op


def aplicar(linha, indice, integracao):
    conferir_ativo()
    passo=linha.passos[indice]
    if passo["acao"] not in {"manter","criar","reativar","inativar"}:
        raise ValidationError("Esta ação não faz parte da conciliação sem renomeações.")
    alvo=passo["alvo"]
    esperado=deepcopy(passo["esperado"])
    if passo["pai_indice"] is not None:
        esperado["categoria_superior"]=linha.passos[passo["pai_indice"]]["codigo"]
    if alvo:
        if passo["acao"]=="manter":
            # The full catalog was checked before this phase and is checked
            # again before any retirement. Reuse does not require a write.
            passo.update(status="sucesso",codigo=alvo["codigo"],confirmado=deepcopy(alvo))
            linha.save();return
        registro=next((c for c in omie.listar(integracao,descricao=alvo["descricao"]) if str(c.get("codigo"))==alvo["codigo"]),None)
        if not registro:raise ValidationError("O cadastro do FILHO não foi localizado. Confira a OMIE antes de continuar.")
        with transaction.atomic():
            _salvar_categorias(linha.empresa,[registro])
            atual=snapshot(CategoriaOmie.objects.get(empresa=linha.empresa,codigo=alvo["codigo"]))
        if sem_observacoes(atual)!=sem_observacoes(alvo):
            raise ValidationError("O cadastro do FILHO mudou depois da prévia. Gere outra sem repetir envios confirmados.")
    metodo=("IncluirGrupoCategoria" if passo["grupo"] else "IncluirCategoria") if passo["acao"]=="criar" else "AlterarCategoria"
    payload={"descricao":unescape(esperado["descricao"])}
    if passo["acao"]=="criar":
        if passo["grupo"]:payload["tipo_grupo"]=tipo(passo["origem"])
        else:payload.update(categoria_superior=esperado["categoria_superior"],codigo_dre=esperado["codigo_dre"],tipo_categoria=esperado["tipo_categoria"])
    else:
        payload.update(codigo=alvo["codigo"],conta_inativa="S" if passo["acao"]=="inativar" else "N")
    passo.update(status="executando",metodo=metodo,parametros=payload,esperado=esperado)
    linha.save()
    try:resposta=omie.chamada(integracao,metodo,payload)
    except omie.OmieRecusada:
        passo["status"]="erro";linha.save();raise
    codigo=str(resposta.get("codigo") or "")
    if alvo and codigo!=alvo["codigo"]:raise omie.OmieIncerta("Código retornado diferente do autorizado.")
    passo["codigo"]=codigo;linha.save()
    confirmar_resultado(linha,indice,integracao)


def processar(op):
    from .central import conferir_operacao, conferir_sem_incerteza, progresso
    conferir_operacao(op);conferir_destino_unico(op)
    if op.modo!="conciliacao" or op.pedido.get("versao")!=VERSAO:
        raise ValidationError("Esta solicitação precisa de uma nova prévia de conciliação.")
    linha=op.empresas.select_related("empresa").get()
    conferir_sem_incerteza(linha.empresa,linha)
    progresso(op,"Consultando categorias da base PAI; nenhuma alteração será enviada nesta leitura.")
    with aplicativo_livre(op.plano.matriz,aguardar_sincronizacao=False) as integracao:fonte=catalogo(op.plano.matriz,integracao)
    if op.pedido["etapa"]=="consulta":
        progresso(op,"Consultando o FILHO e preparando todas as opções de decisão.",1)
        with aplicativo_livre(linha.empresa,aguardar_sincronizacao=False) as integracao:atual=catalogo(linha.empresa,integracao)
        linha.passos=prever(fonte,atual);linha.status="revisao"
        linha.mensagem="Confira cada item do PAI e decida quais cadastros atuais manter ou inativar. Nenhuma alteração enviada."
        linha.save()
        op.pedido.update(fonte=fonte,destinos={str(linha.empresa_id):atual})
        op.status="revisao";op.save()
        progresso(op,"Prévia completa pronta. O novo plano será preparado antes das inativações aprovadas.",1)
        return
    if op.pedido["etapa"]!="envio" or not op.pedido.get("confirmado_em"):
        raise ValidationError("A conciliação ainda não foi autorizada.")
    if not iguais(origem_ativa(fonte),origem_ativa(op.pedido["fonte"])):
        raise ValidationError("A base PAI mudou após a prévia. Gere outra antes de novos envios.")
    op.status="enviando";op.progresso_total=len(linha.passos)+1;op.progresso_atual=0;op.save()
    try:
        if linha.status=="incerto" or any(p.get("status") in {"executando","incerto"} for p in linha.passos):
            raise ValidationError("Verifique o envio sem confirmação; ele não será repetido.")
        with aplicativo_livre(linha.empresa,aguardar_sincronizacao=False) as integracao:
            if not iguais(catalogo(linha.empresa,integracao),esperado_catalogo(op,linha)):
                raise ValidationError("O FILHO mudou após a prévia ou a última confirmação. Gere outra antes de novos envios.")
            linha.status="executando";linha.save()
            for indice,passo in enumerate(linha.passos):
                if passo["acao"]=="inativar":break
                conferir_operacao(op)
                progresso(op,f'Preparando novo plano · {indice+1}/{len(linha.passos)} · {passo["rotulo"]}')
                if passo["status"] not in {"sucesso","ignorada"}:aplicar(linha,indice,integracao)
                progresso(op,op.mensagem,1)
            conferir_operacao(op)
            with aplicativo_livre(op.plano.matriz,aguardar_sincronizacao=False) as origem:
                if not iguais(origem_ativa(catalogo(op.plano.matriz,origem)),origem_ativa(op.pedido["fonte"])):
                    raise ValidationError("A base PAI mudou. As inativações não serão iniciadas; confira o plano.")
            if not iguais(catalogo(linha.empresa,integracao),esperado_catalogo(op,linha)):
                raise ValidationError("O plano preparado não corresponde ao autorizado. As inativações restantes foram suspensas.")
            progresso(op,"Novo plano conferido. Iniciando somente as inativações autorizadas.",1)
            for indice,passo in enumerate(linha.passos):
                if passo["acao"]!="inativar":continue
                conferir_operacao(op)
                progresso(op,f'Inativando cadastro antigo · {passo["rotulo"]}')
                if passo["status"]!="sucesso":aplicar(linha,indice,integracao)
                progresso(op,op.mensagem,1)
            if not iguais(catalogo(linha.empresa,integracao),esperado_catalogo(op,linha)):
                raise ValidationError("O catálogo final mudou. Confira a OMIE; nenhum envio confirmado será repetido.")
        linha.status="sucesso";linha.mensagem="Conciliação concluída conforme as decisões. Nomes, classificações e histórico dos cadastros antigos foram preservados."
        linha.save();atualizar_vinculos(op,linha)
        auditar(op.plano,op.solicitado_por,"Concluiu conciliação sem renomear cadastros",cadastro_id=op.pk,passos=linha.passos)
    except Exception as exc:
        linha.status="incerto" if any(p.get("status") in {"executando","incerto"} for p in linha.passos) else "erro"
        from .falhas import registrar
        registrar(linha, exc)
    op.status="concluido";op.save()
    progresso(op,"Conciliação concluída conforme as decisões aprovadas." if linha.status=="sucesso" else "Execução interrompida com pendências. Alterações confirmadas preservadas; nenhuma repetição automática.")
