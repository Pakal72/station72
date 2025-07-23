from __future__ import annotations

import time
import socket
import os
from typing import Any
import httpx
import requests
from qdrant_client import QdrantClient
from pprint import pprint
from dotenv import load_dotenv
import psycopg2
import re
import ds9_fonctions_externes

# Liste des serveurs Ollama à tester
SERVEURS_OLLAMA = (
    "192.168.12.51",
    "192.168.10.250",
    "192.168.10.251"
)

DB_NAME = os.getenv("DB_NAME", "ds9")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD} host={DB_HOST} port={DB_PORT}"

PORT_OLLAMA = 11434

# Adresses des services
OLLAMA_URL = "http://192.168.12.51:11434"
QDRANT_URL = "http://192.168.12.51:6333"
COLLECTION = "assistance"

# Client Qdrant global
qdrant_client = QdrantClient(url=QDRANT_URL)

def LireParametre(code_parametre: str) -> str:
    """Retourne le texte du paramètre correspondant au code donné."""
    try:
        with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT parametre FROM parametres WHERE code_parametre=%s",
                (code_parametre,),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return row[0]
    except Exception:
        pass
    return ""

def embed(text: str) -> list[float]:
    """Retourne l'embedding d'un texte via Ollama."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": "nomic-embed-text:v1.5", "prompt": text},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if "embedding" not in data:
            raise ValueError("Réponse invalide d'Ollama")
        return data["embedding"]
    except requests.RequestException as exc:
        raise RuntimeError(f"Erreur réseau lors de la vectorisation : {exc}")
    except Exception as exc:
        raise RuntimeError(f"Erreur de vectorisation : {exc}")

def search_similar(vector: list[float]) -> list[str]:
    """Recherche les documents les plus proches dans Qdrant."""
    try:
        hits = qdrant_client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=10,
            with_payload=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Erreur lors de la recherche Qdrant : {exc}")

    context_parts = [hit.payload.get("text", "") for hit in hits if hit.payload.get("text")]
    if not context_parts:
        raise RuntimeError("Aucun contexte pertinent trouvé dans Qdrant")

    return context_parts

def build_prompt(question: str, context_parts: list[str]) -> str:
    """Construit le prompt final avec le contexte."""
    context = "\n\n".join(context_parts)
    return (
        "Réponds à la question suivante en utilisant uniquement le contexte fourni.\n"
        f"Contexte :\n{context}\n\nQuestion : {question}\nRéponse :"
    )

def generate_answer(prompt: str) -> str:
    """Envoie le prompt à Ollama et récupère la réponse."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "llama3", "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        data: Any = response.json()
        if "response" not in data:
            raise ValueError("Réponse invalide d'Ollama")
        return data["response"].strip()
    except requests.RequestException as exc:
        raise RuntimeError(f"Erreur réseau lors de la génération : {exc}")
    except Exception as exc:
        raise RuntimeError(f"Erreur lors de la génération : {exc}")

class DS9_IA:
    """Classe IA multi-fournisseurs"""

    def __init__(self, fournisseur: str, modele: str):
        self.fournisseur = fournisseur.upper()
        self.modele = modele

    def serveur_ollama_disponible(self) -> str:
        for ip in SERVEURS_OLLAMA:
            try:
                with socket.create_connection((ip, PORT_OLLAMA), timeout=1):
                    return ip
            except (socket.timeout, ConnectionRefusedError, OSError):
                continue
        raise RuntimeError("Aucun serveur Ollama disponible.")

    def repond(self, prompt: str, question: str) -> str:
        debut = time.time()

        match self.fournisseur:
            case "OLLAMA":
                reponse = self._ollama_repond(prompt, question)
            case "MISTRAL":
                reponse = self._mistral_repond(prompt, question)
            case "CHATGPT":
                reponse = "Fournisseur CHATGPT pas encore implémenté."
            case _:
                reponse = "Fournisseur inconnu."

        print(f"⏱️ Temps de traitement global : {round(time.time() - debut, 2)} secondes")
        return reponse

    def _ollama_repond(self, prompt: str, question: str) -> str:
        try:
            ip = self.serveur_ollama_disponible()
            print(f"\n✅ Serveur Ollama choisi : {ip}")

            url = f"http://{ip}:{PORT_OLLAMA}/api/chat"
            payload = {
                "model": self.modele,
                "messages": [{"role": "user", "content": f"{prompt} {question}"}],
                "stream": False,
            }

            debut = time.time()
            response = httpx.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            print(f"⏱️ Temps de traitement Ollama : {round(time.time() - debut, 2)} secondes")

            return data.get("message", {}).get("content", "Aucune réponse reçue.")
        except Exception as exc:
            return f"Erreur Ollama : {exc}"

    def _mistral_repond(self, prompt: str, question: str) -> str:
        load_dotenv()
        api_key_mistral = os.getenv("MISTRAL_API_KEY", "")
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key_mistral}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.modele,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            "stream": False,
        }

        try:
            debut = time.time()
            response = httpx.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            print(f"⏱️ Temps de traitement Mistral : {round(time.time() - debut, 2)} secondes")

            return data.get("choices", [{}])[0].get("message", {}).get("content", "Aucune réponse reçue.")
        except Exception as exc:
            return f"Erreur Mistral : {exc}"

