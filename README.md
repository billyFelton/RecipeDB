# Recipe Platform — Docker Compose (Database Layer)

## Directory layout

```
.
├── docker-compose.yml
├── .env.example          # copy to .env and fill in secrets
├── migrations/
│   └── 001_initial_schema.sql   # auto-applied on first container start
├── backups/              # pg_dump output (prod profile)
├── pgadmin/
│   └── servers.json      # auto-registers db in PgAdmin (dev profile)
└── scripts/
    └── backup.sh         # daily dump script used by backup sidecar
```

## First-time setup

```bash
# 1. Copy and edit the env file
cp .env.example .env
vi .env   # set strong passwords

# 2. Place your migration file
cp 001_initial_schema.sql migrations/

# 3. Start development stack (Postgres + Redis + PgAdmin)
docker compose --profile dev up -d

# 4. Confirm health
docker compose ps
docker compose logs db
```

## Profiles

| Profile | Services started            | Use case              |
|---------|-----------------------------|-----------------------|
| (none)  | db, redis                   | CI / minimal          |
| dev     | db, redis, pgadmin          | Local development     |
| prod    | db, redis, backup sidecar   | Production deployment |

```bash
# Dev
docker compose --profile dev up -d

# Prod
docker compose --profile prod up -d
```

## Useful commands

```bash
# Open a psql shell
docker exec -it recipedb_postgres psql -U recipeapp -d recipedb

# Run a migration manually
docker exec -i recipedb_postgres psql -U recipeapp -d recipedb < migrations/002_next.sql

# Trigger a manual backup (prod profile)
docker exec recipedb_backup /backup.sh

# Restore from a backup
docker exec -i recipedb_postgres pg_restore \
  --host=localhost --username=recipeapp --dbname=recipedb \
  --clean --if-exists /backups/recipedb_YYYYMMDD_HHMMSS.dump

# Tail logs
docker compose logs -f db
docker compose logs -f redis

# Stop everything (data volumes preserved)
docker compose --profile dev down

# Nuclear option — destroy volumes too
docker compose --profile dev down -v
```

## Accessing PgAdmin

With the dev profile running, open http://localhost:5050 in your browser.
The RecipeDB server is pre-registered — no manual connection setup needed.

## Postgres tuning notes

The `command:` block in docker-compose.yml passes tuning flags suited for a
container with ~1 GB RAM. Adjust these if your host has more memory:

| Setting                  | Current | Rule of thumb              |
|--------------------------|---------|----------------------------|
| shared_buffers           | 256 MB  | 25% of available RAM       |
| effective_cache_size     | 768 MB  | 75% of available RAM       |
| work_mem                 | 4 MB    | RAM / (max_connections * 2)|
| maintenance_work_mem     | 64 MB   | 5-10% of RAM               |

## Security notes

- Both Postgres and Redis ports are bound to `127.0.0.1` only.
  They are not reachable from outside the host without an explicit tunnel.
- Never commit `.env` to version control — it is gitignored by convention.
- Rotate `POSTGRES_PASSWORD` and `REDIS_PASSWORD` before any production deployment.
- The seed admin user in the migration uses a placeholder password hash.
  Update it immediately after first boot.
