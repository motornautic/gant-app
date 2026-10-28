"""Assistent tècnic: cerca en índex limitat de documentació oficial Volvo Penta.
No accedeix a VPPN ni confirma compatibilitat per número de sèrie.
"""
import re
import unicodedata
from flask import Blueprint, abort, render_template, request, session
from db import carregar_tasques, carregar_embarcacions

assistent_tecnic_bp = Blueprint('assistent_tecnic', __name__)

FONT = {
    'titol': 'Volvo Penta – Parts & Accessories Catalogue, Maintenance',
    'url': 'https://www.volvopenta.com/-/media/volvopenta/parts/accessories/documents/accessories-catalog.pdf',
    'pagina': '91 (numeració impresa al catàleg)',
}

# Índex acotat i revisable, obtingut de la taula de manteniment del fabricant.
# Aquestes dades NO estan filtrades per número de sèrie.
INDEX = [
    {'familia': 'D4/D6 A–F', 'patro': r'^D[46](?:\b|[- ])', 'variants': 'A-F', 'tipus': 'oli', 'peces': [
        ('22030848', 'Filtre d’oli principal (full flow)'),
        ('22030852', 'Filtre d’oli de derivació (by-pass)'),
    ]},
    {'familia': 'D4/D6 G', 'patro': r'^D[46](?:\b|[- ])', 'variants': 'G', 'tipus': 'oli', 'peces': [
        ('22030848', 'Filtre d’oli principal (full flow)'),
        ('22030852', 'Filtre d’oli de derivació (by-pass)'),
    ]},
    {'familia': 'TAMD41/TMD41/AQD41/AQAD41', 'patro': r'^(?:TAMD41|TMD41|AQD41|AQAD41)', 'variants': 'totes', 'tipus': 'oli', 'peces': [
        ('471034', 'Filtre d’oli del motor'),
    ]},
    {'familia': 'D4/D6 A–F', 'patro': r'^D[46](?:\b|[- ])', 'variants': 'A-F', 'tipus': 'combustible', 'peces': [
        ('21718912', 'Filtre de combustible del motor'),
    ]},
    {'familia': 'D4/D6 G', 'patro': r'^D[46](?:\b|[- ])', 'variants': 'G', 'tipus': 'combustible', 'peces': [
        ('23954708', 'Filtre de combustible del motor (catàleg de manteniment)'),
    ]},
    {'familia': 'TAMD41/TMD41/AQD41/AQAD41', 'patro': r'^(?:TAMD41|TMD41|AQD41|AQAD41)', 'variants': 'totes', 'tipus': 'combustible', 'peces': [
        ('21624740', 'Filtre de combustible'),
    ]},
]


def _net(valor):
    s = str(valor if valor is not None else '').strip()
    return '' if s.casefold() in ('nan', 'none', 'nat') else s


def _separa(valor):
    return [_net(s) for s in _net(valor).split(',')]


