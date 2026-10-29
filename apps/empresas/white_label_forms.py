import re
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .forms import EmpresaForm
from .models import AmbienteWhiteLabel, Empresa
from .white_label_services import empresas_vinculaveis
from .white_label_domains import normalizar_dominio


class EmpresaChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nome_fantasia or obj.nome} · {obj.cnpj}"


class AdministradorChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} · {obj.email or obj.username}"


class AmbienteWhiteLabelForm(forms.ModelForm):
    empresas = EmpresaChoiceField(label="CNPJs vinculados", queryset=Empresa.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    administradores = AdministradorChoiceField(label="Administradores White Label", queryset=get_user_model().objects.none(), required=True, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = AmbienteWhiteLabel
        fields = ("nome", "tipo", "contato_nome", "email_suporte", "telefone_suporte", "dominio", "dominio_ativo", "ativa", "empresas", "administradores")
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Grupo Horizonte"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "contato_nome": forms.TextInput(attrs={"class": "form-control"}),
            "email_suporte": forms.EmailInput(attrs={"class": "form-control"}),
            "telefone_suporte": forms.TextInput(attrs={"class": "form-control"}),
            "ativa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "dominio": forms.TextInput(attrs={"class": "form-control", "placeholder": "app.revee.elevdata.com.br", "autocapitalize": "none", "spellcheck": "false"}),
            "dominio_ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "dominio": "Somente o endereço, sem https:// ou barras. Exclusivo dos superusuários.",
            "dominio_ativo": "Ative após configurar DNS, HTTPS e o endereço permitido no servidor. Salvar não publica o domínio automaticamente.",
        }

    def __init__(self, *args, operador, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["empresas"].queryset = empresas_vinculaveis(operador).order_by("nome_fantasia", "pk")
        if operador.is_superuser:
            self.fields["administradores"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name", "username")
        else:
            for campo in ("ativa", "administradores", "dominio", "dominio_ativo"):
                self.fields.pop(campo)

    def clean_dominio(self):
        return normalizar_dominio(self.cleaned_data.get("dominio"))

    def clean(self):
        dados = super().clean()
        if dados.get("dominio_ativo") and not dados.get("dominio"):
            self.add_error("dominio", "Informe o domínio antes de ativar o acesso.")
        if not self.instance.pk and dados.get("nome"):
            base = slugify(dados["nome"])[:90] or "marca"
            identificador = base
            while AmbienteWhiteLabel.objects.filter(slug=identificador).exists():
                identificador = f"{base}-{uuid.uuid4().hex[:8]}"
            self.instance.slug = identificador
        return dados


class EmpresaWhiteLabelForm(EmpresaForm):
    def clean_cnpj(self):
        numero = re.sub(r"\D", "", super().clean_cnpj())
        existentes = Empresa.objects.values_list("cnpj", flat=True)
        if any(re.sub(r"\D", "", cnpj) == numero for cnpj in existentes):
            raise forms.ValidationError("Este CNPJ já está cadastrado. Vincule a empresa existente ao ambiente.")
        return f"{numero[:2]}.{numero[2:5]}.{numero[5:8]}/{numero[8:12]}-{numero[12:]}"
