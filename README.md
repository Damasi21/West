# Oeste BI

Plataforma multiempresa de Business Intelligence em Django e Bootstrap 5,
preparada para dashboards Comercial, Financeiro, Compras, Estoque e CRM.

## Primeiros passos

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse:

- Aplicação: http://127.0.0.1:8000/
- Administração: http://127.0.0.1:8000/admin/

No admin, cadastre uma empresa e vincule usuários na seção de acessos.
Administradores (`is_staff`) visualizam todas as empresas ativas; clientes
visualizam somente as empresas vinculadas ao seu usuário.

## Organização

- `apps/accounts`: login e autenticação.
- `apps/empresas`: cadastro de empresas e controle de acesso multiempresa.
- `apps/dashboards`: navegação e estrutura compartilhada dos dashboards.
- `apps/comercial`, `financeiro`, `compras`, `estoque` e `crm`: regras de cada domínio.
- `templates`: páginas e componentes visuais.
- `static/css` e `static/js`: estilos e scripts separados.

As futuras chamadas ao OMIE devem ficar em camadas de serviço, começando por
`apps/dashboards/services.py`, sem colocar credenciais ou consultas nas views.
