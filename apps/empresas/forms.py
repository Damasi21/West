from django import forms
from django.db.models import Max

from .models import ContaDRE, Empresa, IntegracaoOmie


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ("nome_fantasia", "nome", "cnpj", "logo", "ativa")
        widgets = {
            "nome_fantasia": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nome usado no painel"}
            ),
            "nome": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Razão social"}
            ),
            "cnpj": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "00.000.000/0000-00",
                    "data-cnpj": "",
                }
            ),
            "logo": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            "ativa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_cnpj(self):
        cnpj = self.cleaned_data["cnpj"].strip()
        numeros = "".join(caractere for caractere in cnpj if caractere.isdigit())
        if len(numeros) != 14:
            raise forms.ValidationError("Informe um CNPJ com 14 números.")
        return cnpj


class IntegracaoOmieForm(forms.Form):
    app_key = forms.CharField(
        label="App Key",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Informe a App Key da empresa",
                "autocomplete": "off",
            }
        ),
    )
    app_secret = forms.CharField(
        label="App Secret",
        max_length=255,
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Informe o App Secret",
                "autocomplete": "new-password",
            },
            render_value=False,
        ),
    )
    ativa = forms.BooleanField(
        label="Integração ativa",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.integracao = IntegracaoOmie.objects.filter(empresa=empresa).first()
        if self.integracao and not self.is_bound:
            self.initial.update(
                {
                    "app_key": self.integracao.app_key,
                    "ativa": self.integracao.ativa,
                }
            )
            self.fields["app_secret"].widget.attrs["placeholder"] = (
                "Secret já cadastrado — deixe em branco para manter"
            )

    def clean_app_secret(self):
        app_secret = self.cleaned_data["app_secret"].strip()
        if not app_secret and not self.integracao:
            raise forms.ValidationError("Informe o App Secret.")
        return app_secret

    def save(self):
        integracao = self.integracao or IntegracaoOmie(empresa=self.empresa)
        integracao.app_key = self.cleaned_data["app_key"].strip()
        integracao.ativa = self.cleaned_data["ativa"]
        if self.cleaned_data["app_secret"]:
            integracao.definir_app_secret(self.cleaned_data["app_secret"])
        integracao.save()
        return integracao


class ContaDREForm(forms.ModelForm):
    TIPO_CHOICES = (
        ("pai", "Conta pai / grupo"),
        ("filho", "Conta filho"),
    )

    tipo = forms.ChoiceField(
        label="Tipo da conta",
        choices=TIPO_CHOICES,
        widget=forms.Select(attrs={"class": "form-select", "data-dre-tipo": ""}),
    )
    conta_pai = forms.ModelChoiceField(
        label="Conta pai",
        queryset=ContaDRE.objects.none(),
        required=False,
        empty_label="Selecione o grupo pai",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = ContaDRE
        fields = ("nome", "tipo", "conta_pai", "sinal")
        widgets = {
            "nome": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: Receita operacional bruta",
                    "autofocus": True,
                }
            ),
            "sinal": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        pais = ContaDRE.objects.filter(empresa=empresa, conta_pai__isnull=True)
        if self.instance.pk:
            pais = pais.exclude(pk=self.instance.pk)
            self.initial.setdefault(
                "tipo", "filho" if self.instance.conta_pai_id else "pai"
            )
        self.fields["conta_pai"].queryset = pais

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get("tipo")
        conta_pai = cleaned_data.get("conta_pai")
        if tipo == "filho" and not conta_pai:
            self.add_error("conta_pai", "Selecione a conta pai.")
        if tipo == "pai":
            cleaned_data["conta_pai"] = None
        if (
            self.instance.pk
            and tipo == "filho"
            and self.instance.contas_filhas.exists()
        ):
            self.add_error(
                "tipo",
                "Um grupo com contas filhas não pode ser transformado em conta filha.",
            )
        return cleaned_data

    def save(self, commit=True):
        conta = super().save(commit=False)
        conta.empresa = self.empresa
        conta.conta_pai = self.cleaned_data["conta_pai"]
        if not conta.pk or "conta_pai" in self.changed_data:
            maior_ordem = (
                ContaDRE.objects.filter(
                    empresa=self.empresa,
                    conta_pai=conta.conta_pai,
                ).aggregate(Max("ordem"))["ordem__max"]
                or 0
            )
            conta.ordem = maior_ordem + 1
        if commit:
            conta.save()
        return conta
