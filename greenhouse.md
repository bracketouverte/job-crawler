Voici une doc pratique de l’API publique Greenhouse à réutiliser ailleurs. Je parle ici de la **Job Board API**, celle utilisée par ce repo pour récupérer des offres publiques Greenhouse.

Sources officielles :
- Greenhouse Job Board API : https://developers.greenhouse.io/job-board.html
- Vue d’ensemble des APIs Greenhouse : https://support.greenhouse.io/hc/en-us/articles/10568627186203-Greenhouse-API-overview

**Résumé**
La Job Board API Greenhouse expose les jobs publics d’un board carrière sous forme JSON.

Base URL :

```text
https://boards-api.greenhouse.io/v1
```

Les endpoints `GET` sont publics et ne demandent pas d’authentification.  
Seul le `POST` pour soumettre une candidature demande une clé API en Basic Auth.

**Identifier le board**
Greenhouse utilise un `board_token`.

Exemples d’URLs publiques :

```text
https://job-boards.greenhouse.io/apolloio
https://job-boards.greenhouse.io/apolloio/jobs/5813188004
https://boards.greenhouse.io/vaulttec/jobs/127817
```

Ici :

```text
board_token = apolloio
job_id = 5813188004
```

Dans ce repo, le token est extrait comme le premier segment du chemin d’une URL Greenhouse.

**Lister les jobs**
Endpoint principal :

```http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/jobs"
```

Réponse typique :

```json
{
  "jobs": [
    {
      "id": 127817,
      "internal_job_id": 144381,
      "title": "Vault Designer",
      "updated_at": "2016-01-14T10:55:28-05:00",
      "requisition_id": "50",
      "location": {
        "name": "NYC"
      },
      "absolute_url": "https://boards.greenhouse.io/vaulttec/jobs/127817",
      "language": "en",
      "metadata": null
    }
  ],
  "meta": {
    "total": 1
  }
}
```

Champs utiles :
- `id` : ID du job post public. C’est celui à utiliser pour récupérer le détail ou postuler.
- `internal_job_id` : ID interne Greenhouse du job. Peut être `null` pour certains prospect posts.
- `title` : titre.
- `updated_at` : date de mise à jour/publication côté board.
- `location.name` : localisation textuelle.
- `absolute_url` : URL publique du job.
- `metadata` : champs custom exposés volontairement par l’entreprise.

Pour inclure directement le contenu complet dans la liste :

```http
GET /v1/boards/{board_token}/jobs?content=true
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/jobs?content=true"
```

Avec `content=true`, chaque job peut inclure :
- `content` : description HTML / texte encodé.
- `departments`
- `offices`

**Récupérer un job précis**
Endpoint :

```http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/jobs/5813188004"
```

Champs courants :
- `id`
- `title`
- `updated_at`
- `requisition_id`
- `location.name`
- `content`
- `absolute_url`
- `language`
- `internal_job_id`
- `metadata`
- parfois `pay_input_ranges` si demandé
- parfois `questions`, `location_questions`, `compliance`, `demographic_questions` si demandé

Paramètres utiles :

```text
questions=true
pay_transparency=true
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/jobs/5813188004?questions=true&pay_transparency=true"
```

`questions=true` sert si tu veux construire un formulaire de candidature dynamique. La réponse peut contenir :
- `questions`
- `location_questions`
- `compliance`
- `demographic_questions`

`pay_transparency=true` peut inclure `pay_input_ranges` quand l’entreprise expose des fourchettes de salaire.

**Lister les offices**
Endpoint :

```http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/offices
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/offices"
```

Paramètre optionnel :

```text
render_as=list
render_as=tree
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/offices?render_as=tree"
```

Utile si tu veux regrouper les jobs par bureau/localisation.

**Lister les departments**
Endpoint :

```http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/departments
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio/departments?render_as=tree"
```

Utile si tu veux regrouper les jobs par département : Engineering, Sales, Product, etc.

**Récupérer les infos du job board**
Endpoint :

```http
GET https://boards-api.greenhouse.io/v1/boards/{board_token}
```

Exemple :

```bash
curl "https://boards-api.greenhouse.io/v1/boards/apolloio"
```

Réponse typique :
- `name`
- `content`

**Soumettre une candidature**
Endpoint :

```http
POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{id}
```

Important :
- Auth requise.
- Basic Auth.
- Username = API key.
- Password vide.
- À faire côté serveur uniquement, jamais depuis le navigateur, sinon la clé est exposée.
- Greenhouse recommande plutôt d’utiliser son formulaire embedded quand possible.
- Greenhouse ne valide pas forcément tous les champs obligatoires côté API, donc il faut valider côté client/serveur avant l’envoi.

Exemple JSON simplifié :

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Basic BASE64_API_KEY_WITH_COLON" \
  -d '{
    "first_name": "Sammy",
    "last_name": "McSamson",
    "email": "sammy@example.com",
    "phone": "3337778888",
    "resume_text": "Resume content...",
    "cover_letter_text": "Cover letter content..."
  }' \
  "https://boards-api.greenhouse.io/v1/boards/apolloio/jobs/5813188004"
```

Pour un upload de CV ou lettre de motivation, utiliser `multipart/form-data`.

**Exemple Python minimal**
```python
import requests
from bs4 import BeautifulSoup

BOARD_TOKEN = "apolloio"

def list_greenhouse_jobs(board_token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json().get("jobs", [])

def get_greenhouse_job(board_token: str, job_id: str) -> dict:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()

def html_to_text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)

jobs = list_greenhouse_jobs(BOARD_TOKEN)

for job in jobs:
    print(job["id"], job["title"], job.get("location", {}).get("name"), job["absolute_url"])

first_job = get_greenhouse_job(BOARD_TOKEN, str(jobs[0]["id"]))
description = html_to_text(first_job.get("content", ""))
print(description[:1000])
```

**Mapping recommandé pour un moteur de jobs**
Pour normaliser une offre Greenhouse :

```text
source = "greenhouse"
source_url = absolute_url
external_id = id
internal_id = internal_job_id
title = title
company = board_token ou nom du board
location = location.name
posted_or_updated_at = updated_at
description_html = content
description_text = strip_html(content)
department = departments[].name
office = offices[].name / offices[].location
language = language
metadata = metadata
```

**Comportement dans ce repo**
Le projet utilise Greenhouse de deux façons :

1. Découverte directe :
```text
GET https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs
```

Il lit surtout :
- `title`
- `absolute_url`
- `location.name`
- `updated_at`

2. Enrichissement d’un job :
```text
GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}
```

Il lit surtout :
- `title`
- `location.name`
- `content`

Puis il convertit `content` en texte propre pour scoring / matching.

**Points d’attention**
- `updated_at` n’est pas toujours strictement une date de publication initiale. C’est une date de mise à jour côté Greenhouse.
- `absolute_url` peut pointer vers `boards.greenhouse.io`, `job-boards.greenhouse.io`, ou une URL carrière custom.
- `content` peut contenir du HTML ou du contenu encodé : toujours nettoyer avant scoring/recherche plein texte.
- `metadata` dépend de ce que l’entreprise choisit d’exposer.
- Les endpoints publics n’ont pas besoin d’auth, mais il faut quand même prévoir timeouts, retries raisonnables et cache.
- Si le board token est faux ou que le job n’existe plus, attendre un `404`.
- Pour les candidatures, ne jamais appeler le `POST` directement depuis un frontend public avec la clé API.