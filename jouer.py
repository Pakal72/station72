from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
from ds9_ia import DS9_IA
from ds9_tts import ds9_parle
import threading
from datetime import datetime
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
ia_mistral = DS9_IA("MISTRAL", "mistral-large-latest")

# --- Paramètres synthèse vocale -------------------------------------------------


def _supprimer_apres_delai(fichier: str, delai: int = 60) -> None:
    """Planifie la suppression du ``fichier`` après ``delai`` secondes."""

    def _remove() -> None:
        try:
            os.remove(fichier)
        except FileNotFoundError:
            pass

    timer = threading.Timer(delai, _remove)
    timer.daemon = True
    timer.start()


def audio_for_message(
    message: str | None,
    slug: str,
    page_ordre: int,
    voix: str | None = None,
    voix_active: bool = True,
) -> str | None:
    """Génère un fichier audio en utilisant ds9_parle si ``voix_active``."""

    if not message or not voix_active:
        return None

    dossier = os.path.join("static", "jeux", slug, "wav")
    horo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nom = f"{slug}_page{page_ordre}_{horo}.wav"
    ok = ds9_parle(
        voix=voix or "Henriette Usha", texte=message, dossier=dossier, nom_out=nom
    )
    if ok:
        chemin = os.path.join(dossier, nom)
        _supprimer_apres_delai(chemin)
        return "/" + chemin.replace(os.sep, "/")
    return None


def extraire_tts(contenu: str) -> tuple[str, str | None, str | None]:
    """Extrait un marqueur ``<!--tts:...-->`` et renvoie texte et voix.

    Exemple : ``<!--tts:<voice>Damien</voice><texte>Bonjour</texte>-->``
    """

    motif = re.compile(r"<!--\s*tts:(.*?)-->", re.DOTALL)
    match = motif.search(contenu)
    if not match:
        return contenu, None, None

    bloc = match.group(1).strip()
    voix = None
    texte = None

    voix_match = re.search(r"<voice>(.*?)</voice>", bloc, re.DOTALL)
    if voix_match:
        voix = voix_match.group(1).strip()

    texte_match = re.search(r"<texte>(.*?)</texte>", bloc, re.DOTALL)
    if texte_match:
        texte = texte_match.group(1).strip()
    else:
        texte = bloc

    contenu = motif.sub("", contenu, count=1)
    return contenu, texte, voix


def enregistrer_prompt(prompt: str, chemin: str = "debug_prompt.txt") -> None:
    """Écrit le contenu du ``prompt`` dans ``chemin`` pour débogage."""
    try:
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(prompt)
    except Exception as exc:
        print(f"[DEBUG] Impossible d'écrire le prompt : {exc}")


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


def charger_pnj(conn, pnj_id: int) -> dict | None:
    """Charge un PNJ par son identifiant."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM pnj WHERE id=%s", (pnj_id,))
        return cur.fetchone()


def charger_enigmes(conn, pnj_id: int) -> list[dict]:
    """Retourne la liste des énigmes d'un PNJ."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT texte_enigme, texte_reponse, textes_indices FROM enigmes WHERE id_pnj=%s ORDER BY id",
            (pnj_id,),
        )
        return cur.fetchall()


def construire_prompt_pnj(pnj: dict, enigmes: list[dict]) -> str:
    """Assemble les différentes parties du prompt pour le PNJ."""
    sections: list[str] = []
    if pnj.get("personae"):
        sections.append(pnj["personae"])
    if pnj.get("prompt"):
        sections.append(pnj["prompt"])
    for e in enigmes:
        indices_raw = e.get("textes_indices") or ""
        indices_list = [i.strip() for i in indices_raw.splitlines() if i.strip()]
        indices_str = "[" + ", ".join(f'"{i}"' for i in indices_list) + "]" if indices_list else "[]"
        sections.append(
            f"Énigme = \"{e['texte_enigme']}\"\n"
            f"Réponse = \"{e['texte_reponse']}\"\n"
            f"Indices = {indices_str}"
        )
    return "\n".join(sections)


