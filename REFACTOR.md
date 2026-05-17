# Refactoring roadmap — post-S4

Ce document liste les chantiers de refactoring **non-urgents** mais qui devront
être traités après le déploiement S1+S2+S3. Le pré-requis commun est la
couverture pytest mise en place en S4 — ne pas refactorer sans filet.

---

## 1. Découper `app/api/routes/analyst.py` (1532 lignes)

### Pourquoi
- Un seul fichier rassemble : liste, détail, export CSV, override de match,
  filtres date/heure, gestion case, etc.
- Toute modification touche un fichier de 1500 lignes → diffs énormes, code
  review impossible, conflits de merge garantis.
- La logique métier vit côté route au lieu d'être dans `services/`.

### Pré-requis bloquant
**Avoir au moins 5 tests d'intégration sur analyst en place** :
- Liste paginée
- Filtres date/risk/status
- Export CSV (au moins 1 ligne)
- Detail d'un screening
- Override d'un match

Tant que ces tests ne sont pas verts, ne pas commencer le split.

### Structure cible
```
app/api/routes/analyst/
├── __init__.py           # construit `router` final
├── list.py               # GET /analyst/screenings (~150 lignes)
├── detail.py             # GET /analyst/screenings/{id} (~200 lignes)
├── export.py             # GET /analyst/screenings/export.csv (~200 lignes)
├── matches.py            # POST/PATCH /analyst/screenings/{id}/matches/{mid}
├── filters.py            # helpers de normalisation (date, status, risk)
└── _shared.py            # _safe_str, _case_display_name, _client_name_from_payload
```

Et dans `app/services/analyst_service.py` : extraire les fonctions de
construction SQL (les `sql += ` à rallonge) et le mapping de payloads.

### Méthode (PR-friendly)
1. Créer `app/api/routes/analyst/` avec un `__init__.py` qui re-exporte
   l'ancien `router` (depuis `_analyst_legacy.py`).
2. Renommer `analyst.py` → `_analyst_legacy.py` (1 commit, 0 changement
   fonctionnel).
3. Pour CHAQUE feature : extraire dans son module dédié, déplacer une seule
   route à la fois, garder le test vert à chaque étape.
4. Une fois tout extrait, supprimer `_analyst_legacy.py` et passer en revue
   les helpers communs vers `_shared.py`.

Estimation : 1 PR par feature, ~7 PRs sur 1 semaine.

---

## 2. Nettoyer l'historique Alembic

### État actuel (audit `alembic history`)
```
s3_refresh_tokens (head)        ← S3
└─ s2_composite_indexes         ← S2
   └─ 2b8733c0877d (multi_tenant_users)
      └─ 2b8eb8544e70 (add_tenants_fields)
         └─ 5cb644009daf (baseline)               ← 3 migrations s'appellent "baseline"
            └─ 8e68f1c52ab1 (add_sumsub_fields_to_cases)   ← DOUBLON probable
               └─ ca2bdb0d51ce (add_sumsub_fields_to_cases) ← DOUBLON probable
                  └─ c2142efa601b (baseline_current_schema)
                     └─ 41e62358e9b7 (merge point)
                        ├─ 005_documents (← chain 001-005, branche legacy)
                        │  └─ 001_users_roles → <base>
                        └─ 89b9122cb96e (baseline_existing_db) → <base>
```

### Problèmes
1. **Deux racines `<base>`** : 001_users_roles et 89b9122cb96e. Le merge
   point 41e62358e9b7 réconcilie les deux, mais c'est fragile.
2. **Trois "baseline"** : 5cb644009daf, c2142efa601b, 89b9122cb96e — sémantique
   floue, on ne sait pas laquelle est *la* baseline canonique.
3. **Doublon SumSub** : 8e68f1c52ab1 ET ca2bdb0d51ce s'appellent
   "add_sumsub_fields_to_cases" — l'une est probablement morte.

### Plan
**Ne pas toucher tant que la prod n'est pas stable.** Une fois OK :
1. Capturer un snapshot du schéma de prod (`pg_dump --schema-only`).
2. Créer une **nouvelle baseline propre** Alembic qui correspond exactement
   au schéma snapshot.
3. Archiver les anciennes migrations dans `alembic/versions/_archive/` (hors
   du run-time).
4. Démarrer une nouvelle séquence linéaire à partir de cette baseline.

Risque : si la prod est rejouée depuis zéro (replay env), ça casse. À faire
uniquement quand on est sûr que tous les environnements sont à `head`.

