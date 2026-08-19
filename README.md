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

## Deploy com Docker

O projeto possui uma stack de produção em `.docker/docker-compose.production.yaml`
com os serviços `app`, `postgres`, `proxy`, `certbot` e `scheduler`.

O serviço `scheduler` mantém a sincronização automática da OMIE ativa, executando
continuamente:

```bash
python manage.py monitorar_sincronizacoes_agendadas
```

Para preparar um servidor, crie `.docker/.env.production` a partir de
`.docker/.env.example`, ajuste domínio, segredos e banco, e execute:

```bash
chmod +x .docker/scripts/*.sh
./.docker/scripts/install.sh
```

## Banco de dados

Por padrão, o projeto usa SQLite (`db.sqlite3`). Para usar PostgreSQL,
configure o `.env`:

```env
DATABASE_ENGINE=postgres
POSTGRES_DB=west_bi
POSTGRES_USER=west_user
POSTGRES_PASSWORD=sua-senha
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Para migrar os dados locais do SQLite para PostgreSQL:

```powershell
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission --indent 2 -o backup_sqlite_YYYYMMDD.json
python manage.py migrate
python manage.py loaddata backup_sqlite_YYYYMMDD.json
```

## Organização

- `apps/accounts`: login e autenticação.
- `apps/empresas`: cadastro de empresas e controle de acesso multiempresa.
- `apps/dashboards`: navegação e estrutura compartilhada dos dashboards.
- `apps/comercial`, `financeiro`, `compras`, `estoque` e `crm`: regras de cada domínio.
- `templates`: páginas e componentes visuais.
- `static/css` e `static/js`: estilos e scripts separados.

As futuras chamadas ao OMIE devem ficar em camadas de serviço, começando por
`apps/dashboards/services.py`, sem colocar credenciais ou consultas nas views.
