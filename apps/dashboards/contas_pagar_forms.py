import re
import uuid
import warnings
from decimal import Decimal
from pathlib import Path

from PIL import Image
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.empresas.models import CadastroOmie, CategoriaOmie, DepartamentoOmie, ContaCorrenteOmie
from .models import ContaPagarLocal


MAX_ANEXOS = 5
MAX_ANEXO_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024


class ValorBRField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().removeprefix("R$").strip()
            if "," in value or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
                if not re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?", value):
                    raise ValidationError("Informe um valor valido, como 1.234,56.")
                value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)


class FornecedorSelect(forms.Select):
    def use_required_attribute(self, initial):
        # The visible picker handles browser focus; the server still requires this field.
        return False


class FornecedorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        nome = obj.nome_fantasia or obj.razao_social or str(obj.codigo_cliente_omie)
        partes = [nome]
        if obj.razao_social and obj.razao_social != nome:
            partes.append(obj.razao_social)
        if obj.cnpj_cpf:
            partes.append(obj.cnpj_cpf)
        return " - ".join(partes)


class ContaPagarLocalForm(forms.ModelForm):
    token = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    fornecedor = FornecedorChoiceField(
        queryset=CadastroOmie.objects.none(), empty_label="Selecione o fornecedor",
        widget=FornecedorSelect(attrs={"hidden": True, "aria-hidden": "true", "tabindex": "-1"}),
    )
    valor = ValorBRField(label="Valor", max_digits=18, decimal_places=2, min_value=Decimal("0.01"),
                         widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00"}))
    conta_corrente = forms.ModelChoiceField(queryset=ContaCorrenteOmie.objects.none(), required=True, label="Conta corrente", empty_label="Selecione a conta corrente")

    class Meta:
        model = ContaPagarLocal
        fields = ["fornecedor", "descricao", "categoria", "departamento", "valor", "data_emissao", "data_vencimento", "data_previsao", "conta_corrente", "forma_pagamento", "documento", "observacoes"]
        labels = {"descricao": "Descricao", "categoria": "Categoria / plano de contas", "departamento": "Centro de custo", "data_emissao": "Emissao", "data_vencimento": "Vencimento", "data_previsao": "Previsao de pagamento", "forma_pagamento": "Forma de pagamento", "documento": "Documento / NF", "observacoes": "Observacoes"}
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 2, "placeholder": "Descreva a conta a pagar"}),
            "observacoes": forms.Textarea(attrs={"rows": 3, "maxlength": 5000, "placeholder": "Informacoes adicionais"}),
            "data_emissao": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "data_vencimento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "data_previsao": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "documento": forms.TextInput(attrs={"placeholder": "Ex.: NF 12345"}),
        }

    def __init__(self, *args, empresa, arquivos=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.arquivos = list(arquivos)
        if self.instance.pk:
            self.initial["token"] = self.instance.token_cadastro
        self.fields["fornecedor"].queryset = CadastroOmie.objects.filter(
            empresa=empresa, ativo_omie=True, inativo=False, tipo__in=[CadastroOmie.Tipo.FORNECEDOR, CadastroOmie.Tipo.AMBOS],
        ).order_by("razao_social", "nome_fantasia")
        self.fields["categoria"].queryset = CategoriaOmie.objects.filter(
            empresa=empresa, ativo_omie=True, conta_inativa=False, conta_despesa=True, totalizadora=False, transferencia=False,
        ).exclude(codigo__regex=r"^\d+\.\d{2}$")
        self.fields["categoria"].empty_label = "Selecione a categoria"
        self.fields["departamento"].queryset = DepartamentoOmie.objects.filter(empresa=empresa, ativo_omie=True, inativo=False)
        self.fields["departamento"].empty_label = "Selecione o centro de custo"
        self.fields["conta_corrente"].queryset = ContaCorrenteOmie.objects.filter(empresa=empresa, ativo_omie=True, inativo=False).order_by("descricao", "codigo_omie")
        self.fields["conta_corrente"].help_text = "Selecione a conta da empresa que sera vinculada ao titulo na OMIE."
        self.fields["forma_pagamento"].choices = [("", "Selecione a forma de pagamento"), *ContaPagarLocal.FormaPagamento.choices]
        if not self.instance.pk:
            self.initial.setdefault("data_emissao", timezone.localdate())
            self.initial.setdefault("data_vencimento", timezone.localdate())
        self.fields["observacoes"].max_length = 5000
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean_observacoes(self):
        valor = self.cleaned_data["observacoes"]
        if len(valor) > 5000:
            raise ValidationError("Use no maximo 5.000 caracteres nas observacoes.")
        return valor

    def clean(self):
        dados = super().clean()
        emissao, vencimento = dados.get("data_emissao"), dados.get("data_vencimento")
        dados["data_previsao"] = dados.get("data_previsao") or vencimento
        if emissao and vencimento and vencimento < emissao:
            self.add_error("data_vencimento", "O vencimento nao pode ser anterior a emissao.")
        existentes = list(self.instance.anexos.all()) if self.instance.pk else []
        if len(self.arquivos) + len(existentes) > MAX_ANEXOS:
            self.add_error(None, "Anexe no maximo 5 arquivos.")
        if sum(a.size for a in self.arquivos) + sum(a.tamanho for a in existentes) > MAX_TOTAL_BYTES:
            self.add_error(None, "Os anexos juntos nao podem ultrapassar 25 MB.")
        for arquivo in self.arquivos:
            try:
                validar_anexo(arquivo)
            except ValidationError as erro:
                self.add_error(None, erro)
        return dados


def validar_anexo(arquivo):
    extensao = Path(arquivo.name).suffix.lower()
    if extensao not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise ValidationError("Anexe somente PDF, PNG ou JPG.")
    if not 0 < arquivo.size <= MAX_ANEXO_BYTES:
        raise ValidationError("Cada anexo deve ter conteudo e no maximo 10 MB.")
    try:
        arquivo.seek(0)
        if extensao == ".pdf":
            if arquivo.read(5) != b"%PDF-":
                raise ValueError("PDF invalido")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                imagem = Image.open(arquivo)
                esperado = "PNG" if extensao == ".png" else "JPEG"
                if imagem.format != esperado:
                    raise ValueError("Formato divergente")
                imagem.verify()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError("Um dos anexos nao corresponde a um PDF ou imagem valida.")
    finally:
        arquivo.seek(0)
