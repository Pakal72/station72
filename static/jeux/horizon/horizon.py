import os
import requests
from dotenv import load_dotenv

load_dotenv()  # Charge les variables depuis .env

def ds9_allume_bureau() -> str:
    """Allume le switch bureau_pascal via Home Assistant"""
    HA_URL = os.getenv("HA_URL", "http://localhost:8123")
    HA_TOKEN = os.getenv("HA_TOKEN", "")

    print("HA_URL =", HA_URL)
    print("HA_TOKEN =", HA_TOKEN)


    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "entity_id": "switch.sonoff_1000b8576e"
    }

    try:
        response = requests.post(f"{HA_URL}/api/services/switch/turn_on", headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            return "💡 La lumière du bureau est maintenant allumée."
        else:
            return f"⚠️ Erreur {response.status_code} lors de l’appel Home Assistant."
    except Exception as e:
        return f"❌ Erreur de connexion à Home Assistant : {e}"

def ds9_coupe_bureau() -> str:
    """Allume le switch bureau_pascal via Home Assistant"""
    HA_URL = os.getenv("HA_URL", "http://localhost:8123")
    HA_TOKEN = os.getenv("HA_TOKEN", "")

    print("HA_URL =", HA_URL)
    print("HA_TOKEN =", HA_TOKEN)


    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "entity_id": "switch.sonoff_1000b8576e"
    }

    try:
        response = requests.post(f"{HA_URL}/api/services/switch/turn_off", headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            return "💡 La lumière du bureau est maintenant allumée."
        else:
            return f"⚠️ Erreur {response.status_code} lors de l’appel Home Assistant."
    except Exception as e:
        return f"❌ Erreur de connexion à Home Assistant : {e}"

def ds9_get_etat(entity_id: str) -> str:
    """Retourne l’état actuel d’une entité Home Assistant."""
    HA_URL = os.getenv("HA_URL", "http://localhost:8123")
    HA_TOKEN = os.getenv("HA_TOKEN", "")

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        url = f"{HA_URL}/api/states/{entity_id}"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data["state"]
        else:
            return f"⚠️ Erreur {response.status_code} lors de la lecture."
    except Exception as e:
        return f"❌ Erreur : {e}"

if __name__ == "__main__":

    print("Seuil VMC Cave :", ds9_get_etat("input_number.seuil_vmc_cave"))
    #print(ds9_coupe_bureau())