# ---------------------------------------------
def analyse_reponse_utilisateur(
    conn, page_id: int, saisie: str
) -> tuple[dict | None, str]:
    """Traite la saisie de l'utilisateur en combinant SQL et IA."""

    print(f"[DEBUG] Analyse saisie utilisateur : « {saisie} »")

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
        print(
            f"[DEBUG] Correspondance SQL trouvée : id_transition = {transition['id_transition']}"
        )
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
        print("[DEBUG] Aucune réponse possible définie pour cette page.")
        return None, "Je n’ai pas compris votre réponse."

    liste_reponses = "\n".join(
        f"{p['id_transition']} : {p['intention']}" for p in possibles
    )

    prompt = (
        "Tu es une IA spécialisée dans l'analyse de correspondance entre une phrase et une liste de réponses possibles.\n"
        "Ton rôle est de choisir uniquement l’ID correspondant à la meilleure correspondance sémantique.\n"
        "Si une réponse correspond clairement, tu dois répondre uniquement par l’ID (exemple : 3).\n"
        "Si aucune correspondance ne convient, réponds uniquement : 0.\n"
        "⚠️ Réponds **strictement** par un seul nombre, sans phrase, sans explication, sans ponctuation.\n\n"
        "Exemple 1 :\n"
        'Saisie utilisateur : "je veux allais sur la porte de gaiche"\n'
        "Réponses possibles :\n"
        "1 : droite\n2 : gauche\n3 : arrière\n"
        "Réponse attendue : 2\n\n"
        "Exemple 2 :\n"
        'Saisie utilisateur : "prout"\n'
        "Réponses possibles :\n"
        "1 : rouge\n2 : bleu\n3 : jaune\n"
        "Réponse attendue : 0\n\n"
        f'Saisie utilisateur : "{saisie}"\n'
        "Réponses possibles :\n"
        f"{liste_reponses}\n\n"
        "Réponds uniquement par un entier :"
    )

    print("[DEBUG] Envoi prompt à l’IA Mistral…")
    reponse_id_str = ia_mistral.repond("", prompt)
    print(prompt)
    print(f"[DEBUG] Réponse IA brute : {reponse_id_str!r}")

    try:
        reponse_id = int(reponse_id_str.strip())
    except Exception:
        print("[DEBUG] Réponse IA invalide (non entier)")
        return None, "Je n’ai pas compris votre réponse."

    if reponse_id not in [p["id_transition"] for p in possibles]:
        print("[DEBUG] ID IA non présent dans les transitions possibles")
        return None, "Je n’ai pas compris votre réponse."

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM transitions WHERE id_transition = %s",
            (reponse_id,),
        )
        transition = cur.fetchone()

    if transition:
        print(
            f"[DEBUG] Transition IA sélectionnée : id_transition = {transition['id_transition']}"
        )
        message = transition.get("reponse_systeme") or ""
        return transition, message

    print("[DEBUG] Aucun résultat trouvé après réponse IA")
    return None, "Je n’ai pas compris votre réponse."


# ---------------------------------------------
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

    page["contenu"], tts_text, tts_voix = extraire_tts(page.get("contenu", ""))
    tts_audio = (
        audio_for_message(
            tts_text,
            slug,
            page["ordre"],
            voix=tts_voix or jeu.get("nom_de_la_voie"),
            voix_active=jeu.get("voie_actif", True),
        )
        if tts_text
        else None
    )

    message = ""
    audio = None
    context = ""
    base_prompt = ""
    if page.get("id_pnj"):
        pnj = charger_pnj(conn, page["id_pnj"])
        enigmes = charger_enigmes(conn, page["id_pnj"])
        base_prompt = construire_prompt_pnj(pnj, enigmes)
        enregistrer_prompt(base_prompt)
        message = ia_mistral.repond("", base_prompt)
        context = f"PNJ: {message}\n"
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
            "tts_audio": tts_audio,
            "pnj_message": bool(page.get("id_pnj")),
            "context": context,
            "base_prompt": base_prompt,
        },
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


