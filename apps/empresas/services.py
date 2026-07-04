from django.shortcuts import get_object_or_404

from .models import Empresa


def empresas_permitidas(usuario):
    queryset = Empresa.objects.filter(ativa=True)
    if usuario.is_superuser or usuario.is_staff:
        return queryset
    return queryset.filter(
        vinculos__usuario=usuario,
        vinculos__ativo=True,
    ).distinct()


def obter_empresa_permitida(usuario, slug):
    return get_object_or_404(empresas_permitidas(usuario), slug=slug)
