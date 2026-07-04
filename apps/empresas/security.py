import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    segredo = settings.OMIE_CREDENTIALS_ENCRYPTION_KEY.encode("utf-8")
    chave = base64.urlsafe_b64encode(hashlib.sha256(segredo).digest())
    return Fernet(chave)


def criptografar_credencial(valor):
    return _fernet().encrypt(valor.encode("utf-8")).decode("ascii")


def descriptografar_credencial(valor):
    return _fernet().decrypt(valor.encode("ascii")).decode("utf-8")
