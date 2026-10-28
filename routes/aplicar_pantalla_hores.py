"""Aplica la primera fase de pantalles mòbils a MotorNautic.
Executar des de l'arrel del repositori: python aplicar_pantalla_hores.py
Fa còpies .bak i comprova les coincidències abans de desar res.
"""
from pathlib import Path
import ast

root = Path.cwd()
py_path = root / 'routes' / 'operari.py'
html_path = root / 'templates' / 'operari.html'
app_path = root / 'app.py'
new_path = root / 'templates' / 'operari_hores.html'
paths = [py_path,html_path,app_path]
for p in paths:
    if not p.is_file():
        raise SystemExit(f'Falta {p}. Executa-ho a la carpeta principal del repositori.')
if new_path.exists():
    raise SystemExit('La plantilla operari_hores.html ja existeix: no es modifica res.')

py, html, app = [p.read_text(encoding='utf-8') for p in paths]
def replace_once(s,old,new,where):
    if s.count(old)!=1:
        raise SystemExit(f'No trobo exactament una coincidència a {where}. Cap fitxer modificat.')
    return s.replace(old,new,1)

old_start = '        <details><summary class="text-sm font-semibold cursor-pointer">➕ Afegir hores manualment</summary>'
old_end = '        {% if t.historial_hores %}'
start=html.find(old_start)
end=html.find(old_end,start)
if start<0 or end<0:
    raise SystemExit('No trobo el formulari antic a operari.html. Cap fitxer modificat.')
new_link = '''        <a href="{{ url_for('operari.pagina_hores_manuals', csv_index=t.csv_index) }}" class="flex justify-between items-center w-full rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-900 hover:bg-blue-100">
          <span>➕ Afegir hores i observacions</span><span aria-hidden="true">›</span>
        </a>
'''
html=html[:start]+new_link+html[end:]

route='''@operari_bp.route("/operari/tasca/<int:csv_index>/hores", methods=["GET"])
def pagina_hores_manuals(csv_index):
    """Pantalla de registre d'hores d'una tasca assignada."""
    operari_actual = (session.get("operari_autenticat") or "").strip()
    es_admin = bool(session.get("admin_autenticat"))
    if not (operari_actual or es_admin):
        return redirect(url_for("operari.vista_operari"))

    df = carregar_tasques()
    if not 0 <= csv_index < len(df):
        abort(404)
    tasca = df.iloc[csv_index].to_dict()
    assignats = [n.strip().casefold() for n in str(tasca.get("Operari", "")).split(",") if n.strip()]
    if not es_admin and operari_actual.casefold() not in assignats:
        abort(403)

    return render_template(
        "operari_hores.html",
        tasca=tasca,
        csv_index=csv_index,
        now_date=datetime.now().strftime("%Y-%m-%d"),
    )

'''
py=replace_once(py,'@operari_bp.route("/afegir_temps_manual", methods=["POST"])',route+'@operari_bp.route("/afegir_temps_manual", methods=["POST"])','operari.py')

start=py.find('def afegir_temps_manual():')
end=py.find('    data_imp_raw =',start)
if start<0 or end<0:
    raise SystemExit('No trobo la funció de les hores manuals. Cap fitxer modificat.')
new_header='''def afegir_temps_manual():
    try:
        idx = int(request.form.get("csv_index", ""))
    except (ValueError, TypeError):
        abort(400)
    df = carregar_tasques()
    if not 0 <= idx < len(df):
        abort(404)
    operari_sel = (session.get("operari_autenticat") or "").strip()
    es_admin = bool(session.get("admin_autenticat"))
    if not (operari_sel or es_admin):
        abort(403)
    assignats = [n.strip().casefold() for n in str(df.iloc[idx].get("Operari", "")).split(",") if n.strip()]
    if not es_admin and operari_sel.casefold() not in assignats:
        abort(403)
    hora_inici, hora_fi = request.form.get("hora_inici"), request.form.get("hora_fi")
    if not hora_inici or not hora_fi:
        abort(400)

'''
py=py[:start]+new_header+py[end:]
start=py.index('def afegir_temps_manual():')
end=py.index('@operari_bp.route("/registrar_sollicitud_material"', start)
block=py[start:end]
block=replace_once(block,'return redirect(url_for("operari.vista_operari", operari=operari_sel))','return redirect(url_for("operari.vista_operari", _anchor=f"tasca-{idx}"))','final d\'afegir_temps_manual')
py=py[:start]+block+py[end:]
app=replace_once(app,'    "operari.afegir_temps_manual",','    "operari.afegir_temps_manual",\n    "operari.pagina_hores_manuals",','app.py')