def rag_repond(question: str, HLimit: int=20) -> str:
    """Réponse avec RAG Qdrant"""
    vector = embed(question)
    
    # Recherche des éléments les plus proches dans Qdrant avec payload
    hits = qdrant_client.search(
        collection_name=COLLECTION,
        query_vector=vector,
        limit=HLimit,
        with_payload=True
    )

    # Construction du contexte avec texte + nom de fichier
    context_parts = [
        f"Extrait : {hit.payload.get('text', '')}\nCode : {hit.payload.get('payload_txt', '')}\nDocument : {hit.payload.get('source_file', '')}"
        for hit in hits
    ]

    context = "\n\n".join(context_parts)

    return context

def ask_ia(question: str, modele: str = "mistral-medium") -> str:
    """Interroge l'IA Mistral avec la question fournie."""
    ia = DS9_IA("MISTRAL", modele)
    return ia.repond("", question)

def ds9_ask_Libre(fournisseur: str, modele: str, question: str) -> str:
    """Chercher a trouver une réponse via l'IA et sans donnée de Qdrant"""
    prompt = (
        "Tu es une IA expert francophone."
        "Réponds d'une manière synthétique, tu ne dois pas halluciner et tu dois adopter un ton professionnel"
        "Si la quesiotn commence par pascal: tu dois répondre avec une question la plus délirante et rigolote possible en fonction quand même de la question"
    ) 
    ia = DS9_IA("MISTRAL", "mistral-medium")
    return (ia.repond(prompt, question)
)

def ds9_ask_Reformule(fournisseur: str, modele: str, question: str, contexte: str) -> str:
    """Réponds en fonction du contexte fourni"""
    prompt = (
        "Tu es une IA expert francophone. Tu dois répondre uniquement à partir du contexte fourni. "
        "Voici le contexte à analyser:"
    ) + contexte
    ia = DS9_IA("MISTRAL", "mistral-medium")
    return (ia.repond(prompt, question)
)

def ds9_ask(question: str) -> str:

    """Chercher a trouver une réponse, soit dans le RAG, soit via une IA et envetuellement appeler une fonction python"""
    fournisseur = "MISTRAL"
    modele = "mistral-medium"
#    fournisseur = "OLLAMA"
#    modele = "llama3.2:1b"


    ReponseQdrant = rag_repond(question, 10)

    prompt = (
        "Tu es une IA expert francophone. Tu dois répondre uniquement à partir du contexte fourni. "
        "Tu va recevoir une question et un contexte qui a été fourni par une base de donéne vectorielle qdrant."
        "Ton objectif est de répondre à la seule question suivante : le contexte fourni est-il pertinent ou pas, tu dois répondre par OUI ou pas NON uniquement"
        "Si la réponse contient <FNC_PYTHON>, c'est qu'elle est pertiente"
    ) 
    QuestionIA = "\nVoici la question à analyser:" + question + "\nVoici le contexte de qdrant :" + ReponseQdrant

    ia = DS9_IA(fournisseur, modele)
    ReponseIA = ia.repond(prompt, QuestionIA)

    if ReponseIA == "NON":
        return( ds9_ask_Libre(fournisseur, modele, question))
    
    # Maintenant j'ai une réponse de Qdrant qui est pertiente, je vais regarder si il y a le mot clef <FNC_PYTHON> dans la répose
    # Si c'est le cas je vais caller la fonction
    # Si non je vais IA_iser la réponse pour kla mettre en forme

    pos = ReponseQdrant.find("<FNC_PYTHON>")
    posFin = pos + len("<FNC_PYTHON>") if pos != -1 else 0

    if posFin == 0:
        return(ds9_ask_Reformule(fournisseur, modele, question, ReponseQdrant)) 

    posParenthese = ReponseQdrant.find(")", posFin)
    fonction = "ds9_fonctions_externes."+ ReponseQdrant[posFin:posParenthese + 1]
    return (eval(fonction))


def main():


    while True:
        question = input("Posez votre question : ")
        if question == "exit":
            break
        print(ds9_ask(question))

  #      ia3 = DS9_IA("QDRANT", "")
  #      print("\nIA 3 : " + ia3.repond("Parle en français.", question))
    

    # Exemples de tests :
#    ia1 = DS9_IA("MISTRAL", "mistral-small")
#    ia2 = DS9_IA("OLLAMA", "llama3.2:1b")
#    ia3 = DS9_IA("QDRANT", "")

#    print("\nIA 1 : " + ia1.repond("Parle en français.", question))
#    print("\nIA 2 : " + ia2.repond("Parle en français.", question))
#    print("\nIA 3 : " + ia3.repond("Parle en français.", question))


if __name__ == "__main__":
    

    main()
