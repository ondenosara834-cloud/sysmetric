# Guide : suite du pipeline CI/CD avec contrôles de sécurité (DevSecOps)

Ce guide explique, étape par étape, ce qui a été ajouté au projet
`system_metrics_agent` après la séance avec le professeur, et pourquoi.

---

## 0. Où on en était, où on va

**Avant** : le fichier `.github/workflows/pipeline.yaml` ne faisait qu'une chose,
installer les dépendances. Aucun test, aucune vérification.

**Après** : un pipeline complet, avec la sécurité intégrée à chaque étape
(c'est ce qu'on appelle le **DevSecOps** : *Dev + Security + Ops*).

```text
 Poste du développeur                    GitHub Actions (et Travis CI)
 ─────────────────────                   ─────────────────────────────────────────────
 git commit ─► pre-commit                 1. Installation + lint (flake8)
   flake8, bandit, gitleaks,                    │
   clé privée...                                ├──► 2. Tests pytest + couverture ≥ 80 %
                                                ├──► 3a. SAST          (Bandit)
 git push ──► pre-push                          ├──► 3b. Dépendances   (pip-audit)
   pytest, pip-audit                            ├──► 3c. Secrets       (Gitleaks)
        │                                       └──► 3d. CodeQL        (GitHub)
        ▼                                                │
   GitHub  ───────────────────────────────►      4. Build Docker + smoke test
                                                    + scan image (Trivy)
                                                         │  (uniquement sur main)
                                                         ▼
                                                 5. CD : publication image sur GHCR
```

Lien avec le cours :
- **CI** (chap. 4) = étapes 1 à 3 : *build, tests, vérification qualité, détection de vulnérabilités*.
- **CD – Continuous Delivery** (chap. 5) = étapes 4 et 5 : l'application est *packagée*
  (image Docker) et publiée, prête à être déployée.
- **2e voie – Feedback** : si un contrôle échoue, le pipeline devient rouge et le
  développeur est notifié immédiatement. *« Un problème détecté tôt se corrige rapidement. »*
- **Shift-left security** : on déplace la sécurité le plus à gauche possible (sur le poste
  du développeur, avant même le push) au lieu de la tester à la fin.

---

## 1. Les 4 familles de tests de sécurité utilisées

| Famille | Question posée | Outil | Où |
|---|---|---|---|
| **SAST** (Static Application Security Testing) | Mon code contient-il des failles ? (injection de commande, `eval`, mot de passe en dur, SSL désactivé...) | **Bandit**, **CodeQL** | pre-commit, GitHub Actions, Travis |
| **SCA** (Software Composition Analysis) | Les bibliothèques que j'utilise ont-elles des CVE connues ? | **pip-audit** | pre-push, GitHub Actions, Travis |
| **Secret scanning** | Ai-je commité un token, une clé API, un mot de passe ? | **Gitleaks** | pre-commit, GitHub Actions, Travis |
| **Container scanning** | Mon image Docker / mon Dockerfile est-il vulnérable ou mal configuré ? | **Trivy** | GitHub Actions, Travis |

---

## 2. Préparer son poste

```bash
# Dans le dossier du projet
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\Activate.ps1

pip install -r requirements.txt -r requirements-dev.txt
```

`requirements-dev.txt` (nouveau fichier) contient les outils qui servent au
développement et à la CI, mais **pas** à l'application elle-même :
pytest-cov, flake8, bandit, pip-audit, pre-commit. On les sépare pour que
l'image Docker reste légère (moins de paquets = moins de failles possibles).

Vérifier que tout passe en local :

```bash
flake8 app                                    # style / erreurs de code
pytest -v --cov=app --cov-fail-under=80       # tests + couverture
bandit -r app -x app/tests                    # failles dans le code
pip-audit -r requirements.txt                 # failles dans les dépendances
```

---

## 3. Ce que les outils ont trouvé dans le code du cours, et les corrections

C'est la partie « vérifier le code pour des failles ». Résultats **avant** correction :

### 3.1 Bandit (3 alertes, sévérité *Low*)

