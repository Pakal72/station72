from __future__ import annotations

"""------------------------------------------------------------------------------------------------------"""
"""| Fonctions utilitaires pour interagir avec l'API REST de Home Assistant.                            |"""
"""------------------------------------------------------------------------------------------------------"""
"""| 29.07.25 PCH : Ecriture                                                                            |"""
"""|                Variable du .env : HA_URL et HA_TOKEN                                               |"""
"""|                                                                                                    |"""
"""------------------------------------------------------------------------------------------------------"""

import os
from typing import Any

import requests
from dotenv import load_dotenv

# Chargement des variables d'environnement depuis .env
load_dotenv()

HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

TIMEOUT = 5  # seconds


def _appelle_service_ha(domain: str, service: str, entity_id: str, **data: Any) -> bool:
    """Appelle un service Home Assistant pour une entité donnée.

    Args:
        domain: Domaine du service (ex: ``switch``).
        service: Nom du service (ex: ``turn_on``).
        entity_id: Identifiant de l'entité à cibler.
        **data: Paramètres supplémentaires à envoyer.
    Returns:
        ``True`` si la requête a abouti, ``False`` sinon.
    """
    url = f"{HA_URL}/api/services/{domain}/{service}"
    payload = {"entity_id": entity_id}
    payload.update(data)
    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
        if response.status_code == 401:
            print("❌ Token Home Assistant invalide")
            return False
        response.raise_for_status()
        return True
    except requests.Timeout:
        print("⏱️  Timeout lors de l'appel à Home Assistant")
    except requests.RequestException as exc:
        print(f"❌ Erreur Home Assistant : {exc}")
    return False


def ds9_Allume_Commutateur(entity_id: str) -> bool:
    """Allume un switch Home Assistant."""
    return _appelle_service_ha("switch", "turn_on", entity_id)


def ds9_Eteint_Commutateur(entity_id: str) -> bool:
    """Éteint un switch Home Assistant."""
    return _appelle_service_ha("switch", "turn_off", entity_id)


def ds9_Lit_Etat(entity_id: str) -> Any:
    """Retourne l'état courant d'une entité Home Assistant."""
    url = f"{HA_URL}/api/states/{entity_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code == 401:
            print("❌ Token Home Assistant invalide")
            return None
        response.raise_for_status()
        state = response.json().get("state")
        if state in ("on", "off"):
            return state == "on"
        return state
    except requests.Timeout:
        print("⏱️  Timeout lors de la lecture de l'état")
    except requests.RequestException as exc:
        print(f"❌ Erreur Home Assistant : {exc}")
    return None


def ds9_Modifie_Input_Number(entity_id: str, valeur: float) -> bool:
    """Modifie la valeur d'un ``input_number``."""
    return _appelle_service_ha(
        "input_number", "set_value", entity_id, value=valeur
    )


def ds9_Modifie_Input_Boolean(entity_id: str, actif: bool) -> bool:
    """Active ou désactive un ``input_boolean``."""
    service = "turn_on" if actif else "turn_off"
    return _appelle_service_ha("input_boolean", service, entity_id)


def ds9_Toggle_Commutateur(entity_id: str) -> bool:
    """Inverse l'état d'un switch."""
    return _appelle_service_ha("switch", "toggle", entity_id)


def ds9_Lit_Temperature(entity_id: str) -> float | None:
    """Lit la température d'un capteur."""
    etat = ds9_Lit_Etat(entity_id)
    try:
        return float(etat) if etat is not None else None
    except ValueError:
        return None


def ds9_Lit_Batterie(entity_id: str) -> int | None:
    """Retourne le pourcentage de batterie d'un capteur."""
    etat = ds9_Lit_Etat(entity_id)
    try:
        return int(float(etat)) if etat is not None else None
    except ValueError:
        return None


def ds9_Envoie_Notification(message: str, titre: str | None = None) -> bool:
    """Envoie une notification générique dans Home Assistant."""
    url = f"{HA_URL}/api/services/notify/notify"
    data = {"message": message}
    if titre:
        data["title"] = titre
    try:
        response = requests.post(url, headers=HEADERS, json=data, timeout=TIMEOUT)
        if response.status_code == 401:
            print("❌ Token Home Assistant invalide")
            return False
        response.raise_for_status()
        return True
    except requests.Timeout:
        print("⏱️  Timeout lors de l'envoi de la notification")
    except requests.RequestException as exc:
        print(f"❌ Erreur Home Assistant : {exc}")
    return False


def ds9_Ecrit_Log(message: str, titre: str = "Station79") -> bool:
    """Inscrit un message dans le journal Home Assistant."""
    return _appelle_service_ha(
        "persistent_notification", "create", "", title=titre, message=message
    )

def ds9_Declenche_Script(entity_id: str) -> bool:
    """Déclenche un script Home Assistant."""
    return _appelle_service_ha("script", "turn_on", entity_id)


if __name__ == "__main__":

    print("Seuil VMC Cave :", ds9_Lit_Etat("input_number.seuil_vmc_cave"))

    #print("Toogle Bureau :",ds9_Toggle_Commutateur("switch.sonoff_1000b8576e"))


    print("PYTHON01 :", ds9_Declenche_Script("script.PYTHON01"))

