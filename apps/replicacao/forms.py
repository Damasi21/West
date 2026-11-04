from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.empresas.models import Empresa
from apps.empresas.white_label_domains import marca_host_atual
from .models import PlanoReplicacao, DestinoReplicacao
from .permissions import empresas_gerenciaveis, conferir_acesso


class EmpresaChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nome_fantasia or obj.nome} · {obj.cnpj}"


class DestinosChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nome_fantasia or obj.nome} · {obj.cnpj}"


class PlanoForm(forms.Form):
    nome = forms.CharField(label="Nome da configuração", max_length=120, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Padronização financeira — Grupo REVEE"}))
    matriz = EmpresaChoice(label="Base matriz", queryset=Empresa.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))
    destinos = DestinosChoice(label="Empresas destinatárias", queryset=Empresa.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        empresas = empresas_gerenciaveis(usuario).order_by("nome_fantasia", "pk")
        self.fields["matriz"].queryset = empresas
        self.fields["destinos"].queryset = empresas

    def clean(self):
        dados = super().clean()
        if dados.get("matriz") and dados.get("destinos") is not None and dados["destinos"].filter(pk=dados["matriz"].pk).exists():
            self.add_error("destinos", "A matriz não pode ser seu próprio destino.")
        return dados

    def salvar(self):
        dados = self.cleaned_data
        with transaction.atomic():
            # Serialize changes to the replication graph. No financial data locks.
            list(Empresa.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
            ids = [empresa.pk for empresa in dados["destinos"]]
            envolvidos = [dados["matriz"].pk, *ids]
            permitidas = empresas_gerenciaveis(self.usuario).filter(pk__in=envolvidos).count()
            if permitidas != len(envolvidos):
                raise ValidationError("Os acessos mudaram. Atualize a página e selecione as empresas novamente.")
            if DestinoReplicacao.objects.filter(plano__ativo=True, empresa_id__in=envolvidos).exists() or PlanoReplicacao.objects.filter(ativo=True, matriz_id__in=ids).exists():
                raise ValidationError("Uma empresa já participa de outro fluxo ativo. Pause o fluxo anterior; não são permitidas cadeias ou múltiplas matrizes por destino.")
            plano = PlanoReplicacao.objects.create(nome=dados["nome"], matriz=dados["matriz"], marca=marca_host_atual(), criado_por=self.usuario)
            DestinoReplicacao.objects.bulk_create([DestinoReplicacao(plano=plano, empresa_id=pk) for pk in ids])
            conferir_acesso(plano, self.usuario)
            return plano
