
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
def add_jeu(titre: str = Form(...), auteur: str = Form(...)):
    """Insère un nouveau jeu dans la base puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jeux (titre, auteur) VALUES (%s, %s)",
                (titre, auteur),
            )
            conn.commit()
    return RedirectResponse(url="/jeux", status_code=303)


@app.get("/jeux/edit/{jeu_id}")
def edit_jeu_form(request: Request, jeu_id: int):
    """Affiche le formulaire d'édition pré-rempli."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jeux WHERE id_jeu = %s", (jeu_id,))
            jeu = cur.fetchone()
    return templates.TemplateResponse("add_jeu.html", {"request": request, "jeu": jeu})


@app.post("/jeux/edit/{jeu_id}")
def edit_jeu(jeu_id: int, titre: str = Form(...), auteur: str = Form(...)):
    """Met à jour un jeu existant puis redirige vers la liste."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jeux SET titre=%s, auteur=%s WHERE id_jeu=%s",
                (titre, auteur, jeu_id),
            )
            conn.commit()
    return RedirectResponse(url="/jeux", status_code=303)


@app.get("/jeux/delete/{jeu_id}")
def delete_jeu(jeu_id: int):
    """Supprime un jeu par son identifiant."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jeux WHERE id_jeu=%s", (jeu_id,))
            conn.commit()
    return RedirectResponse(url="/jeux", status_code=303)

if __name__ == "__main__":
    
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
