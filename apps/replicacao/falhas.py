"""Motivos seguros e persistentes para pendências de replicação."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from . import omie


def motivo(erro):
    if isinstance(erro, (ValidationError, PermissionDenied)):
        return " ".join(erro.messages) if hasattr(erro, "messages") else str(erro)
    if isinstance(erro, (omie.OmieRecusada, omie.OmieIncerta)):
        partes = []
        codigo = str(getattr(erro, "codigo", "") or "")
        if codigo:
            partes.append(f"Código OMIE {codigo}.")
        for texto in (str(erro), getattr(erro, "detalhe", "")):
            if texto and texto not in partes:
                partes.append(texto)
        return " ".join(partes)[:2000]
    # Unknown exceptions may contain URLs, payloads or credentials.
    return "Falha interna durante o processamento. Consulte o suporte informando o número da solicitação."


def registrar(linha, erro):
    detalhe = motivo(erro)
    prefixo = ("Resultado sem confirmação. Use Verificar resultado sem reenviar." if linha.status == "incerto"
        else "A OMIE recusou a operação." if isinstance(erro, omie.OmieRecusada) else "Não foi possível concluir esta etapa.")
    linha.mensagem = f"{prefixo} {detalhe}"
    passo = next((p for p in linha.passos if p.get("status") in {"executando", "incerto", "erro"}), None)
    registro = {"tipo": type(erro).__name__, "codigo": str(getattr(erro, "codigo", "") or ""),
        "mensagem": detalhe, "em": timezone.now().isoformat()}
    if passo is not None:
        passo["erro"] = registro
        passo["motivo_seguro"] = detalhe
    linha.save()
    from .services import auditar
    auditar(linha.cadastro.plano, linha.cadastro.solicitado_por, "Registrou pendência de replicação",
        cadastro_id=linha.cadastro_id, empresa_id=linha.empresa_id,
        categoria=(passo or {}).get("origem", {}).get("descricao", linha.cadastro.pedido.get("descricao", "")), erro=registro)


def pendencias(op, linhas):
    resultado = []
    for linha in linhas:
        if linha.status not in {"erro", "incerto", "bloqueada", "revisao"}:
            continue
        passos = [p for p in linha.passos if p.get("status") in {"erro", "executando", "incerto"}]
        for passo in passos or [None]:
            erro = (passo or {}).get("erro") or {}
            resultado.append({"empresa": linha.empresa.nome_fantasia or linha.empresa.nome,
                "categoria": (passo or {}).get("origem", {}).get("descricao") or op.pedido.get("descricao", ""),
                "codigo": (passo or {}).get("codigo") or ((passo or {}).get("alvo") or {}).get("codigo", ""),
                "metodo": (passo or {}).get("metodo", ""), "status": linha.get_status_display(),
                "mensagem": linha.mensagem, "detalhe": erro.get("mensagem") or (passo or {}).get("motivo_seguro", "")})
    if not resultado and op.status == "erro":
        resultado.append({"empresa": "Solicitação", "categoria": op.pedido.get("descricao", ""),
            "mensagem": op.mensagem, "codigo": "", "metodo": "", "status": op.get_status_display(), "detalhe": ""})
    return resultado
