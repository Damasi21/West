from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "voce@empresa.com.br",
                "autofocus": True,
                "autocomplete": "email",
            }
        ),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Digite sua senha",
                "autocomplete": "current-password",
            }
        ),
    )
    error_messages = {
        "invalid_login": "E-mail ou senha invalidos. Tente novamente.",
        "inactive": "Esta conta esta inativa.",
    }

    def clean(self):
        email = (self.cleaned_data.get("username") or "").strip().lower()
        usuario = get_user_model().objects.filter(email__iexact=email).first()
        if usuario:
            self.cleaned_data["username"] = usuario.get_username()
        return super().clean()


class CadastroForm(UserCreationForm):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "voce@empresa.com.br",
                "autofocus": True,
                "autocomplete": "email",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Como podemos chamar voce?",
                "autocomplete": "given-name",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("email", "first_name", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "password1": "Crie uma senha segura",
            "password2": "Digite a senha novamente",
        }
        for field_name, placeholder in placeholders.items():
            self.fields[field_name].widget.attrs.update(
                {"class": "form-control", "placeholder": placeholder}
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ja existe uma conta com este e-mail.")
        return email

    def _username_from_email(self, email):
        User = get_user_model()
        base = email[:150]
        username = base
        contador = 2
        while User.objects.filter(username__iexact=username).exists():
            sufixo = f"-{contador}"
            username = f"{base[:150 - len(sufixo)]}{sufixo}"
            contador += 1
        return username

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.email = self.cleaned_data["email"]
        usuario.username = self._username_from_email(usuario.email)
        if commit:
            usuario.save()
        return usuario


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "voce@empresa.com.br",
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class PasswordResetConfirmForm(forms.Form):
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
    code = forms.CharField(
        label="Codigo",
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Digite o codigo recebido",
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
            }
        ),
    )
    password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Crie uma nova senha",
                "autocomplete": "new-password",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirmar nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Digite a senha novamente",
                "autocomplete": "new-password",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_code(self):
        return "".join(char for char in self.cleaned_data["code"] if char.isdigit())

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "As senhas nao conferem.")
        if password1:
            try:
                validate_password(password1, self.user)
            except ValidationError as erro:
                self.add_error("password1", erro)
        return cleaned