| Code | Problème | Correction |
|---|---|---|
| **B607** | `subprocess.run(["uptime"])` : chemin partiel. Si quelqu'un place un faux programme `uptime` dans le `PATH`, c'est lui qui est exécuté. | On récupère le chemin absolu avec `shutil.which("uptime")` et on lève une erreur s'il n'existe pas. |
| **B603** | Appel `subprocess` : Bandit demande de vérifier qu'aucune donnée externe n'arrive dans la commande. | Vérifié : liste d'arguments fixe, `shell=False` → pas d'injection possible. On le documente avec `# nosec B603`. |
| **B404** | Import du module `subprocess` (simple avertissement). | Usage justifié (exigence du projet) → `# nosec B404` avec commentaire. |

> **À retenir :** `# nosec` ne sert pas à « cacher » une alerte. On ne l'utilise
> qu'après avoir vérifié et **justifié** que le code est sûr. Un correcteur doit
> pouvoir lire pourquoi.

### 3.2 flake8 (qualité)

- `app/montFichier.py` : `import calendar` inutilisé (F401) → supprimé.
- Lignes vides manquantes (E302) dans `api.py` et `montFichier.py` → corrigé.

### 3.3 Dockerfile (ce que Trivy signale en `config`)

| Avant | Risque | Après |
|---|---|---|
| Le conteneur tourne en **root** | Si l'application est compromise, l'attaquant est root dans le conteneur | Utilisateur dédié `appuser` (`USER appuser`) |
| `apt-get install -y procps` | Installe des paquets « recommandés » inutiles, cache apt laissé dans l'image | `--no-install-recommends` + `rm -rf /var/lib/apt/lists/*` |
| `COPY . .` | Copie tout (dont `.git`, `.venv`, `.env` éventuel) dans l'image | `COPY app/ ./app/` + `.dockerignore` complété |
| Pas de `HEALTHCHECK` | Docker ne sait pas si l'API répond | `HEALTHCHECK` sur `/health` |

### 3.4 pip-audit

Aucune vulnérabilité connue dans `requirements.txt` au moment de l'analyse.
Le contrôle reste dans le pipeline car une nouvelle CVE peut être publiée
demain sur une bibliothèque qu'on utilise déjà.

### 3.5 Tests

