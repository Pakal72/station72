# Station72

Cette application FastAPI permet de gérer un catalogue de jeux stockés dans une base de données PostgreSQL. Elle fournit une petite interface web (Jinja2) pour afficher la liste des jeux.

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
