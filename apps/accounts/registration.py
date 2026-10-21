import secrets
import hashlib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import EmpresaUsuario, PreCadastroUsuario
from .models import ConfirmacaoCadastro


def enviar_codigo_cadastro(email, nome):
    email = email.strip().lower()
    agora = timezone.now()
    with transaction.atomic():
        registro, _ = ConfirmacaoCadastro.objects.get_or_create(email=email, defaults={"nome": nome})
        registro = ConfirmacaoCadastro.objects.select_for_update().get(pk=registro.pk)
        if registro.enviada_em and registro.enviada_em > agora - timedelta(seconds=60):
            raise ValidationError("Aguarde um minuto antes de solicitar outro codigo.")
        if not registro.janela_envios or registro.janela_envios < agora - timedelta(hours=1):
            registro.janela_envios = agora
            registro.quantidade_envios = 0
        if registro.quantidade_envios >= 5:
            raise ValidationError("Limite de envios atingido. Tente novamente em uma hora.")
        codigo = f"{secrets.randbelow(100000000):08d}"
        registro.nome = nome
        registro.codigo_hash = make_password(codigo)
        registro.enviada_em = agora
        registro.expira_em = agora + timedelta(minutes=15)
        registro.tentativas = 0
        registro.consumida_em = None
        registro.quantidade_envios += 1
        registro.save()
    try:
        enviados = send_mail(
            "Confirme seu e-mail para acessar o BI",
            f"Seu codigo de confirmacao e: {codigo}\n\nValido por 15 minutos. Se voce nao solicitou este cadastro, ignore esta mensagem.",
            settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
        if enviados != 1:
            raise RuntimeError("Envio de confirmacao nao aceito pelo backend de e-mail.")
    except Exception:
        ConfirmacaoCadastro.objects.filter(pk=registro.pk, codigo_hash=registro.codigo_hash).update(enviada_em=None, expira_em=agora)
        raise ValidationError("Nao foi possivel enviar o e-mail. Tente novamente ou contate o administrador.")
    return registro


def _vincular_pre_cadastros(usuario):
    vinculados = 0
    for convite in PreCadastroUsuario.objects.select_for_update().filter(
        email__iexact=usuario.email.strip(), ativo=True, utilizado_em__isnull=True, empresa__ativa=True,
    ).order_by("pk"):
        # Existing access, including revoked access, is never overwritten by an invitation.
        _, criado = EmpresaUsuario.objects.get_or_create(
            empresa=convite.empresa, usuario=usuario,
            defaults={"papel": convite.papel, "ativo": True, "areas_permitidas": convite.areas_permitidas,
                      "dashboards_permitidos": convite.dashboards_permitidos},
        )
        convite.utilizado_por = usuario
        convite.utilizado_em = timezone.now()
        convite.save(update_fields=["utilizado_por", "utilizado_em"])
        vinculados += int(criado)
    return vinculados


def vincular_email_verificado(usuario):
    email = usuario.email.strip().lower()
    if not email:
        return 0
    with transaction.atomic():
        registro = ConfirmacaoCadastro.objects.select_for_update().filter(
            email=email, usuario=usuario, email_verificado_em__isnull=False,
        ).first()
        if registro is None:
            return 0
        return _vincular_pre_cadastros(usuario)


def confirmar_cadastro(registro_id, codigo, senha, usuario_logado=None):
    with transaction.atomic():
        registro = ConfirmacaoCadastro.objects.select_for_update().get(pk=registro_id)
        if registro.consumida_em or not registro.expira_em or registro.expira_em <= timezone.now() or registro.tentativas >= 5:
            return None, "Codigo invalido, expirado ou sem tentativas disponiveis. Solicite outro codigo."
        registro.tentativas += 1
        registro.save(update_fields=["tentativas"])
        if not check_password(codigo, registro.codigo_hash):
            return None, "Codigo invalido ou expirado."
        User = get_user_model()
        existentes = list(User.objects.filter(email__iexact=registro.email)[:2])
        if existentes:
            if len(existentes) != 1 or not usuario_logado or not usuario_logado.is_authenticated or existentes[0].pk != usuario_logado.pk or not existentes[0].is_active:
                return None, "Entre na sua conta existente para confirmar este e-mail. Se houver contas duplicadas, contate o administrador."
            usuario = existentes[0]
        else:
            if not senha:
                return None, "Informe uma senha para criar sua conta."
            base = registro.email if len(registro.email) <= 150 else "email-" + hashlib.sha256(registro.email.encode()).hexdigest()
            username = base
            numero = 2
            while User.objects.filter(username__iexact=username).exists():
                sufixo = f"-{numero}"
                username = base[:150 - len(sufixo)] + sufixo
                numero += 1
            usuario = User.objects.create_user(username=username, email=registro.email, first_name=registro.nome, password=senha)
        registro.usuario = usuario
        registro.email_verificado_em = timezone.now()
        registro.consumida_em = timezone.now()
        registro.save(update_fields=["usuario", "email_verificado_em", "consumida_em"])
        _vincular_pre_cadastros(usuario)
        return usuario, ""
