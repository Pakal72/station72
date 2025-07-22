
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
import os
import re
import unicodedata
import uvicorn

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pool: SimpleConnectionPool | None = None

@app.on_event("startup")
def startup() -> None:
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
    if pool:
        pool.closeall()

@contextmanager
def get_conn():
    assert pool is not None, "Connection pool not initialized"
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def slugify(text: str) -> str:
    """Convertit un texte en slug ASCII en minuscules."""
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def ensure_game_dirs(title: str) -> None:
    """Crée l'arborescence /static/Jeux/<slug>/ si nécessaire."""
    slug = slugify(title)
    base = os.path.join("static", "Jeux", slug)
    os.makedirs(base, exist_ok=True)
    for sub in ("images", "audio", "video", "html"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)

@app.get("/jeux")
def list_jeux(request: Request):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jeux ORDER BY id_jeu")
            jeux = cur.fetchall()
    return templates.TemplateResponse("index.html", {"request": request, "jeux": jeux})


@app.get("/jeux/add")
def add_jeu_form(request: Request):
    """Affiche le formulaire d'ajout d'un jeu."""
    return templates.TemplateResponse("add_jeu.html", {"request": request})


@app.post("/jeux/add")
def add_jeu(
    titre: str = Form(...),
    auteur: str = Form(...),
    synopsis: str = Form(""),
    motdepasse: str = Form(""),
):
    """Insère un nouveau jeu dans la base puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jeux (titre, auteur, synopsis, mot_de_passe) VALUES (%s, %s, %s, %s)",
                (titre, auteur, synopsis, motdepasse),
            )
            conn.commit()
    ensure_game_dirs(titre)
    return RedirectResponse(url="/jeux", status_code=303)


@app.get("/jeux/edit/{jeu_id}")
def edit_jeu_form(request: Request, jeu_id: int):
    """Affiche le formulaire d'édition pré-rempli et la liste des pages."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jeux WHERE id_jeu = %s", (jeu_id,))
            jeu = cur.fetchone()
            cur.execute(
                """
                SELECT p.*, p2.titre AS titre_suivante
                FROM pages AS p
                LEFT JOIN pages AS p2 ON p.page_suivante = p2.id_page
                WHERE p.id_jeu = %s
                ORDER BY p.ordre
                """,
                (jeu_id,),
            )
            pages = cur.fetchall()
    return templates.TemplateResponse(
        "add_jeu.html",
        {"request": request, "jeu": jeu, "pages": pages},
    )


@app.post("/jeux/edit/{jeu_id}")
def edit_jeu(
    jeu_id: int,
    titre: str = Form(...),
    auteur: str = Form(...),
    synopsis: str = Form(""),
    motdepasse: str = Form(""),
):
    """Met à jour un jeu existant puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jeux SET titre=%s, auteur=%s, synopsis=%s, mot_de_passe=%s WHERE id_jeu=%s",
                (titre, auteur, synopsis, motdepasse, jeu_id),
            )
            conn.commit()
    ensure_game_dirs(titre)
    return RedirectResponse(url="/jeux", status_code=303)


@app.get("/jeux/delete/{jeu_id}")
def delete_jeu(jeu_id: int):
    """Supprime un jeu par son identifiant."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jeux WHERE id_jeu=%s", (jeu_id,))
            conn.commit()
    return RedirectResponse(url="/jeux", status_code=303)


