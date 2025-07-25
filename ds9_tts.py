import argparse
import requests
import httpx
import base64
import os
import platform
import subprocess
import re
import sys


xtts_speakers: dict[str, dict] = {}
xtts_url: str = ""

# Liste des serveurs XTTS disponibles
SERVEURS = [
    "http://192.168.12.51:8000",
    "http://192.168.12.250:12003",
]


FICHIER_OUT = "output.wav"

# URL du serveur XTTS à utiliser. Il sera défini dans `main()`.
SERVER_URL = ""

def choisir_serveur_disponible():
    for url in SERVEURS:
        try:
            print(f"🔍 Test de : {url}/languages ...", end="")
            response = requests.get(f"{url}/languages", timeout=2)
            if response.status_code == 200:
                print("✅ Serveur OK")
                return url
            else:
                print(f"❌ Erreur HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ Injoignable ({e})")
    raise RuntimeError("Aucun serveur XTTS disponible !")

def slugify(nom):
    # Nettoyage du nom de fichier
    return re.sub(r'[^a-zA-Z0-9_]', '_', nom)


def genere_audio(texte: str, voix: str = None):
    try:
        response = requests.get(f"{SERVER_URL}/studio_speakers")
        response.raise_for_status()
    except Exception as e:
        print(f"Erreur lors de la récupération des voix : {e}")
        exit(1)

    speakers = response.json()
    if not speakers:
        print("Aucune voix n’est disponible sur le serveur.")
        exit(1)

    # Choix de la voix
    selected_speaker_name = None

    if voix and voix in speakers:
        selected_speaker_name = voix
    else:
        # Sélection par défaut si voix invalide ou non fournie
        for name in speakers.keys():
            lower_name = name.lower()
            if "female" in lower_name and "fr" in lower_name:
                selected_speaker_name = name
                break

        if selected_speaker_name is None:
            for name in speakers.keys():
                if "fr" in name.lower():
                    selected_speaker_name = name
                    break

        if selected_speaker_name is None:
            selected_speaker_name = list(speakers.keys())[0]

    print(f"Voix sélectionnée : {selected_speaker_name}")

    voice_params = speakers[selected_speaker_name]
    speaker_embedding = voice_params["speaker_embedding"]
    gpt_cond_latent = voice_params["gpt_cond_latent"]

    payload = {
        "text": texte,
        "language": "fr",
        "speaker_embedding": speaker_embedding,
        "gpt_cond_latent": gpt_cond_latent
    }

 #   print(payload["text"] or "a")
 #   print(payload["gpt_cond_latent"] or "b")

    try:
        tts_response = requests.post(f"{SERVER_URL}/tts", json=payload)
        tts_response.raise_for_status()
    except Exception as e:
        print(f"Erreur lors de la requête TTS : {e}")
        exit(1)

    audio_bytes = b""
    content_type = tts_response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            base64_str = tts_response.json()
        except ValueError:
            base64_str = tts_response.text
        base64_str = base64_str.strip().strip('"')
        try:
            audio_bytes = base64.b64decode(base64_str)
        except Exception as decode_err:
            print(f"Échec du décodage base64 de l'audio : {decode_err}")
            exit(1)
    else:
        audio_bytes = tts_response.content

    try:
        with open(FICHIER_OUT, "wb") as f:
            f.write(audio_bytes)
        print(f"Fichier audio sauvegardé : {FICHIER_OUT}")
    except Exception as file_err:
        print(f"Erreur lors de l'enregistrement du fichier audio : {file_err}")


