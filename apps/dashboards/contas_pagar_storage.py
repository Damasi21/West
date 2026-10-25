import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ContasPagarPrivateStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError("Anexos financeiros exigem acesso autenticado.")


def armazenamento_contas_pagar():
    return ContasPagarPrivateStorage(location=settings.PRIVATE_FILES_ROOT)


def caminho_anexo_conta(instance, filename):
    extensao = Path(filename).suffix.lower()
    return f"contas_pagar/{instance.conta.empresa_id}/{instance.conta_id}/{uuid.uuid4().hex}{extensao}"
