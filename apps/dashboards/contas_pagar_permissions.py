from apps.empresas.services import usuario_gestor_empresa, usuario_pode_acessar_dashboard
from .models import ContaPagarLocal


def pode_cadastrar_conta_local(usuario, empresa):
    return usuario.is_active and usuario_pode_acessar_dashboard(usuario, empresa, "financeiro", "contas-a-pagar")


def contas_locais_visiveis(usuario, empresa):
    contas = ContaPagarLocal.objects.filter(empresa=empresa)
    if not usuario_gestor_empresa(usuario, empresa):
        contas = contas.filter(criado_por=usuario)
    return contas
