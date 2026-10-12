from django.db.models.signals import post_save
from django.dispatch import receiver

from .cfops import criar_cfops_padrao
from .models import Empresa


@receiver(post_save, sender=Empresa, dispatch_uid="empresas.cfops_venda_padrao")
def preencher_cfops_nova_empresa(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        criar_cfops_padrao(instance)
