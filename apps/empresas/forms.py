from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Max

from .models import (
    AgendamentoSincronizacaoOmie,
    ContaDRE,
    Empresa,
    EmpresaUsuario,
    IntegracaoOmie,
    SincronizacaoOmie,
)
from .services import usuario_pode_gerenciar_vinculo


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ("nome_fantasia", "nome", "cnpj", "grupo", "logo", "ativa")
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
            "grupo": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex.: Grupo Oeste"}
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


class TrialCadastroForm(forms.Form):
    nome_empresa = forms.CharField(
        label="Empresa",
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Nome fantasia da empresa",
                "autocomplete": "organization",
            }
        ),
    )
    razao_social = forms.CharField(
        label="Razao social",
        max_length=180,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Opcional",
                "autocomplete": "organization-title",
            }
        ),
    )
    cnpj = forms.CharField(
        label="CNPJ",
        max_length=18,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "00.000.000/0000-00",
                "inputmode": "numeric",
            }
        ),
    )
    responsavel = forms.CharField(
        label="Responsavel",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Nome de quem vai acessar",
                "autocomplete": "name",
            }
        ),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "voce@empresa.com.br",
                "autocomplete": "email",
            }
        ),
    )
    telefone = forms.CharField(
        label="Telefone",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "(00) 00000-0000",
                "autocomplete": "tel",
            }
        ),
    )
    app_key = forms.CharField(
        label="App Key OMIE",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "App Key da OMIE",
                "autocomplete": "off",
            }
        ),
    )
    app_secret = forms.CharField(
        label="App Secret OMIE",
        max_length=255,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "App Secret da OMIE",
                "autocomplete": "new-password",
            }
        ),
    )
    password = forms.CharField(
        label="Senha de acesso",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Crie uma senha segura",
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_cnpj(self):
        cnpj = self.cleaned_data["cnpj"].strip()
        numeros = "".join(caractere for caractere in cnpj if caractere.isdigit())
        if len(numeros) != 14:
            raise forms.ValidationError("Informe um CNPJ com 14 numeros.")
        if Empresa.objects.filter(cnpj__in={cnpj, numeros}).exists():
            raise forms.ValidationError("Ja existe uma empresa cadastrada com este CNPJ.")
        return cnpj

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ja existe uma conta com este e-mail.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def username_from_email(self):
        User = get_user_model()
        base = self.cleaned_data["email"][:150]
        username = base
        contador = 2
        while User.objects.filter(username__iexact=username).exists():
            sufixo = f"-{contador}"
            username = f"{base[:150 - len(sufixo)]}{sufixo}"
            contador += 1
        return username


class AgendamentoSincronizacaoOmieForm(forms.ModelForm):
    MAX_HORARIOS = AgendamentoSincronizacaoOmie.MAX_HORARIOS
    dias_semana = forms.MultipleChoiceField(
        label="Dias da semana",
        required=False,
        choices=[
            (str(valor), rotulo)
            for valor, rotulo in AgendamentoSincronizacaoOmie.DIAS_SEMANA
        ],
        widget=forms.SelectMultiple(
            attrs={
                "class": "sync-native-weekday-select",
                "size": 4,
            }
        ),
    )

    class Meta:
        model = AgendamentoSincronizacaoOmie
        fields = ("ativo", "tipo_agendamento", "dias_semana")
        widgets = {
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "tipo_agendamento": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, empresa, usuario=None, **kwargs):
        self.empresa = empresa
        self.usuario = usuario
        instance = kwargs.get("instance")
        super().__init__(*args, **kwargs)
        for indice in range(1, self.MAX_HORARIOS + 1):
            self.fields[f"horario_{indice}"] = forms.TimeField(
                label=f"Horario {indice}",
                required=False,
                widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            )
            self.fields[f"recurso_{indice}"] = forms.ChoiceField(
                label="Modulo",
                required=False,
                choices=SincronizacaoOmie.Recurso.choices,
                initial=SincronizacaoOmie.Recurso.COMPLETA,
                widget=forms.Select(attrs={"class": "form-select"}),
            )
            self.fields[f"periodo_{indice}"] = forms.ChoiceField(
                label="Periodo",
                required=False,
                choices=SincronizacaoOmie.Periodo.choices,
                initial=SincronizacaoOmie.Periodo.TUDO,
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        if not self.is_bound and instance:
            self.initial["dias_semana"] = [
                str(dia) for dia in instance.dias_semana or []
            ]
            for indice, item in enumerate(instance.horarios_configurados, start=1):
                self.initial[f"horario_{indice}"] = item["horario"]
                self.initial[f"recurso_{indice}"] = item["recurso"]
                self.initial[f"periodo_{indice}"] = item["periodo"]

    def clean_dias_semana(self):
        return [int(dia) for dia in self.cleaned_data.get("dias_semana", [])]

    def clean(self):
        cleaned = super().clean()
        horarios = []
        horarios_informados = set()
        for indice in range(1, self.MAX_HORARIOS + 1):
            horario = cleaned.get(f"horario_{indice}")
            if horario:
                valor = horario.strftime("%H:%M")
                if valor in horarios_informados:
                    self.add_error(
                        f"horario_{indice}",
                        "Ja existe uma sincronizacao neste horario.",
                    )
                    continue
                horarios_informados.add(valor)
                horarios.append(
                    {
                        "horario": valor,
                        "recurso": cleaned.get(f"recurso_{indice}")
                        or SincronizacaoOmie.Recurso.COMPLETA,
                        "periodo": cleaned.get(f"periodo_{indice}")
                        or SincronizacaoOmie.Periodo.TUDO,
                    }
                )
        cleaned["horarios"] = horarios

        ativo = cleaned.get("ativo")
        tipo = cleaned.get("tipo_agendamento")
        if ativo and not horarios:
            raise forms.ValidationError("Informe ao menos um horario de sincronizacao.")
        if len(horarios) > self.MAX_HORARIOS:
            raise forms.ValidationError("Informe no maximo 5 horarios por dia.")
        if tipo == AgendamentoSincronizacaoOmie.Tipo.DIAS_SEMANA and not cleaned.get(
            "dias_semana"
        ):
            self.add_error("dias_semana", "Selecione ao menos um dia da semana.")
        cleaned["dia_mes"] = None
        if tipo != AgendamentoSincronizacaoOmie.Tipo.DIAS_SEMANA:
            cleaned["dias_semana"] = []
        self.instance.horarios = horarios
        self.instance.dias_semana = cleaned.get("dias_semana", [])
        self.instance.dia_mes = cleaned.get("dia_mes")
        return cleaned

    def save(self, commit=True):
        agendamento = super().save(commit=False)
        agendamento.empresa = self.empresa
        agendamento.horarios = self.cleaned_data["horarios"]
        agendamento.dias_semana = self.cleaned_data.get("dias_semana", [])
        agendamento.atualizado_por = self.usuario
        if commit:
            agendamento.full_clean()
            agendamento.save()
        return agendamento


class EmpresaUsuarioForm(forms.Form):
    vinculo_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    username = forms.CharField(
        label="Usuário",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        label="Senha inicial",
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "new-password"}
        ),
    )
    papel = forms.ChoiceField(
        label="Perfil",
        choices=EmpresaUsuario.Papel.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    areas_permitidas = forms.MultipleChoiceField(
        label="Módulos",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    dashboards_permitidos = forms.MultipleChoiceField(
        label="Dashboards",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    ativo = forms.BooleanField(
        label="Acesso ativo",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, empresa, operador, areas, vinculo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.operador = operador
        self.vinculo = vinculo
        self.fields["areas_permitidas"].choices = [
            (slug, area["titulo"]) for slug, area in areas.items()
        ]
        self.fields["dashboards_permitidos"].choices = [
            (f"{area_slug}:{dashboard['slug']}", f"{area['titulo']} - {dashboard['titulo']}")
            for area_slug, area in areas.items()
            for dashboard in area["dashboards"]
        ]
        if vinculo and not self.is_bound:
            usuario = vinculo.usuario
            self.initial.update(
                {
                    "vinculo_id": vinculo.pk,
                    "username": usuario.username,
                    "first_name": usuario.first_name,
                    "last_name": usuario.last_name,
                    "email": usuario.email,
                    "papel": vinculo.papel,
                    "areas_permitidas": vinculo.areas_permitidas,
                    "dashboards_permitidos": vinculo.dashboards_permitidos,
                    "ativo": vinculo.ativo,
                }
            )
            self.fields["password"].help_text = "Deixe em branco para manter a senha."

        if not operador.is_superuser and not operador.is_staff:
            operador_vinculo = EmpresaUsuario.objects.filter(
                empresa=empresa,
                usuario=operador,
                ativo=True,
            ).first()
            if operador_vinculo and operador_vinculo.papel == EmpresaUsuario.Papel.GESTOR:
                self.fields["papel"].choices = [
                    (EmpresaUsuario.Papel.VISUALIZADOR, "Visualizador")
                ]

    def clean(self):
        cleaned = super().clean()
        vinculo = self.vinculo
        vinculo_id = cleaned.get("vinculo_id")
        if vinculo_id and not vinculo:
            vinculo = EmpresaUsuario.objects.filter(
                pk=vinculo_id,
                empresa=self.empresa,
            ).select_related("usuario").first()
            if not vinculo:
                raise forms.ValidationError("Acesso não encontrado.")
            self.vinculo = vinculo

        if vinculo and not usuario_pode_gerenciar_vinculo(
            self.operador,
            self.empresa,
            vinculo,
        ):
            raise forms.ValidationError("Você não pode alterar este usuário.")

        papel = cleaned.get("papel")
        if not self.operador.is_superuser and not self.operador.is_staff:
            operador_vinculo = EmpresaUsuario.objects.filter(
                empresa=self.empresa,
                usuario=self.operador,
                ativo=True,
            ).first()
            if operador_vinculo and operador_vinculo.papel == EmpresaUsuario.Papel.GESTOR:
                if papel != EmpresaUsuario.Papel.VISUALIZADOR:
                    raise forms.ValidationError("Gerentes só podem cadastrar usuários.")

        username = (cleaned.get("username") or "").strip()
        if not username:
            return cleaned
        usuario_existente = get_user_model().objects.filter(username=username).first()
        if usuario_existente and (
            not self.vinculo or usuario_existente != self.vinculo.usuario
        ):
            if EmpresaUsuario.objects.filter(
                empresa=self.empresa,
                usuario=usuario_existente,
            ).exists():
                raise forms.ValidationError("Este usuário já está vinculado à empresa.")
        if not self.vinculo and not cleaned.get("password") and not usuario_existente:
            self.add_error("password", "Informe uma senha inicial para novo usuário.")
        return cleaned

    def save(self):
        User = get_user_model()
        username = self.cleaned_data["username"].strip()
        usuario = self.vinculo.usuario if self.vinculo else User.objects.filter(username=username).first()
        if usuario is None:
            usuario = User(username=username)
        usuario.username = username
        usuario.first_name = self.cleaned_data.get("first_name", "").strip()
        usuario.last_name = self.cleaned_data.get("last_name", "").strip()
        usuario.email = self.cleaned_data.get("email", "").strip()
        if self.cleaned_data.get("password"):
            usuario.set_password(self.cleaned_data["password"])
        usuario.save()

        vinculo = self.vinculo or EmpresaUsuario(empresa=self.empresa, usuario=usuario)
        vinculo.papel = self.cleaned_data["papel"]
        vinculo.areas_permitidas = self.cleaned_data.get("areas_permitidas", [])
        vinculo.dashboards_permitidos = self.cleaned_data.get("dashboards_permitidos", [])
        vinculo.ativo = self.cleaned_data.get("ativo", False)
        vinculo.save()
        return vinculo


class ContaDREForm(forms.ModelForm):
    TIPO_CHOICES = (
        ("pai", "Conta pai / grupo"),
        ("filho", "Conta filho"),
        ("resultado", "Conta de resultado"),
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
        pais = ContaDRE.objects.filter(
            empresa=empresa,
            conta_pai__isnull=True,
        ).exclude(sinal=ContaDRE.Sinal.RESULTADO)
        if self.instance.pk:
            pais = pais.exclude(pk=self.instance.pk)
            tipo_inicial = "pai"
            if self.instance.conta_pai_id:
                tipo_inicial = "filho"
            elif self.instance.eh_resultado:
                tipo_inicial = "resultado"
            self.initial.setdefault("tipo", tipo_inicial)
        self.fields["conta_pai"].queryset = pais

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get("tipo")
        conta_pai = cleaned_data.get("conta_pai")
        if tipo == "filho" and not conta_pai:
            self.add_error("conta_pai", "Selecione a conta pai.")
        if tipo == "filho" and conta_pai and conta_pai.eh_resultado:
            self.add_error(
                "conta_pai",
                "Contas de resultado nao podem receber contas filhas.",
            )
        if tipo in {"pai", "resultado"}:
            cleaned_data["conta_pai"] = None
        if (
            self.instance.pk
            and tipo in {"filho", "resultado"}
            and self.instance.contas_filhas.exists()
        ):
            self.add_error(
                "tipo",
                "Um grupo com contas filhas nao pode ser transformado neste tipo.",
            )
        if tipo == "resultado":
            cleaned_data["sinal"] = ContaDRE.Sinal.RESULTADO
        elif cleaned_data.get("sinal") == ContaDRE.Sinal.RESULTADO:
            self.add_error(
                "sinal",
                "Use o tipo Conta de resultado para linhas calculadas.",
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