page='''{% extends "base.html" %}
{% block content %}
<main class="max-w-xl mx-auto px-3 py-4 sm:py-6">
  <a href="{{ url_for('operari.vista_operari', _anchor='tasca-' ~ csv_index) }}" class="inline-block text-sm font-bold text-blue-900 mb-5">← Tornar a la tasca</a>
  <section class="rounded-2xl bg-white border shadow-sm overflow-hidden">
    <header class="bg-blue-900 text-white p-5">
      <p class="text-xs font-bold text-blue-200 uppercase tracking-wider">Registre de feina</p>
      <h1 class="text-xl font-extrabold mt-1">➕ Afegir hores</h1>
      <p class="mt-2 text-sm text-blue-100">⛵ {{ tasca['Embarcació'] }} · {{ tasca['Titol_Tasca'] }}</p>
    </header>
    <form action="{{ url_for('operari.afegir_temps_manual') }}" method="POST" class="p-5 space-y-5">
      <input type="hidden" name="csv_index" value="{{ csv_index }}">
      <label class="block text-sm font-semibold text-slate-800">Data
        <input type="date" name="data_imputacio" value="{{ now_date }}" required class="block w-full mt-2 border rounded-xl p-3 text-base">
      </label>
      <div class="grid grid-cols-2 gap-3">
        <label class="block text-sm font-semibold text-slate-800">Hora inici
          <input type="time" name="hora_inici" required class="block w-full mt-2 border rounded-xl p-3 text-base">
        </label>
        <label class="block text-sm font-semibold text-slate-800">Hora fi
          <input type="time" name="hora_fi" required class="block w-full mt-2 border rounded-xl p-3 text-base">
        </label>
      </div>
      <label class="block text-sm font-semibold text-slate-800">📝 Observacions del període <span class="font-normal text-slate-500">(opcional)</span>
        <textarea name="observacions_manual" rows="6" maxlength="4000" placeholder="Feina realitzada, incidències o material pendent..." class="block w-full mt-2 border rounded-xl p-3 text-base resize-y"></textarea>
      </label>
      <label class="flex items-center gap-3 rounded-xl bg-slate-50 border p-3 text-sm font-semibold text-slate-800">
        <input type="checkbox" name="marcar_finalitzada" value="1" class="w-5 h-5 accent-green-700"> Marcar tasca finalitzada
      </label>
      <button type="submit" class="w-full rounded-xl bg-blue-800 text-white p-4 text-base font-extrabold">💾 Desar hores i observacions</button>
      <a href="{{ url_for('operari.vista_operari', _anchor='tasca-' ~ csv_index) }}" class="block text-center rounded-xl border p-3 text-sm font-semibold text-slate-600">Cancel·lar</a>
    </form>
  </section>
</main>
{% endblock %}
'''

ast.parse(py)
ast.parse(app)
from jinja2 import Environment
for name,source in [('operari.html',html),('operari_hores.html',page)]:
    Environment().parse(source)
for path,source in zip(paths,[py,html,app]):
    (path.with_suffix(path.suffix+'.bak')).write_bytes(path.read_bytes())
    path.write_text(source,encoding='utf-8')
new_path.write_text(page,encoding='utf-8')
print('FET: routes/operari.py, templates/operari.html, app.py i templates/operari_hores.html')
print('Còpies de seguretat: operari.py.bak, operari.html.bak i app.py.bak')