---

## 3. Refactor `app/api/routes/admin.py` (712 lignes) et `admin_tenants.py` (610)

Même pattern que analyst — extraire en sous-modules.

Pré-requis : tests d'intégration admin (au moins login admin + 1 endpoint CRUD).

---

## 4. Migration SQLAlchemy sync → async (S3.5)

Plus gros chantier, **uniquement après** :
- Au moins 60% de coverage sur les flux critiques
- Tests RLS qui passent en async

### Bénéfices
- Gain ×10 concurrence par worker sur les endpoints I/O bound
- Cohérence avec httpx async (déjà en place pour Anthropic)

### Coût
- Toutes les routes `def` → `async def`
- Sessions sync → `AsyncSession`
- `db.query(...)` → `await db.execute(select(...))`
- `.scalars().all()` → `(await db.execute(...)).scalars().all()`
- Tests à réécrire avec `pytest-asyncio` + `AsyncClient`
- Engine `create_async_engine` avec `asyncpg` (psycopg3 async fonctionne aussi)

Risques : RLS context vars doivent rester sticky par session, attention aux
fuites en cas de `db.commit()` dans une transaction async.

---

## 5. Drift modèle / DB sur `cases.tenant_id`

Détecté pendant la mise en place des tests S4.

### Symptôme
Le modèle SQLAlchemy `app/models/case.py` n'a **pas** de colonne `tenant_id`.
Mais la DB de prod en a une (les migrations S2 créent des indexes composites
`(tenant_id, created_at)` sur `cases`, ce qui présuppose la colonne).

Conséquences :
- 4 tests d'intégration RLS / pagination keyset sont skippés sur DB vierge
  (auto-detect via `information_schema.columns`).
- Le code applicatif filtrait sans doute sur `tenant_id` via RLS Postgres,
  ce qui marche en prod parce que la colonne y est, mais "invisible" pour
  les outils Python (auto-completion, tests, migration auto-generate).

### Plan
1. Ajouter `tenant_id` au modèle `Case` (Column UUID FK ondelete=RESTRICT, indexé).
2. Vérifier que les migrations existantes ont bien ajouté la colonne en DB
   (sinon créer une migration "add_tenant_id_to_cases").
3. Réactiver les 4 tests skippés en supprimant le guard `pytest.skip`.

### Autres drifts à auditer
- `app/models/users.py` avait un drift similaire sur `status` — **corrigé en S4** (ajout dans le modèle).
- `app/models/refresh_token.py` manquait `server_default=text("gen_random_uuid()")` sur `id` — **corrigé en S4**.

À chaque PR qui touche un modèle ou une table, faire un audit rapide :
```bash
python -c "
from app.models import load_all_models; load_all_models()
from app.models.base import Base
for t in Base.metadata.tables.values():
    print(t.name, ':', [c.name for c in t.columns])
" | grep <table_name>
```
puis comparer avec `\d <table_name>` côté psql prod.

---

## 6. Nettoyage des `print()` restants

S1 a nettoyé `auth.py` et `deps/auth.py`. S2 a nettoyé `screening.py`. S3 a
nettoyé `local_ocr_service.py`.

Il reste des `print()` dans :
- `app/services/documents_service.py` (4 occurrences, dont 1 module-load)
- `app/services/export_pdf_service.py` (1 occurrence)
- `app/scripts/import_*.py` (CLI tools — les `print()` sont OK ici, c'est
  l'usage attendu pour les scripts)

Trivial à finir — décliner en S4.5 ou inclure dans le PR de découpage des
services.

---

## 7. Couverture pytest à viser

| Module | Coverage cible | Priorité |
|---|---|---|
| `core/config.py` | 100% | 🟢 (fait en S4) |
| `core/pagination.py` | 100% | 🟢 (fait en S4) |
| `services/matching.py` (pure functions) | 100% | 🟢 (fait en S4) |
| `services/auth_service.py` | 90% | 🟡 partiel (refresh tested via integration) |
| `api/routes/auth.py` | 80% | 🟢 (fait en S4 via integration) |
| `api/routes/cases.py` | 70% | 🟡 partiel (1 test pagination) |
| `api/routes/analyst.py` | 40% | 🔴 à compléter AVANT le découpage |
| `api/routes/screening.py` | 50% | 🔴 à compléter |
| `api/routes/admin*.py` | 30% | 🟡 |
| `tasks/pdf_export.py` | 60% | 🟡 mock storage |

Cible globale après S4.5 : **60%**.