def _normalitzar(text):
    text = unicodedata.normalize('NFKD', _net(text).lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def _tipus_consulta(consulta):
    c = _normalitzar(consulta)
    if any(x in c for x in ('oli', 'oil', 'lubric')) and any(x in c for x in ('filtr', 'filter')):
        return 'oli'
    if any(x in c for x in ('gasoil', 'combustible', 'fuel', 'diesel')) and any(x in c for x in ('filtr', 'filter')):
        return 'combustible'
    return None


def _variant(model):
    m = re.search(r'-([A-G])(?:\b|$)', model.upper())
    return m.group(1) if m else ''


def buscar_peces(marca, model, serie, consulta):
    """Retorna únicament coincidències explícites en el petit índex oficial."""
    if not all((marca, model, serie, consulta)):
        return {'error': 'Cal indicar fabricant, model, número de sèrie i peça.'}
    if 'volvo' not in _normalitzar(marca) or 'penta' not in _normalitzar(marca):
        return {'missatge': 'De moment només hi ha documentació indexada de Volvo Penta.', 'peces': []}
    tipus = _tipus_consulta(consulta)
    if not tipus:
        return {'missatge': 'Aquesta consulta encara no està inclosa a la biblioteca indexada. Prova «filtres d’oli» o «filtre de combustible».', 'peces': []}
    variant = _variant(model)
    peces = []
    for entrada in INDEX:
        if entrada['tipus'] != tipus or not re.search(entrada['patro'], model.upper()):
            continue
        if entrada['variants'] == 'A-F' and variant and variant not in 'ABCDEF':
            continue
        if entrada['variants'] == 'G' and variant != 'G':
            continue
        # Sense variant explícita, no es poden triar les taules A-F/G amb seguretat.
        if entrada['variants'] in ('A-F', 'G') and not variant:
            continue
        for ref, descripcio in entrada['peces']:
            peces.append({'referencia': ref, 'descripcio': descripcio, 'familia': entrada['familia'], 'font': FONT})
    if not peces:
        return {'missatge': 'No hi ha una coincidència prou concreta al catàleg indexat per a aquest model. No s’ha assignat cap referència.', 'peces': []}
    return {'peces': peces, 'avis': 'Coincidència pel model i la família del motor. El número de sèrie NO s’ha verificat al despiece específic: comprova les referències al catàleg oficial abans de demanar-les.'}


@assistent_tecnic_bp.route('/operari/tasca/<int:csv_index>/assistent-tecnic', methods=['GET', 'POST'])
def vista_assistent_tasca(csv_index):
    operari = _net(session.get('operari_autenticat'))
    es_admin = bool(session.get('admin_autenticat'))
    if not (operari or es_admin):
        abort(403)
    tasques = carregar_tasques()
    if not 0 <= csv_index < len(tasques):
        abort(404)
    tasca = tasques.iloc[csv_index]
    assignats = [s.strip().casefold() for s in _net(tasca.get('Operari')).split(',') if s.strip()]
    if not es_admin and operari.casefold() not in assignats:
        abort(403)

    nom_embarcacio = _net(tasca.get('Embarcació'))
    embarcacions = carregar_embarcacions()
    fitxa = None
    if not embarcacions.empty and 'Nom' in embarcacions.columns:
        match = embarcacions[embarcacions['Nom'].astype(str).str.strip().str.casefold() == nom_embarcacio.casefold()]
        if not match.empty:
            fitxa = match.iloc[0]
    motors = []
    if fitxa is not None:
        marques, models, series = (_separa(fitxa.get(c)) for c in ('Marca_Motor', 'Model_Motor', 'Num_Serie_Motors'))
        try:
            quantitat = int(float(_net(fitxa.get('Num_Motors')) or '1'))
        except (TypeError, ValueError):
            quantitat = 1
        total = min(12, max(1, quantitat, len(marques), len(models), len(series)))
        for i in range(total):
            motors.append({'nom': f'Motor {i+1}',
                           'marca': marques[i] if i < len(marques) else (marques[0] if len(marques) == 1 else ''),
                           'model': models[i] if i < len(models) else (models[0] if len(models) == 1 else ''),
                           'serie': series[i] if i < len(series) else ''})
    if not motors:
        motors = [{'nom': 'Motor 1', 'marca': '', 'model': '', 'serie': ''}]

    resultat = None
    dades = None
    if request.method == 'POST':
        dades = {k: _net(request.form.get(k))[:300] for k in ('marca', 'model', 'serie')}
        dades['consulta'] = _net(request.form.get('consulta'))[:500]
        dades['motor_idx'] = request.form.get('motor_idx', '0')
        resultat = buscar_peces(dades['marca'], dades['model'], dades['serie'], dades['consulta'])

    return render_template('assistent_tecnic.html', motors=motors, embarcacio=nom_embarcacio,
                           titol_tasca=_net(tasca.get('Titol_Tasca')), csv_index=csv_index,
                           fitxa_trobada=(fitxa is not None), resultat=resultat, dades=dades,
                           font_oficial=FONT)

