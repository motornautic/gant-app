"""Motornautic: agendes compartides v1 (administradors autenticats)."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, render_template, request, session, abort
from sqlalchemy import create_engine, text
from db import get_engine

agendes_bp = Blueprint('agendes', __name__)
TZ = ZoneInfo('Europe/Madrid')
_fallback_engine = None

def db_engine():
    global _fallback_engine
    eng = get_engine()
    if eng is not None:
        return eng
    if _fallback_engine is None:
        path = os.environ.get('AGENDES_SQLITE_PATH', '/data/agendes.sqlite3' if os.path.isdir('/data') else 'data/agendes.sqlite3')
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        _fallback_engine = create_engine('sqlite:///' + os.path.abspath(path), connect_args={'check_same_thread': False})
    return _fallback_engine

def ready():
    engine = db_engine()
    with engine.begin() as con:
        con.execute(text('''CREATE TABLE IF NOT EXISTS agenda_items (
            id VARCHAR(36) PRIMARY KEY, boat VARCHAR(200) NOT NULL,
            title VARCHAR(300) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pendent',
            owners VARCHAR(120) NOT NULL, due_date VARCHAR(10),
            created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
            updated_by VARCHAR(100) NOT NULL)'''))
        con.execute(text('''CREATE TABLE IF NOT EXISTS agenda_notes (
            id VARCHAR(36) PRIMARY KEY, task_id VARCHAR(36) NOT NULL,
            author VARCHAR(100) NOT NULL, message TEXT NOT NULL,
            created_at VARCHAR(40) NOT NULL)'''))
    return engine

def who():
    user = session.get('admin_autenticat')
    if not user:
        abort(403)
    return str(user)[:100]

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

def out(row):
    obj = dict(row)
    obj['owners'] = json.loads(obj['owners'])
    return obj

@agendes_bp.route('/agendes')
def page():
    who()
    return render_template('agendes.html')

@agendes_bp.route('/api/agendes', methods=['GET'])
def listing():
    who()
    with ready().connect() as con:
        rows = con.execute(text('SELECT * FROM agenda_items ORDER BY updated_at DESC')).mappings().all()
    return jsonify({'items': [out(r) for r in rows]})

@agendes_bp.route('/api/agendes', methods=['POST'])
def create():
    user = who()
    import uuid
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()[:300]
    boat = str(data.get('boat') or 'GENERAL').strip()[:200] or 'GENERAL'
    owners = data.get('owners', ['dani'])
    if not title or not isinstance(owners, list) or not owners or not set(owners).issubset({'dani','raul'}):
        return jsonify(error='Títol i responsables vàlids obligatoris'), 400
    id_ = str(uuid.uuid4()); timestamp = now()
    with ready().begin() as con:
        con.execute(text('INSERT INTO agenda_items (id,boat,title,status,owners,due_date,created_at,updated_at,updated_by) VALUES (:id,:boat,:title,:status,:owners,:due_date,:created_at,:updated_at,:updated_by)'),
            dict(id=id_,boat=boat,title=title,status='pendent',owners=json.dumps(owners),due_date=None,created_at=timestamp,updated_at=timestamp,updated_by=user))
    return jsonify(id=id_), 201

@agendes_bp.route('/api/agendes/<task_id>', methods=['PATCH'])
def update(task_id):
    user = who()
    data = request.get_json(silent=True) or {}
    allowed = {'pendent','urgent','espera','fet','posposat'}
    updates = {}
    if 'status' in data:
        if data['status'] not in allowed: return jsonify(error='Estat incorrecte'), 400
        updates['status'] = data['status']
    if 'owners' in data:
        owners = data['owners']
        if not isinstance(owners,list) or not owners or not set(owners).issubset({'dani','raul'}): return jsonify(error='Responsables incorrectes'), 400
        updates['owners'] = json.dumps(owners)
    if 'due_date' in data:
        date = data['due_date']
        if date is not None:
            try: datetime.strptime(date, '%Y-%m-%d')
            except (TypeError, ValueError): return jsonify(error='Data incorrecta'), 400
        updates['due_date'] = date
    if not updates: return jsonify(error='Cap canvi'), 400
    updates.update(updated_at=now(), updated_by=user, id=task_id)
    assignments = ', '.join(k+' = :'+k for k in updates if k!='id')
    with ready().begin() as con:
        result = con.execute(text('UPDATE agenda_items SET '+assignments+' WHERE id = :id'),updates)
    return (jsonify(ok=True) if result.rowcount else (jsonify(error='No trobada'),404))

@agendes_bp.route('/api/agendes/<task_id>/notes', methods=['GET','POST'])
def notes(task_id):
    user = who()
    import uuid
    engine=ready()
    with engine.begin() as con:
        exists=con.execute(text('SELECT id FROM agenda_items WHERE id=:id'),{'id':task_id}).first()
        if not exists: return jsonify(error='No trobada'),404
        if request.method=='POST':
            message=str((request.get_json(silent=True) or {}).get('message') or '').strip()[:5000]
            if not message: return jsonify(error='Missatge buit'),400
            con.execute(text('INSERT INTO agenda_notes (id,task_id,author,message,created_at) VALUES (:id,:task_id,:author,:message,:created_at)'),
              dict(id=str(uuid.uuid4()),task_id=task_id,author=user,message=message,created_at=now()))
            con.execute(text('UPDATE agenda_items SET updated_at=:ts, updated_by=:user WHERE id=:id'),{'ts':now(),'user':user,'id':task_id})
        rows=con.execute(
            text('SELECT id,author,message,created_at FROM agenda_notes WHERE task_id=:id ORDER BY created_at,id'),
            {'id':task_id}
        ).mappings().all()
    return jsonify(notes=[dict(r) for r in rows])
    
@agendes_bp.route('/api/agendes/<task_id>/notes/<note_id>', methods=['DELETE'])
def eliminar_nota(task_id, note_id):
    user = who()

    with ready().begin() as con:
        result = con.execute(
            text("""
                DELETE FROM agenda_notes
                WHERE id = :note_id
                  AND task_id = :task_id
                  AND lower(author) = lower(:user)
            """),
            {
                'note_id': note_id,
                'task_id': task_id,
                'user': user
            }
        )

        if result.rowcount == 0:
            return jsonify(error='Nota no trobada o sense permís'), 403

    return jsonify(ok=True)

@agendes_bp.route('/api/agendes/<task_id>/ai', methods=['POST'])
def consultar_ia_agenda(task_id):
    """Consulta contextual a OpenAI; desa pregunta i resposta a les notes compartides."""
    import uuid
    import requests
    user = who()
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        return jsonify(error='Falta configurar OPENAI_API_KEY a Railway'), 503
    body = request.get_json(silent=True) or {}
    message = str(body.get('message') or '').strip()
    if not message or len(message) > 2000:
        return jsonify(error='Pregunta obligatòria (màxim 2000 caràcters)'), 400
    with ready().connect() as con:
        task = con.execute(text('SELECT boat,title,status,due_date,owners FROM agenda_items WHERE id=:id'), {'id': task_id}).mappings().first()
        if task is None:
            return jsonify(error='Feina no trobada'), 404
        history = con.execute(text('SELECT author,message FROM agenda_notes WHERE task_id=:id ORDER BY created_at DESC,id DESC LIMIT 18'), {'id': task_id}).mappings().all()
    context = [ {'role': 'user' if row['author'].lower() != 'ia' else 'assistant',
                 'content': (row['author'] + ': ' + row['message'])[:2500]}
                for row in reversed(history) ]
    instructions = (
        'Ets l’assistent tècnic de Motornautic. Respon en català, amb precisió i concisió. '
        'Context limitat a aquesta feina. No afirmis haver revisat documents, manuals, equips o missatges externs si no es mostren. '
        'Si una actuació pot comportar risc elèctric, mecànic o de combustible, recomana una comprovació segura. '
        'No canviïs mai l’estat de la feina sense autorització explícita ni afirmis que ho has fet. '
        f'Embarcació: {task["boat"]}. Feina: {task["title"]}. Estat: {task["status"]}. '
        f'Data prevista: {task["due_date"] or "no definida"}.'
    )
    try:
        response = requests.post('https://api.openai.com/v1/responses',
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            json={'model': os.environ.get('OPENAI_AGENDES_MODEL', 'gpt-4.1-mini'),
                  'instructions': instructions,
                  'input': context + [{'role': 'user', 'content': user + ': ' + message}],
                  'max_output_tokens': 650, 'store': False}, timeout=50)
        if not response.ok:
            return jsonify(error='No s’ha pogut consultar la IA. Revisa la clau, el crèdit i els registres de Railway.'), 502
        payload = response.json()
        answer = '\n'.join(item.get('text','') for output in payload.get('output', [])
                           for item in output.get('content', []) if item.get('type') == 'output_text').strip()
        if not answer:
            return jsonify(error='La IA no ha retornat una resposta de text'), 502
    except requests.RequestException:
        return jsonify(error='Error de connexió amb la IA; no s’ha desat la consulta'), 502
    timestamp = now()
    with ready().begin() as con:
        for author, content in ((user, message), ('IA', answer[:5000])):
            con.execute(text('INSERT INTO agenda_notes (id,task_id,author,message,created_at) VALUES (:id,:task_id,:author,:message,:created_at)'),
                        {'id': str(uuid.uuid4()), 'task_id': task_id, 'author': author,
                         'message': content, 'created_at': timestamp})
        con.execute(text('UPDATE agenda_items SET updated_at=:ts, updated_by=:user WHERE id=:id'),
                    {'ts': timestamp, 'user': user, 'id': task_id})
    return jsonify(ok=True, answer=answer)

