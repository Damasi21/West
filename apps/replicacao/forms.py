from django import forms
from django.core.exceptions import ValidationError, PermissionDenied
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
    grupo = forms.ChoiceField(label="Grupo de empresas", widget=forms.Select(attrs={"class": "form-select", "data-rep-grupo": ""}))
    matriz = EmpresaChoice(label="Base matriz", queryset=Empresa.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        empresas = empresas_gerenciaveis(usuario).order_by("nome_fantasia", "pk")
        self.fields["matriz"].queryset = empresas
        grupos = {}
        for grupo in empresas.exclude(grupo="").values_list("grupo", flat=True).order_by("grupo").distinct():
            if grupo.strip():
                grupos.setdefault(grupo.casefold(), grupo)
        self.fields["grupo"].choices = [("", "Selecione o grupo"), *[(g, g) for g in grupos.values()]]
        self.mapa_empresas = [{"id": e.pk, "grupo": e.grupo, "nome": f"{e.nome_fantasia or e.nome} · {e.cnpj}"} for e in empresas if e.grupo]

    def clean(self):
        dados = super().clean()
        if dados.get("grupo") and dados.get("matriz"):
            from .central import empresas_grupo
            try:
                empresas = empresas_grupo(self.usuario, dados["grupo"])
                if dados["matriz"].pk not in {e.pk for e in empresas}:
                    raise ValidationError("Escolha uma base PAI pertencente ao grupo selecionado.")
                dados["destinos"] = [e for e in empresas if e.pk != dados["matriz"].pk]
            except (ValidationError, PermissionDenied) as erro:
                raise ValidationError(str(erro))
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
            plano = PlanoReplicacao.objects.create(nome=dados["nome"], grupo=dados["grupo"], matriz=dados["matriz"], marca=marca_host_atual(), criado_por=self.usuario)
            DestinoReplicacao.objects.bulk_create([DestinoReplicacao(plano=plano, empresa_id=pk) for pk in ids])
            conferir_acesso(plano, self.usuario)
            return plano


class NovaCategoriaForm(forms.Form):
    descricao = forms.CharField(label="Descrição da nova categoria", max_length=50, widget=forms.TextInput(attrs={"class": "form-control"}))
    pai = forms.ModelChoiceField(label="Categoria PAI / grupo superior", queryset=Empresa.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))
    destinos = DestinosChoice(label="Empresas que receberão esta categoria", queryset=Empresa.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, plano, **kwargs):
        from apps.empresas.models import CategoriaOmie
        super().__init__(*args, **kwargs)
        self.fields["pai"].queryset = CategoriaOmie.objects.filter(empresa=plano.matriz, ativo_omie=True, totalizadora=True, conta_inativa=False, transferencia=False).order_by("codigo")
        self.fields["destinos"].queryset = Empresa.objects.filter(pk__in=plano.destinos.values("empresa_id"), ativa=True).order_by("nome_fantasia", "pk")


class PadronizacaoForm(forms.Form):
    destinos = DestinosChoice(label="Empresas FILHO que receberão o plano", queryset=Empresa.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, plano, **kwargs):
        kwargs.setdefault("auto_id", "id_padronizacao_%s")
        super().__init__(*args, **kwargs)
        self.fields["destinos"].queryset = Empresa.objects.filter(pk__in=plano.destinos.values("empresa_id"), ativa=True).order_by("nome_fantasia", "pk")
