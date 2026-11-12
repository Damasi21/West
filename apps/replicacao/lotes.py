"""Prévia explícita e execução avulsa de seleções de categorias."""
from copy import deepcopy
from html import unescape
import re
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from apps.empresas.models import CategoriaOmie
from apps.empresas.omie import _salvar_categorias
from . import omie
from .comparacao import normalizar, semelhanca, tipo, sem_observacoes
from .estado import snapshot, catalogo
from .models import PlanoReplicacao, CadastroCategoria, CadastroCategoriaEmpresa
from .services import aplicativo_livre, identificar_aplicativos, auditar
from .falhas import registrar
from .padronizacao import iguais, esperado_catalogo

ACOES = {'replicar', 'inativar', 'reativar'}


def nome(c):
    return normalizar(unescape(c['descricao']))


def solicitar(plano, usuario, ids, destinos, acao):
    from .central import conferir_empresas, OCUPADOS
    if acao not in ACOES:
        raise ValidationError('Escolha Replicar, Inativar ou Reativar.')
    if not ids or not destinos or any(type(pk) is not int for pk in [*ids,*destinos]) or len(ids)!=len(set(ids)) or len(destinos)!=len(set(destinos)):
        raise ValidationError('Selecione cadastros e destinos, sem repetições.')
    with transaction.atomic():
        plano=PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
        conferir_empresas(plano,usuario)
        if not set(destinos).issubset(set(plano.destinos.values_list('empresa_id',flat=True))):
            raise PermissionDenied('Escolha somente empresas FILHO deste plano.')
        if plano.cadastros.filter(status__in=OCUPADOS|{'revisao'}).exists() or plano.comparacoes.filter(status__in=['fila','comparando','enviando']).exists():
            raise ValidationError('Conclua ou cancele a solicitação atual antes de continuar.')
        selecionados=list(CategoriaOmie.objects.filter(empresa=plano.matriz,pk__in=ids).order_by('codigo'))
        if len(selecionados)!=len(ids):
            raise PermissionDenied('A seleção contém cadastros de outra base.')
        itens=[]
        for c in selecionados:
            nivel=r'[12]\.\d{2}' if c.totalizadora else r'[12]\.\d{2}\.\d{2,3}'
            if not c.ativo_omie or c.transferencia or not tipo(snapshot(c)) or not re.fullmatch(nivel,c.codigo) or nome(snapshot(c))=='<disponivel>':
                raise ValidationError('A seleção contém raízes, transferências ou cadastros indisponíveis.')
            if c.totalizadora and acao!='replicar':
                continue  # State changes apply to the selected children, never groups.
            pai=None if c.totalizadora else CategoriaOmie.objects.filter(empresa=plano.matriz,codigo=c.categoria_superior,ativo_omie=True,totalizadora=True,transferencia=False).first()
            if not c.totalizadora and not pai:
                raise ValidationError(f'O grupo superior de {unescape(c.descricao)} não está disponível na base PAI.')
            if acao=='replicar' and len(unescape(c.descricao))>50:
                raise ValidationError(f'A descrição de {unescape(c.descricao)} excede 50 caracteres.')
            itens.append({'origem':snapshot(c),'pai':snapshot(pai) if pai else None})
        if not itens:
            raise ValidationError('Selecione categorias para alterar a situação. A situação dos grupos é preservada.')
        op=CadastroCategoria.objects.create(plano=plano,solicitado_por=usuario,modo='lote',
            pedido={'versao':1,'etapa':'consulta','acao':acao,'itens':itens,'destinos_ids':destinos,
                'descricao':f'{acao.capitalize()} · {len(itens)} cadastro(s)'},
            aplicativos=identificar_aplicativos(plano),progresso_total=len(destinos)+1,
            mensagem='Na fila para preparar a conferência. Nenhum envio autorizado nesta etapa.')
        CadastroCategoriaEmpresa.objects.bulk_create([CadastroCategoriaEmpresa(cadastro=op,empresa_id=pk) for pk in destinos])
        auditar(plano,usuario,'Solicitou conferência de categorias em lote',cadastro_id=op.pk,pedido=op.pedido)
        return op