async def genere_audio_async(texte: str, voix: str | None = None) -> None:
    """Version asynchrone de ``genere_audio`` utilisant ``httpx.AsyncClient``."""

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{SERVER_URL}/studio_speakers")
            response.raise_for_status()
        except Exception as e:
            print(f"Erreur lors de la récupération des voix : {e}")
            return

        speakers = response.json()
        if not speakers:
            print("Aucune voix n’est disponible sur le serveur.")
            return

        selected_speaker_name = None
        if voix and voix in speakers:
            selected_speaker_name = voix
        else:
            for name in speakers.keys():
                lower_name = name.lower()
                if "female" in lower_name and "fr" in lower_name:
                    selected_speaker_name = name
                    break
            if selected_speaker_name is None:
                for name in speakers.keys():
                    if "fr" in name.lower():
                        selected_speaker_name = name
                        break
            if selected_speaker_name is None:
                selected_speaker_name = list(speakers.keys())[0]

        print(f"Voix sélectionnée : {selected_speaker_name}")

        voice_params = speakers[selected_speaker_name]
        payload = {
            "text": texte,
            "language": "fr",
            "speaker_embedding": voice_params["speaker_embedding"],
            "gpt_cond_latent": voice_params["gpt_cond_latent"],
        }

        try:
            tts_response = await client.post(f"{SERVER_URL}/tts", json=payload)
            tts_response.raise_for_status()
        except Exception as e:
            print(f"Erreur lors de la requête TTS : {e}")
            return

        audio_bytes = b""
        content_type = tts_response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                base64_str = tts_response.json()
            except ValueError:
                base64_str = tts_response.text
            base64_str = base64_str.strip().strip('"')
            try:
                audio_bytes = base64.b64decode(base64_str)
            except Exception as decode_err:
                print(f"Échec du décodage base64 de l'audio : {decode_err}")
                return
        else:
            audio_bytes = tts_response.content

        try:
            with open(FICHIER_OUT, "wb") as f:
                f.write(audio_bytes)
            print(f"Fichier audio sauvegardé : {FICHIER_OUT}")
        except Exception as file_err:
            print(f"Erreur lors de l'enregistrement du fichier audio : {file_err}")

def lire_audio(fichier_audio: str):
    os.startfile(fichier_audio)

def liste_voix():
    try:
        response = requests.get("http://192.168.12.51:8000/studio_speakers")
        response.raise_for_status()
        speakers = response.json()

        print("Voix disponibles sur le serveur XTTS :\n")
        for nom, infos in speakers.items():
            print(f" - {nom}")
    except Exception as e:
        print(f"Erreur lors de la récupération des voix : {e}")    

def generer_messages_voix(langue="fr"):
    try:
        response = requests.get(f"{SERVER_URL}/studio_speakers")
        response.raise_for_status()
        speakers = response.json()
    except Exception as e:
        print(f"Erreur récupération voix : {e}")
        return

    for nom_voix, params in speakers.items():
        texte = f"Je suis {nom_voix}, et ceci est un petit message."

        payload = {
            "text": texte,
            "language": langue,
            "speaker_embedding": params["speaker_embedding"],
            "gpt_cond_latent": params["gpt_cond_latent"]
        }

        try:
            rep = requests.post(f"{SERVER_URL}/tts", json=payload)
            rep.raise_for_status()
        except Exception as e:
            print(f"❌ Erreur pour la voix {nom_voix} : {e}")
            continue

        # Traitement réponse
        audio_bytes = b""
        content_type = rep.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                base64_str = rep.json()
            except:
                base64_str = rep.text
            base64_str = base64_str.strip().strip('"')
            try:
                audio_bytes = base64.b64decode(base64_str)
            except Exception as decode_err:
                print(f"❌ Erreur base64 {nom_voix} : {decode_err}")
                continue
        else:
            audio_bytes = rep.content

        # Sauvegarde fichier
        nom_fichier = f"output_{slugify(nom_voix)}.wav"
        try:
            with open(nom_fichier, "wb") as f:
                f.write(audio_bytes)
            print(f"✅ Fichier généré : {nom_fichier}")
        except Exception as file_err:
            print(f"❌ Erreur écriture fichier {nom_voix} : {file_err}")


