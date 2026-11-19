"""One category, chosen destinations, one explicit execution, no write replay."""
from copy import deepcopy
from hashlib import sha256
from html import unescape
import re

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.empresas.models import CategoriaOmie
from . import omie, lotes
from .comparacao import normalizar, semelhanca, tipo, sem_observacoes
from .estado import snapshot, catalogo
from .falhas import registrar
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa
from .services import aplicativo_livre, identificar_aplicativos, auditar

ACOES = {"nova", "replicar", "inativar"}


def nome(valor):
    return " ".join(re.findall(r"[a-z0-9]+", normalizar(unescape(valor))))


def distancia(a, b, limite=2):
    """Bounded Levenshtein: additions, deletions or substitutions of letters."""
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior = list(range(len(b) + 1))
    for i, letra in enumerate(a, 1):
        atual = [i]
        for j, outra in enumerate(b, 1):
            atual.append(min(atual[-1] + 1, anterior[j] + 1, anterior[j-1] + (letra != outra)))
        if min(atual) > limite:
            return limite + 1
        anterior = atual
    return anterior[-1]


def parecido(a, b):
    a, b = nome(a), nome(b)
    return bool(a and b and (a == b or distancia(a, b) <= 2 or semelhanca(a, b) >= .8))


def tipos(integracao, atualizar=False):
    chave = "rep-tipos:" + sha256(integracao.app_key.encode()).hexdigest()
    valores = None if atualizar else cache.get(chave)
    if valores is None:
        valores = omie.listar_tipos(integracao)
        cache.set(chave, valores, 3600)
    return valores


def conferir_tipo(integracao, codigo, origem):
    if codigo and not any(t['cCodigo'] == codigo and t['cTipo'] == ('R' if tipo(origem) == 'R' else 'P') for t in tipos(integracao)):
        raise ValidationError("O tipo de gasto/receita escolhido não é compatível com este grupo na OMIE.")


def grupo_valido(c):
    return bool(c and c.ativo_omie and not c.conta_inativa and c.totalizadora and not c.transferencia
                and re.fullmatch(r"[12]\.\d{2}", c.codigo) and tipo(snapshot(c)))


def solicitar(plano, usuario, acao, destinos_ids, *, categoria=None, grupo=None, descricao="", tipo_categoria=""):
    from .central import conferir_empresas, OCUPADOS
    if acao not in ACOES or not isinstance(destinos_ids, list) or not destinos_ids or any(type(pk) is not int for pk in destinos_ids) or len(set(destinos_ids)) != len(destinos_ids):
        raise ValidationError("Escolha uma função e ao menos uma base, sem repetições.")
    with transaction.atomic():
        plano = PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        empresas = conferir_empresas(plano, usuario)
        if not set(destinos_ids).issubset({e.pk for e in empresas}):
            raise PermissionDenied("Escolha apenas bases desta configuração que você pode administrar.")
        if plano.cadastros.filter(status__in=OCUPADOS | {'revisao'}).exists() or plano.comparacoes.filter(status__in=['fila', 'comparando', 'enviando']).exists():
            raise ValidationError("Aguarde ou conclua a solicitação em andamento antes de iniciar outra.")
        if acao != "nova":
            categoria = CategoriaOmie.objects.filter(pk=getattr(categoria, 'pk', None), empresa=plano.matriz).first()
            if not categoria or not categoria.ativo_omie or categoria.conta_inativa or categoria.totalizadora or categoria.transferencia or not re.fullmatch(r"[12]\.\d{2}\.\d{2,3}", categoria.codigo) or nome(categoria.descricao) == 'disponivel':
                raise ValidationError("Selecione uma única categoria ativa da base PAI.")
            origem = snapshot(categoria)
            grupo = CategoriaOmie.objects.filter(empresa=plano.matriz, codigo=categoria.categoria_superior).first()
        else:
            grupo = CategoriaOmie.objects.filter(pk=getattr(grupo, 'pk', None), empresa=plano.matriz).first()
        if not grupo_valido(grupo):
            raise ValidationError("Escolha um grupo ativo de receitas ou despesas da base PAI. Atualize as categorias se necessário.")
        if acao == "nova":
            descricao = unescape(descricao).strip()
            if not descricao or len(descricao) > 50 or len(tipo_categoria) > 3 or any(ord(c) < 32 for c in tipo_categoria):
                raise ValidationError("Informe o nome da categoria (até 50 caracteres) e um tipo válido ou deixe o tipo em branco.")
            origem = {**snapshot(grupo), 'codigo': grupo.codigo + '.000', 'descricao': descricao,
                      'categoria_superior': grupo.codigo, 'totalizadora': False, 'tipo_categoria': tipo_categoria,
                      'codigo_dre': '', 'natureza': ''}
        op = CadastroCategoria.objects.create(plano=plano, solicitado_por=usuario, modo='simples',
            pedido={'versao': 1, 'acao': acao, 'origem': origem, 'pai': snapshot(grupo),
                    'destinos_ids': destinos_ids, 'descricao': origem['descricao']},
            aplicativos=identificar_aplicativos(plano), progresso_total=len(destinos_ids),
            mensagem="Aguardando o worker para executar a réplica.")
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op, empresa_id=pk) for pk in destinos_ids])
        auditar(plano, usuario, "Solicitou réplica simples", cadastro_id=op.pk, pedido=op.pedido)
        return op