def conferir_fonte(op):
    with aplicativo_livre(op.plano.matriz,aguardar_sincronizacao=False) as integracao:
        fonte=catalogo(op.plano.matriz,integracao)
    por_codigo={c['codigo']:c for c in fonte}
    for item in op.pedido['itens']:
        for esperado in [item['origem'],item['pai']]:
            if not esperado:
                continue
            atual=por_codigo.get(esperado['codigo'])
            antes=sem_observacoes(esperado);depois=sem_observacoes(atual)
            if op.pedido['acao']!='replicar':
                antes={k:v for k,v in antes.items() if k!='conta_inativa'}
                depois={k:v for k,v in depois.items() if k!='conta_inativa'} if depois else None
            if antes!=depois:
                raise ValidationError(f"O cadastro {unescape(esperado['descricao'])} mudou na base PAI. Prepare outra conferência; envios confirmados permanecem preservados.")


def preparar(op, categorias):
    passos=[];grupos={};acao=op.pedido['acao']
    itens=sorted(op.pedido['itens'],key=lambda i:(not i['origem']['totalizadora'],i['origem']['codigo']))
    for item in itens:
        origem=item['origem'];grupo=origem['totalizadora'];pai=item['pai'];pai_alvo=None;indice_pai=None
        if pai:
            indice_pai=grupos.get(pai['codigo'])
            possiveis=[c for c in categorias if c['totalizadora'] and nome(c)==nome(pai) and tipo(c)==tipo(pai) and not c['conta_inativa'] and not c['transferencia']]
            pai_alvo=possiveis[0] if len(possiveis)==1 else None
        exatos=[c for c in categorias if nome(c)==nome(origem)]
        candidatos=[c for c in categorias if c['totalizadora']==grupo and tipo(c)==tipo(origem) and not c['transferencia'] and semelhanca(unescape(c['descricao']),unescape(origem['descricao']))>=.8]
        if pai:
            candidatos=[c for c in candidatos if pai_alvo and c['categoria_superior']==pai_alvo['codigo']]
        opcoes=[{'valor':'ignorar','rotulo':'Ignorar neste destino'}];escolha='';alvo=None
        motivo='';situacao='';tipo_acao='criar' if acao=='replicar' else acao
        if acao=='replicar':
            indisponivel=origem['conta_inativa'] or bool(pai and pai['conta_inativa'])
            if indisponivel:
                escolha='ignorar';situacao='Origem inativa';motivo='Cadastro ou grupo inativo no PAI: não será replicado.'
            elif exatos:
                escolha='ignorar';situacao='Já existe · ignorar'
                motivo='Descrição já existente no destino. Nenhum cadastro será duplicado ou renomeado.'
                compativeis=[c for c in exatos if c['totalizadora']==grupo and tipo(c)==tipo(origem) and not c['conta_inativa'] and not c['transferencia'] and (grupo or bool(pai_alvo and c['categoria_superior']==pai_alvo['codigo']))]
                alvo=compativeis[0] if len(compativeis)==1 else None
            elif pai and indice_pai is None and not pai_alvo:
                escolha='ignorar';situacao='Grupo superior indisponível';motivo='O grupo superior ativo e idêntico precisa existir no destino. Selecione também o grupo para replicá-lo.'
            else:
                similares=[c for c in categorias if c['totalizadora']==grupo and semelhanca(unescape(c['descricao']),unescape(origem['descricao']))>=.8]
                opcoes.append({'valor':'criar','rotulo':'Criar com a descrição do PAI'})
                for c in candidatos:
                    if not c['conta_inativa']:
                        opcoes.append({'valor':'usar:'+c['codigo'],'rotulo':f"Usar {c['codigo']} · {unescape(c['descricao'])} sem alterar o cadastro"})
                escolha='' if similares else 'criar'
                situacao='Nome parecido · revisar' if similares else 'Não existe · criar'
                motivo='Escolha se deseja usar um cadastro compatível, criar ou ignorar. Nenhum nome existente será alterado.' if similares else 'Inclusão proposta após sua confirmação.'
                candidatos=similares
        else:
            compativeis=[c for c in candidatos if not grupo and pai_alvo and c['categoria_superior']==pai_alvo['codigo']]
            exatos_comp=[c for c in compativeis if nome(c)==nome(origem)]
            if len(exatos_comp)==1 and exatos_comp[0]['conta_inativa']==(acao=='inativar'):
                alvo=exatos_comp[0];escolha='ignorar';situacao='Já está na situação solicitada';motivo='Nenhuma alteração necessária.'
            elif compativeis:
                for c in compativeis:
                    opcoes.append({'valor':'usar:'+c['codigo'],'rotulo':f"{acao.capitalize()} {c['codigo']} · {unescape(c['descricao'])}"})
                escolha='usar:'+exatos_comp[0]['codigo'] if len(exatos_comp)==1 else ''
                situacao='Correspondência encontrada' if escolha else 'Correspondência exige revisão'
                motivo='Somente a situação será alterada; descrição, classificação e histórico serão preservados.'
            else:
                escolha='ignorar';situacao='Sem correspondência compatível';motivo='Categoria ou grupo superior não localizado de forma compatível neste destino.'
        passo={'origem':origem,'pai':pai,'pai_alvo':pai_alvo,'pai_indice':indice_pai,'grupo':grupo,
            'acao':tipo_acao,'alvo':alvo,'opcoes':opcoes,'escolha':escolha,'situacao':situacao,'motivo_ignorar':motivo,
            'candidatos':candidatos,'status':'pendente','esperado':deepcopy(origem)}
        if grupo:
            grupos[origem['codigo']]=len(passos)
        passos.append(passo)
    return passos


