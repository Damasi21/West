"""Replicação avulsa de cadastros existentes, sem escritas na base PAI."""
import re
from html import unescape
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from apps.empresas.models import CategoriaOmie
from .comparacao import tipo, sem_observacoes, normalizar
from .estado import snapshot
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa
from .services import identificar_aplicativos, auditar, aplicativo_livre


def validar(categoria):
    nivel = r"[12]\.\d{2}" if categoria.totalizadora else r"[12]\.\d{2}\.\d{2,3}"
    if not categoria.ativo_omie or categoria.conta_inativa or categoria.transferencia or not tipo(snapshot(categoria)) or not re.fullmatch(nivel,categoria.codigo):
        raise ValidationError("Escolha uma categoria ou grupo ativo de receita ou despesa da base PAI. As raízes e transferências não podem ser replicadas.")
    nome=unescape(categoria.descricao).strip()
    if not nome or normalizar(nome) == "<disponivel>" or len(nome)>50:
        raise ValidationError("A descrição deve estar preenchida, ter até 50 caracteres e não ser uma posição disponível.")


def filhos_ativos(categoria):
    candidatos=CategoriaOmie.objects.filter(empresa=categoria.empresa,categoria_superior=categoria.codigo,ativo_omie=True,conta_inativa=False,transferencia=False,totalizadora=False).order_by('codigo')
    return [c for c in candidatos if normalizar(unescape(c.descricao)) != '<disponivel>']


def solicitar(plano, usuario, categoria, destinos_ids, incluir_filhos=False):
    from .central import conferir_empresas, OCUPADOS
    with transaction.atomic():
        plano=PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        conferir_empresas(plano,usuario)
        if not isinstance(destinos_ids,list) or not destinos_ids or any(type(pk) is not int for pk in destinos_ids) or len(set(destinos_ids))!=len(destinos_ids):
            raise ValidationError("Selecione ao menos uma empresa FILHO, sem repetições.")
        if not set(destinos_ids).issubset(set(plano.destinos.values_list('empresa_id',flat=True))):
            raise PermissionDenied("Escolha somente empresas FILHO desta configuração.")
        if plano.cadastros.filter(status__in=OCUPADOS|{'revisao'}).exists() or plano.comparacoes.filter(status__in=['fila','comparando','enviando']).exists():
            raise ValidationError("Conclua ou cancele a solicitação atual antes de replicar outro cadastro.")
        categoria=CategoriaOmie.objects.filter(pk=categoria.pk,empresa=plano.matriz).first()
        if categoria is None:
            raise PermissionDenied('O cadastro selecionado não pertence à base PAI.')
        validar(categoria)
        if incluir_filhos and not categoria.totalizadora:
            raise ValidationError("A opção de incluir categorias está disponível somente para grupos.")
        pai=CategoriaOmie.objects.filter(empresa=plano.matriz,codigo=categoria.categoria_superior,ativo_omie=True,totalizadora=True,conta_inativa=False,transferencia=False).first()
        if not pai:
            raise ValidationError("O grupo superior não está disponível na base PAI. Atualize a árvore.")
        if not categoria.totalizadora:
            validar(pai)
            if categoria.categoria_superior != categoria.codigo.rsplit('.',1)[0] or tipo(snapshot(pai))!=tipo(snapshot(categoria)):
                raise ValidationError('A hierarquia da categoria na base PAI está inconsistente. Atualize a árvore.')
        origens=[categoria] if categoria.totalizadora else [pai,categoria]
        filhos=list(filhos_ativos(categoria)) if categoria.totalizadora and incluir_filhos else []
        for filho in filhos:validar(filho)
        origens+=filhos
        pedido={'descricao':unescape(categoria.descricao),'pai':snapshot(pai),'origem_id':categoria.pk,
            'origem_existente':True,'origens_existentes':[snapshot(c) for c in origens],
            'incluir_filhos':bool(incluir_filhos),'estrito':not categoria.totalizadora,'destinos_ids':destinos_ids}
        op=CadastroCategoria.objects.create(plano=plano,solicitado_por=usuario,modo='cadastro',pedido=pedido,
            aplicativos=identificar_aplicativos(plano),progresso_total=len(destinos_ids)*2,
            mensagem='Aguardando consulta da base PAI e dos destinos. A base PAI não será alterada.')
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op,empresa_id=pk) for pk in destinos_ids])
        auditar(plano,usuario,'Solicitou replicação de cadastro existente',cadastro_id=op.pk,pedido=pedido)
        return op


def validar_fonte(op):
    from .central import catalogo_dados
    with aplicativo_livre(op.plano.matriz,aguardar_sincronizacao=False) as integracao:
        atual=catalogo_dados(op.plano.matriz,integracao,incluir_dre=True)
    por_codigo={c['codigo']:c for c in atual}
    for origem in [op.pedido['pai'],*op.pedido['origens_existentes']]:
        if sem_observacoes(por_codigo.get(origem['codigo']))!=sem_observacoes(origem):
            raise ValidationError(f"O cadastro {unescape(origem['descricao'])} ({origem['codigo']}) mudou na base PAI. Atualize a árvore e prepare outra solicitação; envios confirmados não serão repetidos.")
    if op.pedido.get('incluir_filhos'):
        grupo=op.pedido['origens_existentes'][0]['codigo']
        filhos={c['codigo'] for c in atual if c['categoria_superior']==grupo and not c['totalizadora'] and c['ativo_omie'] and not c['conta_inativa'] and not c['transferencia'] and normalizar(unescape(c['descricao']))!='<disponivel>'}
        previstos={c['codigo'] for c in op.pedido['origens_existentes'][1:]}
        if filhos!=previstos:
            raise ValidationError('As categorias ativas do grupo mudaram na base PAI. Atualize a árvore e prepare outra solicitação.')
