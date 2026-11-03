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

new_route = '''\n\n@agendes_bp.route('/api/agendes/<task_id>/ai', methods=['POST'])
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
        answer = '\\n'.join(item.get('text','') for output in payload.get('output', [])
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
'''
new_js = '''\nlet sendingAI = false;
async function sendAI() {
  if (!chatId || sendingAI) return;
  const message = el('message').value.trim();
  if (!message) { error('Escriu una consulta abans de preguntar a la IA'); return; }
  sendingAI = true;
  const button = el('askAI');
  button.disabled = true;
  button.textContent = 'Consultant...';
  try {
    await api('/api/agendes/' + encodeURIComponent(chatId) + '/ai', {
      method: 'POST', body: JSON.stringify({message})
    });
    el('message').value = '';
    await refreshNotes();
  } catch (e) { error(e); }
  finally { sendingAI = false; button.disabled = false; button.textContent = '✨ Consultar IA'; }
}
'''
# Afegir botó només dins el formulari del xat, no al de nova feina.
needle='<button class="bg-blue-800 text-white px-3 rounded">Enviar</button></form></div>'
if t.count(needle)!=1:
    raise SystemExit('No s’ha trobat el botó Enviar esperat. Cap fitxer modificat.')
t=t.replace(needle, '<button class="bg-blue-800 text-white px-3 rounded">Desar nota</button><button id="askAI" type="button" onclick="sendAI()" class="bg-violet-700 text-white px-3 py-2 rounded">✨ Consultar IA</button></form></div>')
needle2='refresh();setInterval(refresh,3000);'
if t.count(needle2)!=1:
    raise SystemExit('No s’ha trobat la funció de refresc. Cap fitxer modificat.')
t=t.replace(needle2, new_js+'\n'+needle2)
# Comprovar que el JavaScript nou és a la plantilla i que el Python resultant compila.
r=r.rstrip()+new_route
ast.parse(r)
for path in (route,tpl):
    bak=path.with_suffix(path.suffix+'.bak')
    if bak.exists():
        raise SystemExit(f'La còpia {bak} ja existeix. No s’ha modificat res.')
for path in (route,tpl): shutil.copy2(path, path.with_suffix(path.suffix+'.bak'))
route.write_text(r,encoding='utf-8')
tpl.write_text(t,encoding='utf-8')
print('OK: modificats routes/agendes.py i templates/agendes.html. Còpies .bak creades. Configura OPENAI_API_KEY a Railway.')