def confirmar(op,usuario,escolhas):
    from .central import conferir_empresas,conferir_operacao,operacao_livre
    with operacao_livre(op.pk),transaction.atomic():
        op=CadastroCategoria.objects.select_for_update().get(pk=op.pk)
        PlanoReplicacao.objects.select_for_update().get(pk=op.plano_id)
        conferir_empresas(op.plano,usuario);conferir_operacao(op)
        if op.modo!='lote' or op.status!='revisao' or op.pedido.get('etapa')!='consulta' or escolhas.get('confirmar')!='sim':
            raise ValidationError('Conclua a conferência e confirme as decisões antes de enviar.')
        aprovados={}
        for linha in op.empresas.select_for_update():
            usados=set()
            for indice,p in enumerate(linha.passos):
                valor=escolhas.get(f'decisao_{linha.pk}_{indice}',p['escolha'])
                if valor not in {o['valor'] for o in p['opcoes']}:
                    raise ValidationError(f"Escolha uma ação para {unescape(p['origem']['descricao'])} em {linha.empresa.nome_fantasia}.")
                if valor.startswith('usar:'):
                    alvo=next((c for c in p['candidatos'] if c['codigo']==valor[5:]),None)
                    if not alvo or alvo['totalizadora']!=p['grupo'] or tipo(alvo)!=tipo(p['origem']) or alvo['transferencia'] or (op.pedido['acao']=='replicar' and alvo['conta_inativa']):
                        raise ValidationError('Correspondência incompatível com a ação solicitada.')
                    if not p['grupo'] and (not p['pai_alvo'] or alvo['categoria_superior'] != p['pai_alvo']['codigo']):
                        raise ValidationError('A categoria escolhida pertence a outro grupo no destino.')
                    if alvo['codigo'] in usados:
                        raise ValidationError('Um cadastro do destino não pode atender a duas categorias selecionadas.')
                    usados.add(alvo['codigo']);p['alvo']=alvo
                    p['acao']='manter' if op.pedido['acao']=='replicar' else op.pedido['acao']
                elif valor=='ignorar':
                    p['acao']='ignorar';p['status']='ignorada'
                    if p['alvo']:p['codigo']=p['alvo']['codigo']
                else:
                    p['acao']='criar'
                if not p['grupo'] and p['pai_indice'] is not None:
                    pai=linha.passos[p['pai_indice']]
                    if pai['acao']=='ignorar' and not pai.get('codigo'):
                        p.update(acao='ignorar',status='ignorada',motivo_ignorar='Grupo superior ignorado ou incompatível; categoria preservada sem envio.')
                p['escolha']=valor
            linha.status='pronta';linha.mensagem='Conferência aprovada. Aguardando execução.';linha.save()
            aprovados[str(linha.pk)]=deepcopy(linha.passos)
        op.pedido.update(etapa='envio',aprovado_em=timezone.now().isoformat(),decisoes=aprovados)
        op.solicitado_por=usuario;op.status='fila';op.iniciada_em=None;op.save()
        auditar(op.plano,usuario,'Aprovou seleção de categorias em lote',cadastro_id=op.pk,decisoes=aprovados)
        return op