@app.get("/pages/add")
def add_page_form(request: Request, jeu_id: int):
    """Formulaire d'ajout d'une page."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id_page, titre FROM pages WHERE id_jeu=%s ORDER BY ordre",
                (jeu_id,),
            )
            pages = cur.fetchall()
    return templates.TemplateResponse(
        "add_page.html", {"request": request, "jeu_id": jeu_id, "pages": pages}
    )


@app.post("/pages/add")
def add_page(
    jeu_id: int = Form(...),
    titre: str = Form(...),
    ordre: int = Form(...),
    delai_fermeture: int = Form(0),
    page_suivante: str = Form(""),
    musique: str = Form(""),
    image_fond: str = Form(""),
    enigme_texte: str = Form(""),
    bouton_texte: str = Form(""),
    erreur_texte: str = Form(""),
    contenu: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            next_page = int(page_suivante) if page_suivante else None
            cur.execute(
                "INSERT INTO pages (id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, enigme_texte, bouton_texte, erreur_texte, contenu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    jeu_id,
                    titre,
                    ordre,
                    delai_fermeture,
                    next_page,
                    musique,
                    image_fond,
                    enigme_texte,
                    bouton_texte,
                    erreur_texte,
                    contenu,
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/jeux/edit/{jeu_id}", status_code=303)


@app.get("/pages/edit/{page_id}")
def edit_page_form(request: Request, page_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM pages WHERE id_page=%s", (page_id,))
            page = cur.fetchone()
            cur.execute(
                "SELECT id_page, titre FROM pages WHERE id_jeu=%s ORDER BY ordre",
                (page["id_jeu"],),
            )
            pages = cur.fetchall()
            cur.execute(
                """
                SELECT t.*, p.titre AS page_cible_titre
                FROM transitions t
                JOIN pages p ON t.id_page_cible = p.id_page
                WHERE t.id_page_source=%s
                ORDER BY t.priorite, t.id_transition
                """,
                (page_id,),
            )
            transitions = cur.fetchall()
    return templates.TemplateResponse(
        "add_page.html",
        {
            "request": request,
            "page": page,
            "transitions": transitions,
            "pages": pages,
        },
    )


@app.post("/pages/edit/{page_id}")
def edit_page(
    page_id: int,
    titre: str = Form(...),
    ordre: int = Form(...),
    delai_fermeture: int = Form(0),
    page_suivante: str = Form(""),
    musique: str = Form(""),
    image_fond: str = Form(""),
    enigme_texte: str = Form(""),
    bouton_texte: str = Form(""),
    erreur_texte: str = Form(""),
    contenu: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            next_page = int(page_suivante) if page_suivante else None
            cur.execute(
                "UPDATE pages SET titre=%s, ordre=%s, delai_fermeture=%s, page_suivante=%s, musique=%s, image_fond=%s, enigme_texte=%s, bouton_texte=%s, erreur_texte=%s, contenu=%s WHERE id_page=%s",
                (
                    titre,
                    ordre,
                    delai_fermeture,
                    next_page,
                    musique,
                    image_fond,
                    enigme_texte,
                    bouton_texte,
                    erreur_texte,
                    contenu,
                    page_id,
                ),
            )
            cur.execute("SELECT id_jeu FROM pages WHERE id_page=%s", (page_id,))
            jeu_id = cur.fetchone()[0]
            conn.commit()
    return RedirectResponse(url=f"/jeux/edit/{jeu_id}", status_code=303)


@app.get("/pages/delete/{page_id}")
def delete_page(page_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id_jeu FROM pages WHERE id_page=%s", (page_id,))
            jeu_id = cur.fetchone()[0]
            cur.execute("DELETE FROM pages WHERE id_page=%s", (page_id,))
            conn.commit()
    return RedirectResponse(url=f"/jeux/edit/{jeu_id}", status_code=303)


@app.get("/pages/duplicate/{page_id}")
def duplicate_page(page_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, enigme_texte, bouton_texte, erreur_texte, contenu FROM pages WHERE id_page=%s",
                (page_id,),
            )
            page = cur.fetchone()
            cur.execute(
                "INSERT INTO pages (id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, enigme_texte, bouton_texte, erreur_texte, contenu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    page["id_jeu"],
                    page["titre"],
                    page["ordre"],
                    page["delai_fermeture"],
                    page["page_suivante"],
                    page["musique"],
                    page["image_fond"],
                    page["enigme_texte"],
                    page["bouton_texte"],
                    page["erreur_texte"],
                    page["contenu"],
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/jeux/edit/{page['id_jeu']}", status_code=303)


@app.get("/transitions/add")
def add_transition_form(request: Request, page_id: int):
    """Formulaire d'ajout d'une transition."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id_jeu FROM pages WHERE id_page=%s", (page_id,))
            jeu_id = cur.fetchone()["id_jeu"]
            cur.execute(
                "SELECT id_page, titre FROM pages WHERE id_jeu=%s ORDER BY ordre",
                (jeu_id,),
            )
            pages = cur.fetchall()
    return templates.TemplateResponse(
        "add_transition.html", {"request": request, "page_id": page_id, "pages": pages}
    )


