from io import BytesIO

from django import forms
from django.core.validators import RegexValidator
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps

from .models import AmbienteWhiteLabel


class LogoWhiteLabelInput(forms.ClearableFileInput):
    template_name = "empresas/widgets/logo_input.html"


class IdentidadeWhiteLabelForm(forms.ModelForm):
    class Meta:
        model = AmbienteWhiteLabel
        fields = ("layout_login", "cor_primaria", "cor_secundaria", "cor_destaque", "cor_fundo", "logo_login", "logo_navbar")
        labels = {"layout_login": "Layout do login", "cor_primaria": "Cor principal", "cor_secundaria": "Cor secundária", "cor_destaque": "Cor de destaque", "cor_fundo": "Cor de fundo (Aurora)", "logo_login": "Logo do login", "logo_navbar": "Logo da navbar"}
        widgets = {
            "layout_login": forms.RadioSelect,
            **{campo: forms.TextInput(attrs={"type":"color", "class":"wl-color-picker"}) for campo in ("cor_primaria","cor_secundaria","cor_destaque","cor_fundo")},
            **{campo: LogoWhiteLabelInput(attrs={"class":"form-control", "accept":"image/png,image/jpeg,image/webp"}) for campo in ("logo_login","logo_navbar")},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cor_fundo"].required = False
        for nome in ("cor_primaria","cor_secundaria","cor_destaque","cor_fundo"):
            self.fields[nome].validators.append(RegexValidator(r"^#[0-9a-fA-F]{6}$", "Escolha uma cor válida no formato #RRGGBB."))

    def _logo(self, nome):
        arquivo = self.cleaned_data.get(nome)
        if not arquivo or not hasattr(arquivo, "content_type"):
            return arquivo
        if arquivo.size > 3*1024*1024:
            raise forms.ValidationError("Envie uma imagem de até 3 MB.")
        try:
            arquivo.seek(0)
            with Image.open(arquivo) as imagem:
                if imagem.format not in {"PNG", "JPEG", "WEBP"}:
                    raise forms.ValidationError("Use PNG, JPG ou WebP.")
                if max(imagem.size) > 4096:
                    raise forms.ValidationError("A imagem deve ter no máximo 4096 pixels em cada lado.")
                imagem = ImageOps.exif_transpose(imagem).convert("RGBA")
                imagem.info.clear()
                saida = BytesIO()
                imagem.save(saida, format="PNG")
            return SimpleUploadedFile("logo.png", saida.getvalue(), content_type="image/png")
        except (OSError, ValueError, Image.DecompressionBombError):
            raise forms.ValidationError("Não foi possível ler a imagem. Envie um PNG, JPG ou WebP válido.")

    def clean_logo_login(self):
        return self._logo("logo_login")

    def clean_logo_navbar(self):
        return self._logo("logo_navbar")

    def clean(self):
        dados = super().clean()
        if dados.get("layout_login") == "aurora" and not dados.get("cor_fundo"):
            self.add_error("cor_fundo", "Escolha a quarta cor para o layout Aurora.")
        if dados.get("layout_login") == "classico" and not dados.get("cor_fundo"):
            dados["cor_fundo"] = self.instance.cor_fundo or "#f3f7fb"
        return dados

    def save(self, commit=True):
        self.instance.identidade_personalizada = True
        return super().save(commit=commit)
