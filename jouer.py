from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
import re
import unicodedata
import os
import uvicorn

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def slugify(text: str) -> str:
    """Transforme un texte en slug ASCII en minuscules."""
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pool: SimpleConnectionPool | None = None

@app.on_event("startup")
def startup() -> None:
    """Initialise la connexion à la base de données."""
    global pool
    pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )

@app.on_event("shutdown")
def shutdown() -> None:
    """Ferme le pool de connexions."""
    if pool:
        pool.closeall()

@contextmanager
def get_conn():
    assert pool is not None, "Le pool de connexions n'est pas initialisé"
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def charger_page(conn, page_id: int):
    """Récupère une page par son identifiant."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM pages WHERE id_page=%s", (page_id,))
        return cur.fetchone()


def charger_jeu(conn, jeu_id: int):
    """Récupère un jeu par son identifiant."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM jeux WHERE id_jeu=%s", (jeu_id,))
        return cur.fetchone()


@app.get("/play/{jeu_id}")
def demarrer_jeu(request: Request, jeu_id: int):
    """Affiche la première page du jeu."""
    with get_conn() as conn:
        jeu = charger_jeu(conn, jeu_id)
        if not jeu:
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": "Jeu introuvable"},
                status_code=404,
            )
        slug = slugify(jeu["titre"])
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM pages WHERE id_jeu=%s ORDER BY ordre LIMIT 1",
                (jeu_id,),
            )
            page = cur.fetchone()
    return templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug},
    )


@app.get("/play/{jeu_id}/{page_id}")
def afficher_page(request: Request, jeu_id: int, page_id: int):
    """Affiche simplement une page sans traitement de saisie."""
    with get_conn() as conn:
        jeu = charger_jeu(conn, jeu_id)
        page = charger_page(conn, page_id)
        if not page or not jeu:
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": "Page introuvable"},
                status_code=404,
            )
        slug = slugify(jeu["titre"])
    return templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug},
    )


@app.post("/play/{jeu_id}/{page_id}")
def jouer_page(request: Request, jeu_id: int, page_id: int, saisie: str = Form("")):
    """Traite la saisie du joueur et applique la transition."""
    with get_conn() as conn:
        jeu = charger_jeu(conn, jeu_id)
        page = charger_page(conn, page_id)
        if not page:
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": "Page introuvable"},
                status_code=404,
            )
        # Recherche de la transition correspondante
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM transitions
                WHERE id_page_source=%s
                  AND %s ILIKE '%%' || intention || '%%'
                ORDER BY priorite, id_transition
                LIMIT 1
                """,
                (page_id, saisie),
            )
            transition = cur.fetchone()
        if transition:
            # On affiche la réponse système éventuelle puis on charge la page cible
            message = transition.get("reponse_systeme") or ""
            page = charger_page(conn, transition["id_page_cible"])
        else:
            # Utilise le message d'erreur spécifique à la page lorsqu'aucune
            # transition ne correspond
            message = page.get("erreur_texte") or "Je n'ai pas compris…"
    slug = slugify(jeu["titre"])
    return templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": message, "slug": slug},
    )


if __name__ == "__main__":
    uvicorn.run("jouer:app", host="0.0.0.1", port=8001, reload=True)