@app.post("/transitions/add")
def add_transition(
    id_page_source: int = Form(...),
    intention: str = Form(...),
    id_page_cible: int = Form(...),
    condition_flag: str = Form(""),
    valeur_condition: str = Form(""),
    priorite: int = Form(1),
    reponse_systeme: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transitions (
                    id_page_source, intention, id_page_cible,
                    condition_flag, valeur_condition, priorite, reponse_systeme
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_page_source,
                    intention,
                    id_page_cible,
                    condition_flag or None,
                    valeur_condition or None,
                    priorite,
                    reponse_systeme,
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/pages/edit/{id_page_source}", status_code=303)


@app.get("/transitions/edit/{transition_id}")
def edit_transition_form(request: Request, transition_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM transitions WHERE id_transition=%s",
                (transition_id,),
            )
            transition = cur.fetchone()
            cur.execute(
                "SELECT id_jeu FROM pages WHERE id_page=%s",
                (transition["id_page_source"],),
            )
            jeu_id = cur.fetchone()["id_jeu"]
            cur.execute(
                "SELECT id_page, titre FROM pages WHERE id_jeu=%s ORDER BY ordre",
                (jeu_id,),
            )
            pages = cur.fetchall()
    return templates.TemplateResponse(
        "add_transition.html",
        {"request": request, "transition": transition, "pages": pages},
    )


@app.post("/transitions/edit/{transition_id}")
def edit_transition(
    transition_id: int,
    id_page_source: int = Form(...),
    intention: str = Form(...),
    id_page_cible: int = Form(...),
    condition_flag: str = Form(""),
    valeur_condition: str = Form(""),
    priorite: int = Form(1),
    reponse_systeme: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE transitions SET
                    id_page_source=%s,
                    intention=%s,
                    id_page_cible=%s,
                    condition_flag=%s,
                    valeur_condition=%s,
                    priorite=%s,
                    reponse_systeme=%s
                WHERE id_transition=%s
                """,
                (
                    id_page_source,
                    intention,
                    id_page_cible,
                    condition_flag or None,
                    valeur_condition or None,
                    priorite,
                    reponse_systeme,
                    transition_id,
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/pages/edit/{id_page_source}", status_code=303)


@app.get("/transitions/delete/{transition_id}")
def delete_transition(transition_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_page_source FROM transitions WHERE id_transition=%s",
                (transition_id,),
            )
            page_id = cur.fetchone()[0]
            cur.execute(
                "DELETE FROM transitions WHERE id_transition=%s",
                (transition_id,),
            )
            conn.commit()
    return RedirectResponse(url=f"/pages/edit/{page_id}", status_code=303)


@app.get("/transitions/duplicate/{transition_id}")
def duplicate_transition(transition_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id_page_source, intention, id_page_cible,
                       condition_flag, valeur_condition, priorite, reponse_systeme
                FROM transitions WHERE id_transition=%s
                """,
                (transition_id,),
            )
            t = cur.fetchone()
            cur.execute(
                """
                INSERT INTO transitions (
                    id_page_source, intention, id_page_cible,
                    condition_flag, valeur_condition, priorite, reponse_systeme
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    t["id_page_source"],
                    t["intention"],
                    t["id_page_cible"],
                    t["condition_flag"],
                    t["valeur_condition"],
                    t["priorite"],
                    t["reponse_systeme"],
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/pages/edit/{t['id_page_source']}", status_code=303)

if __name__ == "__main__":
    
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