- Ajout de `app/tests/test_api.py` (le README le mentionnait mais il n'existait pas) :
  `/health`, `POST /metrics`, `/metrics/latest` (vide → 404), payload invalide → 422.
- Ajout de `app/tests/test_config.py` : valeurs par défaut, valeurs non numériques, valeurs négatives.
- Ajout d'un test « uptime introuvable ».
- Résultat : **16 tests, couverture 85 %** (avant : 8 tests, 75 %).

---

## 4. Tester la sécurité AVANT de push : `pre-commit`

Fichier : `.pre-commit-config.yaml`

**Installation (une seule fois par machine) :**

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push
```

À partir de là, Git lance automatiquement les contrôles :

| Moment | Contrôles | Si échec |
|---|---|---|
| `git commit` | check-yaml, gros fichiers, conflits non résolus, **clé privée**, **flake8**, **bandit**, **gitleaks** | Le commit est **refusé** |
| `git push` | **pytest**, **pip-audit** | Le push est **refusé** |

Lancer tous les contrôles manuellement :

```bash
pre-commit run --all-files
```

**Pourquoi en plus de la CI ?** Un secret poussé sur GitHub est compromis,
même si on le supprime au commit suivant (il reste dans l'historique). Il faut
donc le bloquer **avant** qu'il ne parte. La CI reste indispensable car
pre-commit peut être contourné (`git commit --no-verify`) ou pas installé chez
un camarade.

---

## 5. GitHub Actions : le pipeline expliqué job par job

Fichier : `.github/workflows/pipeline.yaml`

### En-tête

```yaml
on:
  push:          { branches: [main] }
  pull_request:  { branches: [main] }
  workflow_dispatch:          # bouton "Run workflow" dans l'onglet Actions

permissions:
  contents: read              # moindre privilège
```

- `permissions: contents: read` : par défaut le jeton du pipeline ne peut que **lire**.
  C'est une bonne pratique de sécurité : si une action tierce était malveillante,
  elle ne pourrait rien modifier. Les jobs qui ont besoin de plus (CodeQL, publication)
  le demandent explicitement.
- `concurrency` : annule l'ancien pipeline si on pousse deux fois de suite.

### Job 1 : `install-dependencies` (Installation & lint)
C'est le job commencé en classe, complété par `flake8`.
`cache: pip` garde les paquets téléchargés d'un pipeline à l'autre.

### Job 2 : `tests`
`pytest --cov-fail-under=80` : le pipeline échoue si les tests échouent **ou**
si moins de 80 % du code est couvert. Le rapport `coverage.xml` est téléchargeable
dans l'onglet *Actions → (le run) → Artifacts*.

### Jobs 3a à 3d : sécurité (en parallèle)
`needs: install-dependencies` : ils attendent le job 1, puis tournent **en même
temps** (pipeline plus rapide).

- **sast-bandit** : `bandit -r app -x app/tests`. Le rapport est conservé en artifact.
- **dependency-audit** : `pip-audit -r requirements.txt --strict`.
- **secrets-scan** : `gitleaks/gitleaks-action@v2` avec `fetch-depth: 0` pour scanner
  **tout l'historique**. Si votre dépôt appartient à une **organisation** GitHub
  (pas un compte perso), il faut une licence gratuite sur gitleaks.io à mettre dans
  le secret `GITLEAKS_LICENSE`.
- **codeql** : analyse de GitHub ; les alertes apparaissent dans *Security → Code scanning*.
  Gratuit sur dépôt **public**, ignoré automatiquement sur dépôt privé.

### Job 4 : `docker-build-scan`
`needs: [tests, sast-bandit, dependency-audit, secrets-scan]` → ne démarre que si
**tout** est vert. Il :
1. scanne le **Dockerfile** (`trivy config`) ;
2. construit l'image **sans la publier** (`push: false`, `load: true`) ;
3. lance le conteneur et vérifie que `/health` répond (**smoke test**) ;
4. scanne l'**image** avec Trivy : échec s'il reste une faille **HIGH/CRITICAL**
   qui a un correctif (`ignore-unfixed: true`).

> ⚠️ **Actualité sécurité à citer dans votre rapport :** en mars 2026, les tags de
> l'action `aquasecurity/trivy-action` (0.0.1 à 0.34.2) ont été détournés par des
> attaquants pour voler les secrets des pipelines (CVE-2026-33634). Seule la v0.35.0
> est sûre ; c'est celle utilisée ici. Leçon : un outil de sécurité est lui-même une
> dépendance à surveiller, et la bonne pratique est d'épingler les actions par leur
> **SHA de commit** plutôt que par un tag.

### Job 5 : `publish-image` (CD)
- `if: github.event_name == 'push' && github.ref == 'refs/heads/main'` :
  uniquement après un merge/push sur `main`, jamais sur une pull request.
- Se connecte à **GHCR** (GitHub Container Registry) avec `GITHUB_TOKEN`, fourni
  automatiquement : **aucun mot de passe à créer**.
- Publie deux images (API et agent), chacune taguée `latest` et avec le SHA du commit
  → permet le **rollback** (chap. 5.3) en redéployant un SHA précédent.
- Les images apparaissent dans l'onglet *Packages* de votre profil GitHub.

C'est du **Continuous Delivery** : l'image est prête, le déploiement en production
reste une décision humaine.

---

## 6. Travis CI

Fichier : `.travis.yml`. Il reprend les mêmes contrôles, organisés en **stages**
qui s'exécutent dans l'ordre : `quality` → `security` → `docker`.
Si un stage échoue, le suivant ne démarre pas.

**Mise en route :**
1. Aller sur **app.travis-ci.com** et se connecter avec GitHub.
2. Autoriser l'application Travis CI sur votre dépôt.
3. Pousser un commit sur `main` : le build démarre.

**À savoir (le dire au prof si besoin) :** Travis n'est plus gratuit en illimité.
Les nouveaux comptes reçoivent des crédits d'essai (10 000) et une **carte bancaire**
est demandée pour vérification. Pour les projets open source, des crédits se
demandent au support. Si ce n'est pas possible, GitHub Actions couvre exactement les
mêmes contrôles.

Points techniques :
- `git: depth: false` : clone complet pour que Gitleaks scanne tout l'historique.
- `services: docker` : Docker disponible pour construire et scanner l'image.
- Trivy est lancé via l'image `aquasec/trivy:0.69.3` (les versions 0.69.4 à 0.69.6
  sont celles qui ont été compromises).

---

## 7. Mettre tout ça sur GitHub

```bash
git checkout -b feature/ci-securite
git add .
git commit -m "CI/CD: tests, SAST, SCA, secrets, scan Docker, publication GHCR + Travis"
git push -u origin feature/ci-securite
```

Puis ouvrir une **Pull Request** vers `main` :
- le pipeline tourne sur la PR (étapes 1 à 4) → vérifier que tout est vert ;
- merger la PR → le pipeline retourne sur `main`, cette fois avec l'étape 5 (publication).

**Paramètre GitHub à activer pour la publication :**
*Settings → Actions → General → Workflow permissions* : laisser « Read repository
contents » (le job de publication demande lui-même `packages: write`).

**Recommandé :** protéger `main`
(*Settings → Branches → Add rule*) avec « Require status checks to pass before merging »
→ impossible de merger si la sécurité échoue.

---

## 8. Démonstration pour le professeur : prouver que la sécurité bloque

Créer volontairement un fichier vulnérable :

```python
# app/bad.py
import subprocess


def run(cmd):
    return subprocess.call(cmd, shell=True)


PASSWORD = "SuperSecret123"
```

```bash
git add app/bad.py
git commit -m "test faille"
```

Résultat attendu : le commit est **refusé** par Bandit :

```text
bandit..........................Failed
>> Issue: [B602] subprocess call with shell=True identified, security issue.
   Severity: High
>> Issue: [B105] Possible hardcoded password: 'SuperSecret123'
```

Si on force (`git commit --no-verify` puis `git push`), c'est le pipeline GitHub
qui devient **rouge** au job « Sécurité : SAST (Bandit) », et l'image n'est ni
construite ni publiée. Supprimer ensuite le fichier.

---

## 9. Dépannage

| Symptôme | Cause / solution |
|---|---|
| `pre-commit` : gitleaks met longtemps la 1re fois | Normal : il se compile une fois puis reste en cache. |
| Job Gitleaks : « missing license » | Dépôt dans une organisation → créer une licence gratuite sur gitleaks.io et l'ajouter dans *Settings → Secrets → Actions* sous `GITLEAKS_LICENSE`. |
| Job Trivy rouge sur une CVE de l'image Python | Mettre à jour l'image de base (`python:3.12-slim` est reconstruite régulièrement) ; relancer le pipeline. |
| `publish-image` : `denied: permission` | Vérifier que le job a bien `packages: write` et que le dépôt n'interdit pas l'écriture des packages. |
| `source` non reconnu (PowerShell) | Sous Windows : `.venv\Scripts\Activate.ps1`. |
| `ConnectionResetError 10054` pendant `pip install` | Connexion coupée : relancer `pip install --timeout 120 --retries 10 -r requirements.txt -r requirements-dev.txt`. |
| Couverture < 80 % | Ajouter des tests, ou ajuster `--cov-fail-under` (à justifier). |

---

## 10. Récapitulatif des fichiers

| Fichier | Statut | Rôle |
|---|---|---|
| `.github/workflows/pipeline.yaml` | modifié | Pipeline GitHub Actions complet |
| `.travis.yml` | **nouveau** | Pipeline Travis CI |
| `.pre-commit-config.yaml` | **nouveau** | Contrôles avant commit / push |
| `requirements-dev.txt` | **nouveau** | Outils de dev et de CI |
| `.flake8` | **nouveau** | Configuration du lint |
| `Dockerfile` | modifié | Utilisateur non-root, image allégée, healthcheck |
| `.dockerignore` | modifié | N'envoie que le nécessaire dans l'image |
| `.gitignore` | modifié | Ignore les rapports de couverture / bandit |
| `app/collector.py` | modifié | Correction Bandit B607 |
| `app/api.py`, `app/montFichier.py` | modifiés | Corrections flake8 |
| `app/tests/test_api.py`, `app/tests/test_config.py` | **nouveaux** | Tests de l'API et de la configuration |
| `app/tests/test_collector.py` | modifié | Test « uptime introuvable » |
