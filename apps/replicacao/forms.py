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
    nome = forms.CharField(label="Nome da configuração", max_length=120, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Padronização de categorias"}))
    matriz = EmpresaChoice(label="Base PAI", queryset=Empresa.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))
    destinos = DestinosChoice(label="Empresas FILHO disponíveis nesta configuração", queryset=Empresa.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        empresas = empresas_gerenciaveis(usuario).filter(ativa=True).order_by("nome_fantasia", "pk")
        self.fields["matriz"].queryset = empresas
        self.fields["destinos"].queryset = empresas

    def clean(self):
        dados = super().clean()
        if dados.get("matriz") and dados.get("destinos"):
            if dados["matriz"].pk in {e.pk for e in dados["destinos"]}:
                raise ValidationError("A base PAI não pode ser selecionada como empresa FILHO.")
        return dados

    def salvar(self):
        dados = self.cleaned_data
        with transaction.atomic():
            ids = [empresa.pk for empresa in dados["destinos"]]
            envolvidos = [dados["matriz"].pk, *ids]
            # Serialize only the selected participants, including their graph checks.
            list(Empresa.objects.select_for_update().filter(pk__in=envolvidos).order_by("pk").values_list("pk", flat=True))
            permitidas = empresas_gerenciaveis(self.usuario).filter(pk__in=envolvidos).count()
            if permitidas != len(envolvidos):
                raise ValidationError("Os acessos mudaram. Atualize a página e selecione as empresas novamente.")
            if DestinoReplicacao.objects.filter(plano__ativo=True, empresa_id__in=envolvidos).exists() or PlanoReplicacao.objects.filter(ativo=True, matriz_id__in=ids).exists():
                raise ValidationError("Uma empresa já participa de outro fluxo ativo. Pause o fluxo anterior; não são permitidas cadeias ou múltiplas matrizes por destino.")
            plano = PlanoReplicacao.objects.create(nome=dados["nome"], selecao_livre=True, matriz=dados["matriz"], marca=marca_host_atual(), criado_por=self.usuario)
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
    destinos = EmpresaChoice(label="Empresa FILHO que receberá o plano", queryset=Empresa.objects.none(), widget=forms.RadioSelect, empty_label=None)

    def __init__(self, *args, plano, **kwargs):
        kwargs.setdefault("auto_id", "id_padronizacao_%s")
        super().__init__(*args, **kwargs)
        self.fields["destinos"].queryset = Empresa.objects.filter(pk__in=plano.destinos.values("empresa_id"), ativa=True).order_by("nome_fantasia", "pk")

    def clean_destinos(self):
        if hasattr(self.data, "getlist") and len(self.data.getlist("destinos")) != 1:
            raise ValidationError("Escolha uma única empresa FILHO para esta padronização.")
        return self.cleaned_data["destinos"]


class ReplicarExistenteForm(forms.Form):
    destinos = DestinosChoice(label="Empresas FILHO que receberão o cadastro", queryset=Empresa.objects.none(), widget=forms.CheckboxSelectMultiple)
    incluir_filhos = forms.BooleanField(label="Incluir as categorias ativas deste grupo", required=False)
    confirmar = forms.BooleanField(label="Autorizo a consulta e a replicação nos destinos selecionados. A base PAI será somente consultada.")

    def __init__(self, *args, plano, categoria, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['destinos'].queryset=Empresa.objects.filter(pk__in=plano.destinos.values('empresa_id'),ativa=True).order_by('nome_fantasia','pk')
        if not categoria.totalizadora:
            self.fields.pop('incluir_filhos')
