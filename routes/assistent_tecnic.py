"""Primera fase: consulta tècnica contextual, sense connexió a portals ni IA."""
from flask import Blueprint, abort, render_template, request, session
from db import carregar_tasques, carregar_embarcacions

assistent_tecnic_bp = Blueprint('assistent_tecnic', __name__)


def _net(valor):
    text = str(valor if valor is not None else '').strip()
    return '' if text.casefold() in ('nan', 'none', 'nat') else text


def _separa(valor):
    # Els camps existents guarden els múltiples motors separats per comes.
    return [_net(x) for x in _net(valor).split(',')]


@assistent_tecnic_bp.route('/operari/tasca/<int:csv_index>/assistent-tecnic', methods=['GET'])
def vista_assistent_tasca(csv_index):
    operari = _net(session.get('operari_autenticat'))
    es_admin = bool(session.get('admin_autenticat'))
    if not (operari or es_admin):
        abort(403)

    tasques = carregar_tasques()
    if not 0 <= csv_index < len(tasques):
        abort(404)
    tasca = tasques.iloc[csv_index]
    assignats = [op.strip().casefold() for op in _net(tasca.get('Operari')).split(',') if op.strip()]
    if not es_admin and operari.casefold() not in assignats:
        abort(403)

    nom_embarcacio = _net(tasca.get('Embarcació'))
    embarcacions = carregar_embarcacions()
    fitxa = None
    if not embarcacions.empty and 'Nom' in embarcacions.columns:
        coincidencies = embarcacions[
            embarcacions['Nom'].astype(str).str.strip().str.casefold() == nom_embarcacio.casefold()
        ]
        if not coincidencies.empty:
            fitxa = coincidencies.iloc[0]

    motors = []
    if fitxa is not None:
        marques = _separa(fitxa.get('Marca_Motor'))
        models = _separa(fitxa.get('Model_Motor'))
        series = _separa(fitxa.get('Num_Serie_Motors'))
        try:
            quantitat = int(float(_net(fitxa.get('Num_Motors')) or '1'))
        except (TypeError, ValueError):
            quantitat = 1
        # Com a màxim 12 motors per evitar que una dada malformada ampliï desmesuradament la pàgina.
        total = min(12, max(1, quantitat, len(marques), len(models), len(series)))
        for i in range(total):
            motors.append({
                'nom': f'Motor {i + 1}',
                'marca': marques[i] if i < len(marques) else (marques[0] if len(marques) == 1 else ''),
                'model': models[i] if i < len(models) else (models[0] if len(models) == 1 else ''),
                'serie': series[i] if i < len(series) else ''
            })
    if not motors:
        motors = [{'nom': 'Motor 1', 'marca': '', 'model': '', 'serie': ''}]
    return render_template('assistent_tecnic.html', motors=motors,
                           embarcacio=nom_embarcacio, titol_tasca=_net(tasca.get('Titol_Tasca')),
                           csv_index=csv_index, fitxa_trobada=(fitxa is not None))
