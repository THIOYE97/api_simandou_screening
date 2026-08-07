# Réplication temps réel Prod ↔ Backup — architecture et exploitation

> Réponse à l'exigence du TDR BCRG (§VII) : *« La plateforme disposera de trois (3)
> environnements : le Test, la Production et le Backup. Une réplication en temps réel
> devra se faire entre la production et le backup. »*

## 1. Principe

La solution utilise la **réplication physique en streaming** native de PostgreSQL
(WAL streaming). Le serveur de **Production** (primaire) transmet en continu son
journal des transactions (WAL) au serveur de **Backup** (standby chaud), qui rejoue
ces enregistrements **en temps réel** (latence sub-milliseconde en régime normal).

- Le **Backup** est un *hot standby* : accessible **en lecture seule** (il refuse
  toute écriture), ce qui permet aussi d'y déporter des lectures lourdes (rapports).
- En cas d'incident sur la Production, le Backup est **promu** primaire en une
  commande (`pg_ctl promote`) : bascule (failover) en quelques secondes, sans
  perte des transactions déjà répliquées.

```
   ┌──────────────┐   WAL streaming (temps réel)   ┌──────────────┐
   │  PRODUCTION  │ ─────────────────────────────► │   BACKUP     │
   │  (primaire)  │   pg_stat_replication : state  │ (hot standby)│
   │  lecture/écr.│   = streaming, lag ≈ 0         │ lecture seule│
   └──────────────┘                                └──────────────┘
          ▲                                               │
          └───────── promotion (failover) ◄───────────────┘
```

L'environnement de **Test** est une base indépendante (données non sensibles),
amorcée par le même outil reproductible (`scripts/init_db.py`).

## 2. Mise en place (serveurs BCRG)

Sur les serveurs virtuels mis à disposition par la BCRG (infrastructure
hyperconvergée, §VIII), PostgreSQL 18.

### 2.1 Primaire (Production)
`postgresql.conf` :
```
wal_level = replica
max_wal_senders = 10
wal_keep_size = 512MB          # marge de rétention WAL
hot_standby = on
# Option haute sécurité (aucune perte) : réplication SYNCHRONE
# synchronous_standby_names = 'backup'
```
`pg_hba.conf` :
```
host replication repl <IP_backup>/32 scram-sha-256
```
Rôle de réplication :
```sql
CREATE ROLE repl WITH REPLICATION LOGIN PASSWORD '<secret>';
```

### 2.2 Backup (standby)
Amorçage par copie cohérente + flux :
```
pg_basebackup -h <IP_prod> -p 5432 -U repl -D <datadir> -R -X stream -c fast
```
`-R` écrit `standby.signal` + `primary_conninfo` : au démarrage, le standby se
connecte au primaire et suit le flux WAL. Démarrer PostgreSQL : il est en
réplication temps réel.

## 3. Supervision

Sur le primaire :
```sql
SELECT application_name, state, sync_state, write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
-- state = 'streaming' ; *_lag ≈ 0
SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_octets
FROM pg_stat_replication;   -- doit rester proche de 0
```
Une alerte est levée si `state != 'streaming'` ou si le lag dépasse un seuil.

## 4. Bascule (failover)

Incident Production → promotion du Backup :
```
pg_ctl -D <datadir_backup> promote
```
Le standby quitte le mode recovery (`pg_is_in_recovery() = false`) et accepte les
écritures. L'application bascule sa chaîne de connexion vers l'ancien Backup
(désormais primaire). Retour à la normale : reconstruire un nouveau standby par
`pg_basebackup` depuis le primaire courant.

## 5. Synchrone vs asynchrone

- **Asynchrone** (par défaut) : latence minimale, très faible risque de perte
  (les dernières transactions non encore streamées en cas de crash brutal).
- **Synchrone** (`synchronous_standby_names`) : **zéro perte** — une transaction
  n'est validée qu'une fois écrite sur le Backup. Recommandé pour la Production
  BCRG au vu de la criticité ; léger surcoût de latence en écriture.

## 6. Démonstration reproductible

Le script [`ops/replication_demo.sh`](../ops/replication_demo.sh) monte, en local
et sans droits particuliers, un primaire + un standby en streaming, puis :
1. prouve le flux (`pg_stat_replication.state = streaming`, lag ≈ 0) ;
2. mesure la **réplication temps réel** d'écritures Prod → Backup ;
3. vérifie que le Backup est en **lecture seule** ;
4. exécute une **bascule** (promotion du Backup) et écrit dessus.

Sortie de référence : `ops/replication_demo.out` (latence mesurée < 400 ms
bout-en-bout, lag = 0 octet, bascule réussie).