def conferir_fonte(op):
    with aplicativo_livre(op.plano.matriz, aguardar_sincronizacao=False) as integracao:
        fonte = catalogo(op.plano.matriz, integracao)
    esperados = [op.pedido['pai']]
    if op.pedido['acao'] != 'nova':
        esperados.append(op.pedido['origem'])
    for esperado in esperados:
        atual = next((c for c in fonte if c['codigo'] == esperado['codigo']), None)
        a, b = sem_observacoes(atual), sem_observacoes(esperado)
        # Inactivating the selected PAI is itself an authorized change.
        if op.pedido['acao'] == 'inativar' and atual and not esperado['totalizadora']:
            a = {k: v for k, v in a.items() if k != 'conta_inativa'}
            b = {k: v for k, v in b.items() if k != 'conta_inativa'}
        if a != b:
            raise ValidationError("A categoria ou o grupo mudou na base PAI. Atualize a seleção antes de executar novamente.")


def preparar(op, categorias):
    origem, pai = op.pedido['origem'], op.pedido['pai']
    proximas = [c for c in categorias if parecido(c['descricao'], origem['descricao'])]
    if op.pedido['acao'] != 'inativar' and proximas:
        existente = sorted(proximas, key=lambda c: (nome(c['descricao']) != nome(origem['descricao']), c['codigo']))[0]
        return None, f"Ignorada: já existe categoria igual ou semelhante ({existente['codigo']} · {unescape(existente['descricao'])}). Nenhum envio realizado."
    pais = [c for c in categorias if c['totalizadora'] and not c['transferencia'] and not c['conta_inativa']
            and tipo(c) == tipo(pai) and nome(c['descricao']) == nome(pai['descricao']) and re.fullmatch(r'[12]\.\d{2}', c['codigo'])]
    if len(pais) != 1:
        raise ValidationError("O grupo superior não existe de forma única, ativa e idêntica neste destino. Cadastre ou ajuste o grupo antes de replicar.")
    pai_alvo = pais[0]
    alvo = None
    if op.pedido['acao'] == 'inativar':
        exatas = [c for c in categorias if not c['totalizadora'] and not c['transferencia'] and tipo(c) == tipo(origem)
                  and c['categoria_superior'] == pai_alvo['codigo'] and nome(c['descricao']) == nome(origem['descricao'])]
        if len(exatas) > 1:
            raise ValidationError("Há mais de uma categoria com o mesmo nome no grupo de destino. Nenhuma inativação foi enviada.")
        if not exatas:
            return None, "Ignorada: categoria idêntica não localizada no grupo de destino. Nomes parecidos não são inativados automaticamente."
        alvo = exatas[0]
        if alvo['conta_inativa']:
            return None, f"Ignorada: {alvo['codigo']} já está inativa."
    return {'origem': deepcopy(origem), 'pai': deepcopy(pai), 'pai_alvo': pai_alvo, 'pai_indice': None,
            'grupo': False, 'acao': 'inativar' if alvo else 'criar', 'alvo': alvo, 'status': 'pendente',
            'esperado': deepcopy(origem)}, ''