@app.post("/delete-audio")
async def delete_audio(request: Request):
    """Supprime un fichier audio généré."""
    data = await request.json()
    path = data.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="Chemin manquant")
    # Sécurise le chemin pour éviter les traversals
    if not path.startswith("/static/"):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    local_path = os.path.abspath(path.lstrip("/"))
    static_dir = os.path.abspath("static")
    if not local_path.startswith(static_dir):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    try:
        os.remove(local_path)
    except FileNotFoundError:
        pass
    return {"status": "ok"}


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
        page["contenu"], tts_text, tts_voix = extraire_tts(page.get("contenu", ""))
        tts_audio = (
            audio_for_message(
                tts_text,
                slug,
                page["ordre"],
                voix=tts_voix or jeu.get("nom_de_la_voie"),
                voix_active=jeu.get("voie_actif", True),
            )
            if tts_text
            else None
        )

    message = ""
    audio = None
    context = ""
    base_prompt = ""
    if page.get("id_pnj"):
        pnj = charger_pnj(conn, page["id_pnj"])
        enigmes = charger_enigmes(conn, page["id_pnj"])
        base_prompt = construire_prompt_pnj(pnj, enigmes)
        print("[DEBUG] Prompt PNJ envoyé à l’IA :\n", base_prompt)
        enregistrer_prompt(base_prompt)
        message = ia_mistral.repond("", base_prompt)
        context = f"PNJ: {message}\n"
        audio = audio_for_message(
            message,
            slug,
            page["ordre"],
            voix=jeu.get("nom_de_la_voie"),
            voix_active=jeu.get("voie_actif", True),
        )
    else:
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
            "message": message,
            "slug": slug,
            "audio": audio,
            "tts_audio": tts_audio,
            "pnj_message": bool(page.get("id_pnj")),
            "context": context,
            "base_prompt": base_prompt,
        },
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


@app.post("/play/{jeu_id}/{page_id}")
def jouer_page(
    request: Request,
    jeu_id: int,
    page_id: int,
    saisie: str = Form(""),
    context: str = Form(""),
    base_prompt: str = Form(""),
):
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
            # On affiche la réponse système éventuelle puis on charge la page cible
            page = charger_page(conn, transition["id_page_cible"])
            context = ""
        slug = slugify(jeu["titre"])
    page["contenu"], tts_text, tts_voix = extraire_tts(page.get("contenu", ""))
    tts_audio = (
        audio_for_message(
            tts_text,
            slug,
            page["ordre"],
            voix=tts_voix or jeu.get("nom_de_la_voie"),
            voix_active=jeu.get("voie_actif", True),
        )
        if tts_text
        else None
    )
    pnj_message = False
    if page.get("id_pnj"):
        if not transition:
            if not base_prompt:
                pnj = charger_pnj(conn, page["id_pnj"])
                enigmes = charger_enigmes(conn, page["id_pnj"])
                base_prompt = construire_prompt_pnj(pnj, enigmes)
            prompt = f"{base_prompt}\n{context}Joueur: {saisie}\nPNJ:"
            enregistrer_prompt(prompt)
            message = ia_mistral.repond("", prompt)
            context = f"{context}Joueur: {saisie}\nPNJ: {message}\n"
            pnj_message = True
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
            "tts_audio": tts_audio,
            "pnj_message": pnj_message,
            "context": context,
            "base_prompt": base_prompt,
        },
    )
    if page.get("delai_fermeture") and page.get("page_suivante"):
        response.headers["Refresh"] = (
            f"{page['delai_fermeture']}; url=/play/{jeu_id}/{page['page_suivante']}"
        )
    return response


if __name__ == "__main__":

    uvicorn.run("jouer:app", host="0.0.0.0", port=8001, reload=True)
