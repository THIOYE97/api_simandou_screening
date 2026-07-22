#!/usr/bin/env bash
# Démonstration reproductible de la réplication PostgreSQL en streaming (temps réel)
# Prod (primaire) -> Backup (hot standby), puis bascule (failover).
# Ne nécessite aucun privilège : monte deux instances jetables dans un dossier temporaire.
#
#   Exigence TDR BCRG (§VII) : réplication temps réel entre Production et Backup.
#   Usage : ./replication_demo.sh        (PostgreSQL 16+ requis)
set -e

# --- localisation des binaires PostgreSQL ---
BIN=""
for d in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin /usr/local/pgsql/bin; do
  [ -x "$d/postgres" ] && BIN="$d"
done
[ -z "$BIN" ] && command -v postgres >/dev/null && BIN="$(dirname "$(command -v postgres)")"
[ -z "$BIN" ] && { echo "PostgreSQL introuvable."; exit 1; }
echo "PostgreSQL : $("$BIN/postgres" --version)"

ROOT=$(mktemp -d)
PRI=$ROOT/primary; STB=$ROOT/standby
PPORT=6432; SPORT=6433
export PGPASSWORD=replpass
trap '"$BIN/pg_ctl" -D "$STB" -w stop >/dev/null 2>&1 || true; "$BIN/pg_ctl" -D "$PRI" -w stop >/dev/null 2>&1 || true; rm -rf "$ROOT"' EXIT

echo "=== 1) Initialisation du PRIMAIRE (Prod) ==="
"$BIN/initdb" -D "$PRI" -U postgres -A trust >/dev/null
cat >> "$PRI/postgresql.conf" <<CONF
port = $PPORT
listen_addresses = 'localhost'
unix_socket_directories = '$ROOT'
wal_level = replica
max_wal_senders = 10
wal_keep_size = 128MB
hot_standby = on
CONF
echo "host replication repl 127.0.0.1/32 md5" >> "$PRI/pg_hba.conf"
"$BIN/pg_ctl" -D "$PRI" -l "$ROOT/primary.log" -w start >/dev/null
echo "  primaire démarré sur $PPORT"

"$BIN/psql" -h localhost -p $PPORT -U postgres -q <<SQL
CREATE ROLE repl WITH REPLICATION LOGIN PASSWORD 'replpass';
CREATE TABLE operations (id serial PRIMARY KEY, libelle text, cree_a timestamptz DEFAULT now());
INSERT INTO operations (libelle) VALUES ('opération initiale sur le primaire');
SQL
echo "  table 'operations' créée, 1 ligne insérée"

echo "=== 2) Création du STANDBY (Backup) par pg_basebackup (copie + streaming) ==="
"$BIN/pg_basebackup" -h localhost -p $PPORT -U repl -D "$STB" -R -X stream -c fast >/dev/null
sed -i "s/^#*port =.*/port = $SPORT/" "$STB/postgresql.conf"
echo "unix_socket_directories = '$ROOT'" >> "$STB/postgresql.conf"
"$BIN/pg_ctl" -D "$STB" -l "$ROOT/standby.log" -w start >/dev/null
echo "  standby démarré sur $SPORT (lecture seule, réplication en flux)"

sleep 2
echo "=== 3) PREUVE : le primaire voit le standby connecté en streaming ==="
"$BIN/psql" -h localhost -p $PPORT -U postgres -x -c \
  "SELECT application_name, state, sync_state, write_lag, flush_lag, replay_lag FROM pg_stat_replication;"

echo "=== 4) PREUVE temps réel : écriture sur le PRIMAIRE, mesure de la latence ==="
"$BIN/psql" -h localhost -p $PPORT -U postgres -q -c \
  "INSERT INTO operations (libelle) VALUES ('virement interbancaire RTGS'),('chèque télé-compense ACP'),('MT103 SWIFT entrant');"
echo "  3 lignes insérées sur le primaire (total attendu sur le standby : 4)"
start=$(date +%s%N)
for _ in $(seq 1 200); do
  n=$("$BIN/psql" -h localhost -p $SPORT -U postgres -t -A -c "SELECT count(*) FROM operations;")
  if [ "$n" = "4" ]; then
    echo "  ✅ les 4 lignes sont sur le STANDBY après $(( ($(date +%s%N) - start) / 1000000 )) ms (temps réel)"
    break
  fi
  sleep 0.02
done
"$BIN/psql" -h localhost -p $SPORT -U postgres -c "SELECT id, libelle, cree_a FROM operations ORDER BY id;"

echo "=== 5) Lag de réplication (≈ 0) + standby en lecture seule ==="
"$BIN/psql" -h localhost -p $PPORT -U postgres -t -c \
  "SELECT 'lag octets = ' || COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn),0) FROM pg_stat_replication;"
"$BIN/psql" -h localhost -p $SPORT -U postgres -c \
  "INSERT INTO operations (libelle) VALUES ('tentative écriture sur backup');" 2>&1 | grep -iE "read-only|cannot" | head -1 || true

echo "=== 6) BASCULE (failover) : promotion du STANDBY en primaire ==="
"$BIN/pg_ctl" -D "$STB" promote -w >/dev/null
sleep 2
"$BIN/psql" -h localhost -p $SPORT -U postgres -c "SELECT pg_is_in_recovery() AS encore_standby;"
"$BIN/psql" -h localhost -p $SPORT -U postgres -q -c \
  "INSERT INTO operations (libelle) VALUES ('écriture APRÈS bascule — le backup est devenu primaire');"
"$BIN/psql" -h localhost -p $SPORT -U postgres -c "SELECT count(*) AS lignes_apres_bascule FROM operations;"

echo "OK — démonstration terminée."