def lister_voix_et_generer_exemples(langue: str = "fr"):
    """Affiche la liste des voix disponibles et génère un exemple .wav pour chacune."""
    try:
        response = requests.get(f"{SERVER_URL}/studio_speakers")
        response.raise_for_status()
        speakers = response.json()
    except Exception as e:
        print(f"Erreur récupération voix : {e}")
        return

    #print("Voix disponibles :")
    #for nom in speakers.keys():
    #    print(f" - {nom}")

    print("\nGénération des exemples :")
    for nom_voix, params in speakers.items():
        texte = f"Je suis {nom_voix}, ceci est une démonstration."

        payload = {
            "text": texte,
            "language": langue,
            "speaker_embedding": params["speaker_embedding"],
            "gpt_cond_latent": params["gpt_cond_latent"],
        }

        try:
            rep = requests.post(f"{SERVER_URL}/tts", json=payload)
            rep.raise_for_status()
        except Exception as e:
            print(f"❌ Erreur pour la voix {nom_voix} : {e}")
            continue

        audio_bytes = b""
        content_type = rep.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                base64_str = rep.json()
            except Exception:
                base64_str = rep.text
            base64_str = base64_str.strip().strip('"')
            try:
                audio_bytes = base64.b64decode(base64_str)
            except Exception as decode_err:
                print(f"❌ Erreur base64 {nom_voix} : {decode_err}")
                continue
        else:
            audio_bytes = rep.content

        nom_fichier = f"exemple_{slugify(nom_voix)}.wav"
        try:
            with open(nom_fichier, "wb") as f:
                f.write(audio_bytes)
            print(f"✅ Exemple généré : {nom_fichier}")
        except Exception as file_err:
            print(f"❌ Erreur écriture fichier {nom_voix} : {file_err}")

def main():
    """Montre comment utiliser les différentes fonctions du module."""
    global SERVER_URL

    # Sélection du serveur XTTS
    SERVER_URL = choisir_serveur_disponible()
    print(f"🌐 Serveur sélectionné : {SERVER_URL}")

    # Exemple d'utilisation de slugify
    print("Slugify :", slugify("Nom de fichier exemple"))

    # Génération et lecture d'un message simple
    genere_audio(
        "Salut Léa, je suis heureuse de faire ta connaissance ! "
        "Nous ne sommes pas prêts de dîner ce soir... Mery va parler longtemps.",
        voix="Tanja Adelina",
    )
    lire_audio(FICHIER_OUT)

    # Affichage des voix disponibles
    liste_voix()

    # Création d'un petit message pour chaque voix
    generer_messages_voix()

    # Génération d'un exemple audio pour chaque voix
    lister_voix_et_generer_exemples()

def ds9_parle(voix: str, texte: str, dossier: str, nom_out: str) -> bool:
    global SERVER_URL, FICHIER_OUT

    try:
        # Prépare le chemin complet
        chemin_out = os.path.join(dossier, nom_out)

        # Supprime le fichier s’il existe déjà
        if os.path.exists(chemin_out):
            os.remove(chemin_out)

        # Crée le dossier s’il n’existe pas
        os.makedirs(dossier, exist_ok=True)

        # Sélection du serveur (si pas déjà fait)
        if not SERVER_URL:
            SERVER_URL = choisir_serveur_disponible()
        print(f"🔈 Serveur XTTS sélectionné dans ds9_parle : {SERVER_URL}")

        # Spécifie le fichier de sortie global
        FICHIER_OUT = chemin_out

        # Génération audio
        genere_audio(texte, voix)

        # Vérifie la création du fichier
        return os.path.exists(chemin_out)

    except Exception as e:
        print(f"❌ Erreur dans ds9_parle : {e}")
        return False


async def ds9_parle_async(voix: str, texte: str, dossier: str, nom_out: str) -> bool:
    """Version asynchrone de ``ds9_parle``."""

    global SERVER_URL, FICHIER_OUT

    try:
        chemin_out = os.path.join(dossier, nom_out)
        if os.path.exists(chemin_out):
            os.remove(chemin_out)

        os.makedirs(dossier, exist_ok=True)

        if not SERVER_URL:
            SERVER_URL = choisir_serveur_disponible()
        print(f"🔈 Serveur XTTS sélectionné dans ds9_parle_async : {SERVER_URL}")

        FICHIER_OUT = chemin_out

        await genere_audio_async(texte, voix)

        return os.path.exists(chemin_out)

    except Exception as e:
        print(f"❌ Erreur dans ds9_parle_async : {e}")
        return False


if __name__ == "__main__":


    ok = ds9_parle(
        voix="Henriette Usha",
        texte="Bienvenue dans Station 79. Préparez-vous à entrer dans l'inconnu.",
        dossier="audio_intro",
        nom_out="intro_station79.wav"
    )

    if ok:
        print("✅ Audio généré avec succès.")
    else:
        print("❌ Échec de génération.")

  #  liste_voix()