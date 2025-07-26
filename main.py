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
import subprocess

from jouer import audio_for_message, analyse_reponse_utilisateur

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
    """Crée l'arborescence /static/jeux/<slug>/ si nécessaire."""
    slug = slugify(title)
    base = os.path.join("static", "jeux", slug)
    os.makedirs(base, exist_ok=True)
    for sub in ("images", "audio", "video", "html"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)


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


@app.get("/", include_in_schema=False)
def redirect_root() -> RedirectResponse:
    """Redirige la racine vers la liste des jeux."""
    return RedirectResponse(url="/jeux")


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
    ia_nom: str = Form(""),
    nom_de_la_voie: str = Form(""),
    voie_actif: bool = Form(False),
    synopsis: str = Form(""),
    motdepasse: str = Form(""),
):
    """Insère un nouveau jeu dans la base puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jeux (titre, auteur, ia_nom, synopsis, mot_de_passe, nom_de_la_voie, voie_actif) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (titre, auteur, ia_nom, synopsis, motdepasse, nom_de_la_voie or None, voie_actif),
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
    ia_nom: str = Form(""),
    nom_de_la_voie: str = Form(""),
    voie_actif: bool = Form(False),
    synopsis: str = Form(""),
    motdepasse: str = Form(""),
):
    """Met à jour un jeu existant puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jeux SET titre=%s, auteur=%s, ia_nom=%s, nom_de_la_voie=%s, voie_actif=%s, synopsis=%s, mot_de_passe=%s WHERE id_jeu=%s",
                (titre, auteur, ia_nom, nom_de_la_voie or None, voie_actif, synopsis, motdepasse, jeu_id),
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


# ------------------------ Gestion des PNJ -------------------------

@app.get("/pnj")
def list_pnj(request: Request, jeu_id: int):
    """Affiche la liste des PNJ pour un jeu."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT titre FROM jeux WHERE id_jeu=%s", (jeu_id,))
            jeu = cur.fetchone()
            cur.execute("SELECT * FROM pnj WHERE id_jeu=%s ORDER BY id", (jeu_id,))
            pnjs = cur.fetchall()
    return templates.TemplateResponse("pnj_index.html", {"request": request, "pnjs": pnjs, "jeu_id": jeu_id, "jeu": jeu})


@app.get("/pnj/add")
def add_pnj_form(request: Request, jeu_id: int):
    """Formulaire d'ajout d'un PNJ."""
    return templates.TemplateResponse("add_pnj.html", {"request": request, "jeu_id": jeu_id})


@app.post("/pnj/add")
def add_pnj(
    jeu_id: int = Form(...),
    nom: str = Form(...),
    personae: str = Form(""),
    prompt: str = Form("")
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pnj (id_jeu, nom, personae, prompt) VALUES (%s, %s, %s, %s)",
                (jeu_id, nom, personae, prompt),
            )
            conn.commit()
    return RedirectResponse(url=f"/pnj?jeu_id={jeu_id}", status_code=303)


@app.get("/pnj/edit/{pnj_id}")
def edit_pnj_form(request: Request, pnj_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM pnj WHERE id=%s", (pnj_id,))
            pnj = cur.fetchone()
            cur.execute("SELECT * FROM enigmes WHERE id_pnj=%s ORDER BY id", (pnj_id,))
            enigmes = cur.fetchall()
    return templates.TemplateResponse(
        "add_pnj.html",
        {"request": request, "pnj": pnj, "enigmes": enigmes, "jeu_id": pnj["id_jeu"]},
    )


@app.post("/pnj/edit/{pnj_id}")
def edit_pnj(
    pnj_id: int,
    jeu_id: int = Form(...),
    nom: str = Form(...),
    personae: str = Form(""),
    prompt: str = Form("")
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pnj SET id_jeu=%s, nom=%s, personae=%s, prompt=%s WHERE id=%s",
                (jeu_id, nom, personae, prompt, pnj_id),
            )
            conn.commit()
    return RedirectResponse(url=f"/pnj?jeu_id={jeu_id}", status_code=303)


@app.get("/pnj/delete/{pnj_id}")
def delete_pnj(pnj_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id_jeu FROM pnj WHERE id=%s", (pnj_id,))
            jeu_id = cur.fetchone()[0]
            cur.execute("DELETE FROM pnj WHERE id=%s", (pnj_id,))
            conn.commit()
    return RedirectResponse(url=f"/pnj?jeu_id={jeu_id}", status_code=303)


@app.get("/enigmes/add")
def add_enigme_form(request: Request, pnj_id: int):
    """Formulaire d'ajout d'une énigme."""
    return templates.TemplateResponse("add_enigme.html", {"request": request, "pnj_id": pnj_id})


@app.post("/enigmes/add")
def add_enigme(
    id_pnj: int = Form(...),
    texte_enigme: str = Form(...),
    texte_reponse: str = Form(...),
    textes_indices: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO enigmes (id_pnj, texte_enigme, texte_reponse, textes_indices)
                VALUES (%s, %s, %s, %s)
                """,
                (id_pnj, texte_enigme, texte_reponse, textes_indices),
            )
            conn.commit()
    return RedirectResponse(url=f"/pnj/edit/{id_pnj}", status_code=303)


