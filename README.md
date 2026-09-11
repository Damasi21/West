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
com os serviços `app`, `postgres` e `scheduler`. O Nginx e o Certbot ficam no
host e apontam para o app publicado em `127.0.0.1:8000`.

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

Quando houver mais de uma instalação no mesmo servidor, configure nomes
exclusivos no `.docker/.env.production` de cada projeto para evitar conflito
entre containers, imagem, rede e volume:

```env
COMPOSE_PROJECT_NAME=westwise_production
APP_IMAGE_NAME=westwise
DOCKER_NETWORK_NAME=WESTWISE_NETWORK
POSTGRES_VOLUME_NAME=WESTWISE_POSTGRES_DATA
STATIC_VOLUME_NAME=WESTWISE_STATIC
MEDIA_VOLUME_NAME=WESTWISE_MEDIA
CERTBOT_WWW_VOLUME_NAME=WESTWISE_CERTBOT_WWW
CERTBOT_CONF_VOLUME_NAME=WESTWISE_CERTBOT_CONF
APP_HOST_PORT=127.0.0.1:8001
```

## Banco de dados

O projeto usa PostgreSQL. Configure o `.env` com os dados de conexão:

```env
POSTGRES_DB=west_bi
POSTGRES_USER=west_user
POSTGRES_PASSWORD=sua-senha
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
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
