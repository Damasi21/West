import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .forms import EmpresaForm
from .models import AmbienteWhiteLabel, Empresa
from .white_label_services import empresas_vinculaveis


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
        fields = ("nome", "slug", "tipo", "contato_nome", "email_suporte", "telefone_suporte", "ativa", "empresas", "administradores")
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Grupo Horizonte"}),
            "slug": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: grupo-horizonte"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "contato_nome": forms.TextInput(attrs={"class": "form-control"}),
            "email_suporte": forms.EmailInput(attrs={"class": "form-control"}),
            "telefone_suporte": forms.TextInput(attrs={"class": "form-control"}),
            "ativa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, operador, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["empresas"].queryset = empresas_vinculaveis(operador).order_by("nome_fantasia", "pk")
        self.fields["slug"].help_text = "Identificador interno. O domínio e o subdomínio serão configurados em outra etapa."
        if operador.is_superuser:
            self.fields["administradores"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name", "username")
        else:
            for campo in ("slug", "ativa", "administradores"):
                self.fields.pop(campo)

    def clean_slug(self):
        valor = self.cleaned_data["slug"].strip()
        if valor != slugify(valor):
            raise forms.ValidationError("Use apenas letras minúsculas, números e hífens.")
        return valor


class EmpresaWhiteLabelForm(EmpresaForm):
    def clean_cnpj(self):
        numero = re.sub(r"\D", "", super().clean_cnpj())
        existentes = Empresa.objects.values_list("cnpj", flat=True)
        if any(re.sub(r"\D", "", cnpj) == numero for cnpj in existentes):
            raise forms.ValidationError("Este CNPJ já está cadastrado. Vincule a empresa existente ao ambiente.")
        return f"{numero[:2]}.{numero[2:5]}.{numero[5:8]}/{numero[8:12]}-{numero[12:]}"