@app.get("/enigmes/edit/{enigme_id}")
def edit_enigme_form(request: Request, enigme_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM enigmes WHERE id=%s", (enigme_id,))
            enigme = cur.fetchone()
    return templates.TemplateResponse("add_enigme.html", {"request": request, "enigme": enigme})


@app.post("/enigmes/edit/{enigme_id}")
def edit_enigme(
    enigme_id: int,
    id_pnj: int = Form(...),
    texte_enigme: str = Form(...),
    texte_reponse: str = Form(...),
    textes_indices: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE enigmes SET id_pnj=%s, texte_enigme=%s, texte_reponse=%s, textes_indices=%s
                WHERE id=%s
                """,
                (id_pnj, texte_enigme, texte_reponse, textes_indices, enigme_id),
            )
            conn.commit()
    return RedirectResponse(url=f"/pnj/edit/{id_pnj}", status_code=303)


@app.get("/enigmes/delete/{enigme_id}")
def delete_enigme(enigme_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id_pnj FROM enigmes WHERE id=%s", (enigme_id,))
            pnj_id = cur.fetchone()[0]
            cur.execute("DELETE FROM enigmes WHERE id=%s", (enigme_id,))
            conn.commit()
    return RedirectResponse(url=f"/pnj/edit/{pnj_id}", status_code=303)



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
    est_aide: bool = Form(False),
    enigme_texte: str = Form(""),
    bouton_texte: str = Form(""),
    erreur_texte: str = Form(""),
    contenu: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            next_page = int(page_suivante) if page_suivante else None
            cur.execute(
                "INSERT INTO pages (id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, est_aide, enigme_texte, bouton_texte, erreur_texte, contenu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    jeu_id,
                    titre,
                    ordre,
                    delai_fermeture,
                    next_page,
                    musique,
                    image_fond,
                    est_aide,
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
    est_aide: bool = Form(False),
    enigme_texte: str = Form(""),
    bouton_texte: str = Form(""),
    erreur_texte: str = Form(""),
    contenu: str = Form(""),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            next_page = int(page_suivante) if page_suivante else None
            cur.execute(
                "UPDATE pages SET titre=%s, ordre=%s, delai_fermeture=%s, page_suivante=%s, musique=%s, image_fond=%s, est_aide=%s, enigme_texte=%s, bouton_texte=%s, erreur_texte=%s, contenu=%s WHERE id_page=%s",
                (
                    titre,
                    ordre,
                    delai_fermeture,
                    next_page,
                    musique,
                    image_fond,
                    est_aide,
                    enigme_texte,
                    bouton_texte,
                    erreur_texte,
                    contenu,
                    page_id,
                ),
            )
            conn.commit()
    return RedirectResponse(url=f"/pages/edit/{page_id}", status_code=303)


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
                "SELECT id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, est_aide, enigme_texte, bouton_texte, erreur_texte, contenu FROM pages WHERE id_page=%s",
                (page_id,),
            )
            page = cur.fetchone()
            cur.execute(
                "INSERT INTO pages (id_jeu, titre, ordre, delai_fermeture, page_suivante, musique, image_fond, est_aide, enigme_texte, bouton_texte, erreur_texte, contenu) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    page["id_jeu"],
                    page["titre"],
                    page["ordre"],
                    page["delai_fermeture"],
                    page["page_suivante"],
                    page["musique"],
                    page["image_fond"],
                    page["est_aide"],
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


@app.get("/play/{jeu_id}")
def demarrer_jeu(request: Request, jeu_id: int):
    """Affiche la première page du jeu."""
    with get_conn() as conn:
        jeu = charger_jeu(conn, jeu_id)
        if not jeu:
            msg = "Jeu introuvable"
            audio = audio_for_message(msg, "erreur", 0)
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": msg, "audio": audio},
                status_code=404,
            )
        slug = slugify(jeu["titre"])
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM pages WHERE id_jeu=%s ORDER BY ordre LIMIT 1",
                (jeu_id,),
            )
            page = cur.fetchone()

    print("[DEBUG] ROUTE ACTUELLE : /play")
    message = f"Page {page['ordre']}, {jeu['titre']}"
    print("[DEBUG] Message à lire :", message)
    audio = audio_for_message(
        message,
        slug,
        page["ordre"],
        voix=jeu.get("nom_de_la_voie"),
        voix_active=jeu.get("voie_actif", True),
    )

    response = templates.TemplateResponse(
        "play_page.html",
        {
            "request": request,
            "jeu": jeu,
            "page": page,
            "message": "",
            "slug": slug,
            "audio": audio,
        },
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
            msg = "Page introuvable"
            audio = audio_for_message(msg, "erreur", 0)
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": msg, "audio": audio},
                status_code=404,
            )
        slug = slugify(jeu["titre"])

    print("[DEBUG] ROUTE ACTUELLE : /play")
    message = f"Page {page['ordre']}, {jeu['titre']}"
    print("[DEBUG] Message à lire :", message)
    audio = audio_for_message(
        message,
        slug,
        page["ordre"],
        voix=jeu.get("nom_de_la_voie"),
        voix_active=jeu.get("voie_actif", True),
    )

    response = templates.TemplateResponse(
        "play_page.html",
        {
            "request": request,
            "jeu": jeu,
            "page": page,
            "message": "",
            "slug": slug,
            "audio": audio,
        },
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
            msg = "Page introuvable"
            audio = audio_for_message(msg, "erreur", 0)
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": msg, "audio": audio},
                status_code=404,
            )
        transition, message = analyse_reponse_utilisateur(conn, page_id, saisie)
        if transition:
            page = charger_page(conn, transition["id_page_cible"])

    slug = slugify(jeu["titre"])
    audio = audio_for_message(
        message,
        slug,
        page["ordre"],
        voix=jeu.get("nom_de_la_voie"),
        voix_active=jeu.get("voie_actif", True),
    )
    response = templates.TemplateResponse(
        "play_page.html",
        {
            "request": request,
            "jeu": jeu,
            "page": page,
            "message": message,
            "slug": slug,
            "audio": audio,
        },
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


if __name__ == "__main__":
    jouer_proc = subprocess.Popen(["uv", "run", "jouer.py"])
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    finally:
        jouer_proc.terminate()
        jouer_proc.wait()
