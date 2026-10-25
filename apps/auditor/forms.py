from django import forms
from .catalogo import PARAMETROS
from .models import CasoAuditoria, PoliticaAuditoria


class PoliticaForm(forms.Form):
    ativa = forms.BooleanField(required=False, label="Ativa")
    severidade = forms.ChoiceField(choices=PoliticaAuditoria.Severidade.choices, label="Severidade")
    amostras_minimas = forms.IntegerField(min_value=3, max_value=1000, label="Amostras minimas")
    multiplicador_valor = forms.DecimalField(min_value=1.5, max_value=100, decimal_places=2, label="Multiplicador da mediana")
    janela_dias = forms.IntegerField(min_value=7, max_value=1825, label="Janela historica (dias)")

    def __init__(self, *args, politica, **kwargs):
        super().__init__(*args, initial={"ativa": politica.ativa, "severidade": politica.severidade,
                                        **PARAMETROS, **politica.parametros}, **kwargs)
        if politica.codigo not in {"valor_atipico", "categoria_atipica"}:
            for nome in PARAMETROS:
                self.fields.pop(nome)
        elif politica.codigo == "categoria_atipica":
            self.fields.pop("multiplicador_valor")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field, forms.BooleanField) else "form-select" if isinstance(field, forms.ChoiceField) else "form-control"


class TratamentoForm(forms.Form):
    status = forms.ChoiceField(choices=CasoAuditoria.Status.choices, label="Tratamento")
    responsavel = forms.ModelChoiceField(queryset=None, required=False, label="Responsavel")
    comentario = forms.CharField(max_length=4000, label="Registro da analise", widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, caso, usuarios, **kwargs):
        super().__init__(*args, initial={"status": caso.status, "responsavel": caso.responsavel_id}, **kwargs)
        self.fields["responsavel"].queryset = usuarios
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo, forms.ChoiceField) else "form-control"