def verificar(linha,indice,integracao,codigo=''):
    p=linha.passos[indice];conhecido=p.get('codigo') or (p.get('alvo') or {}).get('codigo')
    if conhecido and codigo and codigo!=conhecido:
        raise ValidationError('O código difere do envio original.')
    codigo=conhecido or codigo
    if not codigo:
        raise ValidationError('Informe o código confirmado na OMIE; a inclusão não será repetida.')
    if p['acao']=='criar' and any(c['codigo']==codigo for c in linha.cadastro.pedido['destinos'][str(linha.empresa_id)]):
        raise ValidationError('O código já existia antes desta inclusão. Verifique sem reenviar.')
    if p['acao']=='criar' and any(i != indice and outro.get('codigo') == codigo for i, outro in enumerate(linha.passos)):
        raise ValidationError('O código já foi utilizado em outra etapa. Verifique sem reenviar.')
    registro=next((c for c in omie.listar(integracao,descricao=p['esperado']['descricao']) if str(c.get('codigo'))==codigo),None)
    if not registro:
        raise omie.OmieIncerta(f'A categoria de código {codigo} ainda não foi localizada na OMIE. Confirmação pendente; não reenviar.')
    _salvar_categorias(linha.empresa,[registro])
    atual=snapshot(CategoriaOmie.objects.get(empresa=linha.empresa,codigo=codigo))
    esperado={**p['esperado'],'codigo':codigo}
    a,b=sem_observacoes(atual),sem_observacoes(esperado)
    a['descricao']=unescape(a['descricao']);b['descricao']=unescape(b['descricao'])
    diferentes=[k for k in b if a.get(k)!=b[k]]
    if diferentes:
        raise omie.OmieIncerta('A OMIE retornou dados divergentes em: '+', '.join(diferentes)+'. Verifique o resultado sem reenviar.')
    p.update(status='sucesso',codigo=codigo,confirmado=atual);linha.save()


def gravar(linha,indice,integracao):
    p=linha.passos[indice]
    if p['acao']=='manter':
        p.update(status='sucesso',codigo=p['alvo']['codigo'],confirmado=p['alvo']);linha.save();return
    esperado=deepcopy(p['alvo'] or p['origem'])
    if p['acao']=='criar':
        esperado.update(codigo='',natureza='',conta_inativa=False)
        payload={'descricao':unescape(esperado['descricao'])}
        if p['grupo']:
            metodo='IncluirGrupoCategoria';payload['tipo_grupo']=tipo(p['origem']);esperado['codigo_dre']=''
        else:
            pai=(linha.passos[p['pai_indice']].get('codigo') if p['pai_indice'] is not None else (p['pai_alvo'] or {}).get('codigo'))
            if not pai:
                raise ValidationError('O grupo superior não foi confirmado. Nenhuma inclusão desta categoria foi enviada.')
            esperado['categoria_superior']=pai
            metodo='IncluirCategoria';payload.update(categoria_superior=pai,tipo_categoria=esperado['tipo_categoria'],codigo_dre=esperado.get('codigo_dre',''))
    elif p['acao'] in {'inativar','reativar'}:
        atual=next((c for c in catalogo(linha.empresa,integracao) if c['codigo']==p['alvo']['codigo']),None)
        if sem_observacoes(atual)!=sem_observacoes(p['alvo']):
            raise ValidationError('O cadastro mudou após a conferência. Confira o resultado antes de preparar outra solicitação.')
        esperado['conta_inativa']=p['acao']=='inativar'
        metodo='AlterarCategoria';payload={'codigo':esperado['codigo'],'descricao':unescape(esperado['descricao']),'conta_inativa':'S' if esperado['conta_inativa'] else 'N'}
    else:
        raise ValidationError('Ação não autorizada nesta conferência.')
    p.update(status='executando',metodo=metodo,parametros=payload,esperado=esperado);linha.save()
    try:
        resposta=omie.chamada(integracao,metodo,payload)
    except omie.OmieRecusada:
        p['status']='erro';linha.save();raise
    codigo=str(resposta.get('codigo') or '')
    if p['alvo'] and codigo!=p['alvo']['codigo']:
        raise omie.OmieIncerta('Código retornado diferente do cadastro autorizado.')
    p['codigo']=codigo;linha.save();verificar(linha,indice,integracao)


