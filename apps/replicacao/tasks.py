from celery import shared_task


@shared_task(name="apps.replicacao.comparar_categorias", max_retries=0, acks_late=True)
def comparar_categorias(comparacao_id):
    from .services import executar_comparacao
    executar_comparacao(comparacao_id)


@shared_task(name="apps.replicacao.replicar_categorias", max_retries=0, acks_late=True)
def replicar_categorias(comparacao_id):
    from .services import executar_envio
    executar_envio(comparacao_id)


@shared_task(name="apps.replicacao.verificar_categoria", max_retries=0)
def verificar_categoria(item_id, usuario_id, codigo=""):
    from django.contrib.auth import get_user_model
    from apps.empresas.white_label_domains import _marca_host
    from .models import ItemReplicacao
    from .permissions import contexto_plano
    from .services import verificar_item
    item = ItemReplicacao.objects.select_related("comparacao__plano__marca").get(pk=item_id)
    usuario = get_user_model().objects.get(pk=usuario_id)
    token = contexto_plano(item.comparacao.plano)
    try:
        verificar_item(item, usuario, codigo)
    finally:
        _marca_host.reset(token)
