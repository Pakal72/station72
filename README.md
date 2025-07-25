# Station72

Cette application FastAPI permet de gérer un catalogue de jeux stockés dans une base de données PostgreSQL. Elle fournit une petite interface web (Jinja2) pour afficher la liste des jeux. Chaque jeu dispose maintenant de son propre fichier de style situé dans `/static/jeux/<slug>/style.css`.

## Installation

1. Créez un environnement virtuel Python 3.13 ou plus :
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Installez les dépendances définies dans `pyproject.toml` avec `pip` :
   ```bash
   pip install -e .
   ```

## Variables d'environnement

L'application s'appuie sur plusieurs variables à définir dans un fichier `.env` ou dans votre environnement :

- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`

Vous trouverez un exemple dans `env.example`.

## Changement de schéma

La table `pages` possède maintenant quatre colonnes supplémentaires :

- `delai_fermeture` : temps en secondes avant fermeture automatique d'une page ;
- `page_suivante` : identifiant de la page vers laquelle effectuer la transition automatique ;
- `musique` : chemin vers la musique associée à la page ;
- `image_fond` : image d'arrière-plan de la page.

Une nouvelle table `transitions` décrit les liens entre pages : intention de l'utilisateur, page cible, condition optionnelle et priorité.

## Synthèse vocale

Le module `ds9_tts` propose désormais une fonction asynchrone `ds9_parle_async`.
Elle fonctionne comme `ds9_parle` mais utilise `httpx.AsyncClient` pour
permettre un appel non bloquant dans FastAPI.

```python
from fastapi import BackgroundTasks
from ds9_tts import ds9_parle_async

@app.post("/tts")
async def creer_audio(bg: BackgroundTasks, texte: str):
    bg.add_task(ds9_parle_async, "Henriette Usha", texte, "static/tmp", "out.wav")
```

Il est également possible d'attendre directement la fonction :

```python
audio_ok = await ds9_parle_async("Henriette Usha", "Bonjour", "static/tmp", "out.wav")
```

## Zones interactives sur les pages

Le contenu d'une page peut inclure des boutons ou des zones invisibles afin de
proposer des actions directes au joueur. Il suffit d'ajouter une balise dans le
champ **Contenu** lors de l'édition de la page. La classe `zone-action` place
l'élément en position absolue et change le curseur de la souris. Avec la classe
complémentaire `zone-invisible`, la zone devient transparente mais reste
cliquable.

Exemple :

```html
<button class="zone-action" data-saisie="ouvrir porte" style="top:50px;left:80px;">Porte</button>
```

Pour rendre la zone totalement invisible :

```html
<button class="zone-action zone-invisible" data-saisie="inspecter bureau" style="top:120px;left:30px;"></button>
```

## Texte lu automatiquement

Il est possible d'intégrer un marqueur `<!--tts:Votre texte-->` dans le champ **Contenu** d'une page.
Le texte ainsi indiqué est converti en audio et joué dès l'affichage de la page,
sans apparaître à l'écran.