def processar(op):
    from .central import conferir_operacao,conferir_sem_incerteza,progresso
    conferir_operacao(op)
    if op.pedido.get('versao')!=1 or op.pedido.get('acao') not in ACOES:
        raise ValidationError('Solicitação inválida. Prepare outra conferência.')
    linhas=list(op.empresas.select_related('empresa'))
    if {l.empresa_id for l in linhas}!=set(op.pedido['destinos_ids']) or not set(op.pedido['destinos_ids']).issubset(set(op.plano.destinos.values_list('empresa_id',flat=True))):
        raise PermissionDenied('Os destinos não pertencem ao plano selecionado.')
    conferir_fonte(op)
    if op.pedido['etapa']=='consulta':
        destinos={};progresso(op,'Consultando as bases selecionadas.',1)
        for linha in linhas:
            conferir_operacao(op);conferir_sem_incerteza(linha.empresa,linha)
            with aplicativo_livre(linha.empresa,aguardar_sincronizacao=False) as integracao:
                atual=catalogo(linha.empresa,integracao)
            destinos[str(linha.empresa_id)]=atual
            linha.passos=preparar(op,atual);linha.status='revisao';linha.mensagem='Confira as ações propostas antes de enviar.';linha.save()
            progresso(op,f'Conferência preparada para {linha.empresa.nome_fantasia}.',1)
        op.pedido['destinos']=destinos;op.status='revisao';op.save()
        progresso(op,'Conferência pronta. Nenhuma alteração enviada.');return
    if op.pedido['etapa']!='envio' or not op.pedido.get('aprovado_em'):
        raise ValidationError('Os envios ainda não foram autorizados.')
    op.status='enviando';op.progresso_total=sum(len(l.passos) for l in linhas);op.progresso_atual=0;op.save()
    for linha in linhas:
        if linha.status in {'sucesso','ignorada'}:
            progresso(op,op.mensagem,len(linha.passos));continue
        try:
            conferir_operacao(op);conferir_sem_incerteza(linha.empresa,linha);conferir_fonte(op)
            if any(p['status'] in {'executando','incerto'} for p in linha.passos):
                raise ValidationError('Há envio sem confirmação. Verifique o resultado sem reenviar.')
            with aplicativo_livre(linha.empresa,aguardar_sincronizacao=False) as integracao:
                if not iguais(catalogo(linha.empresa,integracao),esperado_catalogo(op,linha)):
                    raise ValidationError('A base FILHO mudou após a conferência. Confira os cadastros antes de preparar outra solicitação.')
                linha.status='executando';linha.save()
                for indice,p in enumerate(linha.passos):
                    conferir_operacao(op)
                    progresso(op,f"{linha.empresa.nome_fantasia} · {unescape(p['origem']['descricao'])}")
                    if p['status'] not in {'sucesso','ignorada'}:
                        gravar(linha,indice,integracao)
                    progresso(op,op.mensagem,1)
                if not iguais(catalogo(linha.empresa,integracao),esperado_catalogo(op,linha)):
                    raise ValidationError('O catálogo final divergiu das alterações confirmadas. Verifique o resultado sem repetir envios.')
            confirmados=sum(p['status']=='sucesso' for p in linha.passos)
            ignorados=sum(p['status']=='ignorada' for p in linha.passos)
            linha.status='sucesso' if confirmados else 'ignorada'
            linha.mensagem=f'Concluído: {confirmados} cadastro(s) confirmado(s), {ignorados} ignorado(s). Veja os motivos nos detalhes.'
            linha.save()
            auditar(op.plano,op.solicitado_por,'Concluiu categorias em lote',cadastro_id=op.pk,empresa_id=linha.empresa_id,passos=linha.passos)
        except Exception as erro:
            linha.status='incerto' if any(p['status'] in {'executando','incerto'} for p in linha.passos) else 'erro'
            registrar(linha,erro)
    op.status='concluido';op.save()
    progresso(op,'Execução encerrada. Confira o resultado de cada base.')
