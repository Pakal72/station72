from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
from ds9_ia import DS9_IA
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

# IA Mistral utilisee en secours
ia_mistral = DS9_IA("MISTRAL", "mistral-small")


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


def analyse_reponse_utilisateur(
    conn, page_id: int, saisie: str
) -> tuple[dict | None, str]:
    """Traite la saisie de l'utilisateur en combinant SQL et IA."""

    # Étape 1 – recherche directe dans la base
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM transitions
            WHERE id_page_source = %s
              AND intention ILIKE '%%' || %s || '%%'
            ORDER BY priorite, id_transition
            LIMIT 1
            """,
            (page_id, saisie),
        )
        transition = cur.fetchone()

    if transition:
        message = transition.get("reponse_systeme") or ""
        return transition, message

    # Étape 2 – analyse IA Mistral
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id_transition, intention
            FROM transitions
            WHERE id_page_source = %s
            ORDER BY priorite, id_transition
            """,
            (page_id,),
        )
        possibles = cur.fetchall()

    if not possibles:
        return None, "Je n’ai pas compris votre réponse."

    liste_reponses = "\n".join(
        f"{p['id_transition']} : {p['intention']}" for p in possibles
    )

    prompt = (
        "Tu est une IA faite pour décider et analyser la correspondance entre une phrase et un ensemble de réponses possibles. "
        "Si une correspondance existe, tu dois renvoyer uniquement l’ID de la réponse correspondante, sous forme d’un entier (ex: 2).\n\n"
        "Exemple :\n"
        'Reponse utilisateur : "je veux allais sur la porte de gaiche"\n'
        "Possibilités de réponse :\n"
        "1 : droite\n2 : gauche\n3 : arrière\n"
        "Dans ce cas tu dois répondre : 2\n\n"
        f'Voici la saisie : "{saisie}"\n'
        "Voici les réponses possibles :\n"
        f"{liste_reponses}"
    )

    reponse_id_str = ia_mistral.repond("", prompt)

    try:
        reponse_id = int(reponse_id_str.strip())
    except Exception:
        return None, "Je n’ai pas compris votre réponse."

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM transitions WHERE id_transition = %s",
            (reponse_id,),
        )
        transition = cur.fetchone()

    if transition:
        message = transition.get("reponse_systeme") or ""
        return transition, message

    return None, "Je n’ai pas compris votre réponse."


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
    response = templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug},
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


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
    response = templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug},
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


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
        transition, message = analyse_reponse_utilisateur(conn, page_id, saisie)
        if transition:
            # On affiche la réponse système éventuelle puis on charge la page cible
            page = charger_page(conn, transition["id_page_cible"])
    slug = slugify(jeu["titre"])
    response = templates.TemplateResponse(
        "play_page.html",
        {
            "request": request,
            "jeu": jeu,
            "page": page,
            "message": message,
            "slug": slug,
        },
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


if __name__ == "__main__":
    uvicorn.run("jouer:app", host="0.0.0.0", port=8001, reload=True)