def processar(op):
    from .central import conferir_operacao, conferir_sem_incerteza, progresso
    conferir_operacao(op)
    linhas = list(op.empresas.select_related('empresa'))
    permitidas = {op.plano.matriz_id, *op.plano.destinos.values_list('empresa_id', flat=True)}
    if op.pedido.get('versao') != 1 or op.pedido.get('acao') not in ACOES or not linhas or {l.empresa_id for l in linhas} != set(op.pedido['destinos_ids']) or not set(op.pedido['destinos_ids']).issubset(permitidas):
        raise ValidationError("Solicitação inválida ou destinos fora da configuração.")
    try:
        conferir_fonte(op)
    except Exception as erro:
        for linha in linhas:
            if linha.status not in {'sucesso', 'ignorada', 'incerto'} and not any(p.get('status') in {'executando', 'incerto'} for p in linha.passos):
                linha.status = 'erro'
                registrar(linha, erro)
        raise
    op.status = 'enviando'
    op.progresso_total = len(linhas)
    op.save()
    for linha in linhas:
        if linha.status in {'sucesso', 'ignorada'}:
            progresso(op, op.mensagem, 1)
            continue
        try:
            conferir_operacao(op)
            conferir_sem_incerteza(linha.empresa, linha)
            if linha.status == 'incerto' or any(p.get('status') in {'executando', 'incerto'} for p in linha.passos):
                raise ValidationError("Há um envio sem confirmação. Verifique o resultado sem reenviar.")
            progresso(op, f"Processando {linha.empresa.nome_fantasia or linha.empresa.nome}.")
            with aplicativo_livre(linha.empresa, aguardar_sincronizacao=False) as integracao:
                atual = catalogo(linha.empresa, integracao)
                passo, ignorar = preparar(op, atual)
                if ignorar:
                    linha.status, linha.mensagem = 'ignorada', ignorar
                    linha.passos = [{'origem': op.pedido['origem'], 'status': 'ignorada', 'motivo_ignorar': ignorar}]
                    linha.save()
                    continue
                if passo['acao'] == 'criar':
                    conferir_tipo(integracao, op.pedido['origem']['tipo_categoria'], op.pedido['origem'])
                op.pedido.setdefault('destinos', {})[str(linha.empresa_id)] = atual
                op.save()
                linha.passos = [passo]
                linha.status, linha.mensagem = 'executando', 'Aguardando confirmação da OMIE.'
                linha.save()
                conferir_operacao(op)
                lotes.gravar(linha, 0, integracao)
                linha.status = 'sucesso'
                linha.mensagem = ('Categoria inativada' if op.pedido['acao'] == 'inativar' else 'Categoria cadastrada') + f" com sucesso. Código {linha.passos[0]['codigo']}."
                linha.save()
                auditar(op.plano, op.solicitado_por, "Confirmou réplica simples", cadastro_id=op.pk,
                        empresa_id=linha.empresa_id, passos=linha.passos)
        except Exception as erro:
            linha.status = 'incerto' if any(p.get('status') in {'executando', 'incerto'} for p in linha.passos) else 'erro'
            registrar(linha, erro)
        finally:
            progresso(op, op.mensagem, 1)
    op.status = 'concluido'
    op.save()
    progresso(op, "Réplica finalizada. Confira o resultado e o motivo em cada base.")
