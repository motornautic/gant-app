from pathlib import Path
from datetime import datetime
import ast
import shutil

ROOT=Path(__file__).resolve().parent
route=ROOT/'routes'/'agendes.py'
tpl=ROOT/'templates'/'agendes.html'
if not route.is_file() or not tpl.is_file():
    raise SystemExit('ERROR: copia aquest instal·lador a l’arrel de gant-app, al costat de app.py')
r=route.read_text(encoding='utf-8')
t=tpl.read_text(encoding='utf-8')
if 'def consultar_ia_agenda(' in r or 'async function sendAI(' in t:
    raise SystemExit('La integració IA ja sembla instal·lada. No s’ha modificat res.')
if "from db import get_engine" not in r or 'refreshNotes()' not in t:
    raise SystemExit('El codi ha canviat. No s’ha modificat res; revisa la versió.')
