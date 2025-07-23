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
import requests
import base64

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

# --- Paramètres synthèse vocale -------------------------------------------------
TTS_SERVERS = [
    "http://192.168.12.51:8000",
]
TTS_DIR = os.path.join("static", "tts")
os.makedirs(TTS_DIR, exist_ok=True)
_TTS_SERVER_URL: str | None = None


def choisir_serveur_tts() -> str:
    global _TTS_SERVER_URL
    if _TTS_SERVER_URL:
        return _TTS_SERVER_URL
    for url in TTS_SERVERS:
        try:
            print(f"[DEBUG] Test serveur TTS : {url}/languages")
            r = requests.get(f"{url}/languages", timeout=2)
            print(f"[DEBUG] Réponse code : {r.status_code}")
            if r.status_code == 200:
                _TTS_SERVER_URL = url
                return url
        except Exception as e:
            print(f"[DEBUG] Erreur serveur TTS : {e}")
            continue
    raise RuntimeError("Aucun serveur XTTS disponible")



def tts_genere_audio(message: str, voix: str | None = None) -> str | None:
    """Génère un fichier audio pour le message donné et renvoie son chemin."""
    
    print(f"[DEBUG] Génération audio pour : {message}")

    try:
        server = choisir_serveur_tts()
    except Exception:
        return None

    try:
        resp = requests.get(f"{server}/studio_speakers", timeout=5)
        resp.raise_for_status()
        speakers = resp.json()
        speaker = None
        if voix and voix in speakers:
            speaker = voix
            print(f"[DEBUG] Génération speaker pour : {speaker}")
        else:
            for name in speakers:
                if "fr" in name.lower():
                    speaker = name
                    break
            if not speaker:
                speaker = list(speakers.keys())[0]
        params = speakers[speaker]
        payload = {
            "text": message,
            "language": "fr",
            "speaker_embedding": params["speaker_embedding"],
            "gpt_cond_latent": params["gpt_cond_latent"],
        }
        rep = requests.post(f"{server}/tts", json=payload, timeout=30)
        rep.raise_for_status()
    except Exception:
        return None

    print("[DEBUG] Écriture fichier audio")
    audio = rep.content
    if "application/json" in rep.headers.get("Content-Type", ""):
        try:
            b64 = rep.json()
        except Exception:
            b64 = rep.text
        b64 = b64.strip().strip('"')
        try:
            audio = base64.b64decode(b64)
        except Exception:
            return None
    print("[DEBUG] 2")
    filename = os.path.join(TTS_DIR, "message.wav")
    try:
        with open(filename, "wb") as f:
            f.write(audio)
        return "/" + filename.replace(os.sep, "/")
    except Exception:
        return None


def audio_for_message(message: str | None) -> str | None:
    """Crée un audio pour le message si fourni."""
    print("[DEBUG] 4")
    if not message:
        return None
    print("[DEBUG] 5")
    return tts_genere_audio(message)


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

#---------------------------------------------
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
        print(f"[DEBUG] Correspondance SQL trouvée : id_transition = {transition['id_transition']}")
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
        print(f"[DEBUG] Transition IA sélectionnée : id_transition = {transition['id_transition']}")
        message = transition.get("reponse_systeme") or ""
        return transition, message

    print("[DEBUG] Aucun résultat trouvé après réponse IA")
    return None, "Je n’ai pas compris votre réponse."



#---------------------------------------------
@app.get("/play/{jeu_id}")
def demarrer_jeu(request: Request, jeu_id: int):
    """Affiche la première page du jeu."""
    with get_conn() as conn:
        jeu = charger_jeu(conn, jeu_id)
        if not jeu:
            msg = "Jeu introuvable"
            audio = audio_for_message(msg)
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
    audio = audio_for_message("")
    response = templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug, "audio": audio},
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
            audio = audio_for_message(msg)
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": msg, "audio": audio},
                status_code=404,
            )
        slug = slugify(jeu["titre"])
    audio = audio_for_message("")
    response = templates.TemplateResponse(
        "play_page.html",
        {"request": request, "jeu": jeu, "page": page, "message": "", "slug": slug, "audio": audio},
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
            audio = audio_for_message(msg)
            return templates.TemplateResponse(
                "erreur.html",
                {"request": request, "message": msg, "audio": audio},
                status_code=404,
            )
        transition, message = analyse_reponse_utilisateur(conn, page_id, saisie)
        if transition:
            # On affiche la réponse système éventuelle puis on charge la page cible
            page = charger_page(conn, transition["id_page_cible"])
    slug = slugify(jeu["titre"])
    audio = audio_for_message(message)
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
    uvicorn.run("jouer:app", host="0.0.0.0", port=8001, reload=True)
