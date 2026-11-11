from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import re
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text

from db import carregar_tasques, guardar_tasques, get_engine
from routes.operari import extreure_historial_hores, calcular_total_formatted, vincular_observacions_historial

fitxatges_bp = Blueprint('fitxatges', __name__)

# Coincideix amb el format històric que usa routes/operari.py.
_REGISTRE = re.compile(
    r'\[(?:([^|]+)\|)?\s*(Temps manual|Cronòmetre|Crono)\s+'
    r'([\d/]+):\s+([\d:]+)\s+a\s+([\d:]+)\s+\(([^)]+)\)\]'
)


def _identitat():
    # A l'admin li cal seleccionar un operari al panell, igual que actualment.
    nom = str(session.get('operari_autenticat') or '').strip()
    if not nom:
        abort(403)
    return nom


def _data_original(valor):
    for fmt in ('%d/%m/%y', '%d/%m/%Y'):
        try:
            return datetime.strptime(valor, fmt).date()
        except ValueError:
            pass
    return None


def _hores(inici, fi):
    a = datetime.strptime(inici, '%H:%M')
    b = datetime.strptime(fi, '%H:%M')
    if b < a:
        b += timedelta(days=1)
    minuts = round((b-a).total_seconds()/60)
    if not 0 < minuts <= 24 * 60:
        raise ValueError('Durada incorrecta')
    return minuts


def _hash(valor):
    return hashlib.sha256(valor.encode('utf-8')).hexdigest()


def _tasca_signatura(t):
    return _hash('|'.join(str(t.get(k, '')) for k in ('Embarcació', 'Titol_Tasca', 'Data_Creacio')))


def _llista_fitxatges(df, operari):
    resultat = []
    for idx, t in df.iterrows():
        task = t.to_dict()
        comentari = str(task.get('Comentaris_Operari') or '')
        registres_notes = vincular_observacions_historial(
            extreure_historial_hores(comentari), task.get('Notes_Text', ''))
        for reg_idx, m in enumerate(_REGISTRE.finditer(comentari)):
            autor, tipus, data_str, inici, fi, _durada = m.groups()
            if (autor or 'General').strip().casefold() != operari.casefold():
                continue
            data = _data_original(data_str)
            if not data:
                continue
            try:
                minuts = _hores(inici, fi)
            except ValueError:
                continue
            resultat.append({
                'index_tasca': int(idx), 'index_registre': reg_idx,
                'signatura_tasca': _tasca_signatura(task),
                'signatura_registre': _hash(m.group(0)),
                'data_iso': data.isoformat(), 'data': data.strftime('%d/%m/%Y'),
                'inici': inici, 'fi': fi, 'durada_minuts': minuts,
                'hores': f'{minuts//60} h {minuts%60:02d} min',
                'tipus': tipus,
                'observacio': registres_notes[reg_idx].get('observacio','') if reg_idx < len(registres_notes) else '',
                'embarcacio': str(task.get('Embarcació') or ''),
                'titol': str(task.get('Titol_Tasca') or ''),
                'arxivada': str(task.get('Estat') or '').strip().casefold() == 'arxivada',
                'estat': str(task.get('Estat') or ''),
            })
    return resultat


def _audit(nom, tasca, tipus, abans, despres):
    """Auditoria independent de la taula tasques (no es perd al recalcular hores)."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError('La traçabilitat de correccions requereix PostgreSQL')
    with engine.begin() as con:
        con.execute(text('''
          CREATE TABLE IF NOT EXISTS fitxatges_auditoria (
            id BIGSERIAL PRIMARY KEY,
            data_canvi TIMESTAMPTZ NOT NULL DEFAULT now(),
            operari TEXT NOT NULL,
            embarcacio TEXT NOT NULL,
            tasca TEXT NOT NULL,
            accio TEXT NOT NULL,
            valor_anterior TEXT NOT NULL,
            valor_nou TEXT NOT NULL
          )
        '''))
        con.execute(text('''
          INSERT INTO fitxatges_auditoria
            (operari,embarcacio,tasca,accio,valor_anterior,valor_nou)
          VALUES (:op,:boat,:task,:accio,:antic,:nou)
        '''), {'op':nom, 'boat':str(tasca.get('Embarcació') or ''),
               'task':str(tasca.get('Titol_Tasca') or ''), 'accio':tipus,
               'antic':abans, 'nou':despres})


@fitxatges_bp.route('/operari/les-meves-hores', methods=['GET'])
def calendari():
    nom = _identitat()
    mes = request.args.get('mes', '')
    try:
        any_, mes_ = map(int, mes.split('-'))
        if not (2020 <= any_ <= 2100 and 1 <= mes_ <= 12):
            raise ValueError()
        primer = date(any_, mes_, 1)
    except (ValueError, TypeError):
        avui = date.today()
        primer = date(avui.year, avui.month, 1)

    if primer.month == 12:
        seguent = date(primer.year+1, 1, 1)
    else:
        seguent = date(primer.year, primer.month+1, 1)
    anterior = (primer-timedelta(days=1)).replace(day=1)
    df = carregar_tasques()
    regs = [r for r in _llista_fitxatges(df, nom)
            if primer.isoformat() <= r['data_iso'] < seguent.isoformat()]
    regs.sort(key=lambda r: (r['data_iso'],r['inici'],r['embarcacio']))
    per_dia = defaultdict(list)
    for reg in regs:
        per_dia[reg['data_iso']].append(reg)
    totals = {dia:sum(r['durada_minuts'] for r in val) for dia,val in per_dia.items()}
    token = session.setdefault('fitxatges_csrf', secrets.token_urlsafe(24))
    return render_template('operari_calendari.html',
        nom=nom, mes=f'{primer.year:04d}-{primer.month:02d}',
        any_=primer.year, mes_=primer.month,
        anterior=f'{anterior.year:04d}-{anterior.month:02d}',
        seguent=f'{seguent.year:04d}-{seguent.month:02d}',
        primer_setmana=primer.weekday(), num_dies=(seguent-primer).days,
        registres_per_dia=dict(per_dia), totals=totals,
        total_mes=sum(totals.values()), csrf=token)


@fitxatges_bp.route('/operari/les-meves-hores/modificar', methods=['POST'])
def modificar():
    nom = _identitat()
    if not secrets.compare_digest(str(request.form.get('csrf') or ''),
                                   str(session.get('fitxatges_csrf') or 'NO_TOKEN')):
        abort(403)
    try:
        idx = int(request.form['index_tasca'])
        reg_idx = int(request.form['index_registre'])
        data = date.fromisoformat(request.form['data'])
        inici = datetime.strptime(request.form['inici'], '%H:%M').strftime('%H:%M')
        fi = datetime.strptime(request.form['fi'], '%H:%M').strftime('%H:%M')
        minuts = _hores(inici, fi)
        if not (2020 <= data.year <= 2100):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        abort(400, 'Data o hores incorrectes')

    df = carregar_tasques()
    if not 0 <= idx < len(df):
        abort(404)
    t = df.iloc[idx].to_dict()
    if str(t.get('Estat') or '').strip().casefold() == 'arxivada':
        abort(403, 'La tasca està arxivada: els fitxatges són de només lectura')
    if _tasca_signatura(t) != request.form.get('signatura_tasca'):
        abort(409, 'La tasca ha canviat. Torna a obrir el calendari')

    comentari = str(t.get('Comentaris_Operari') or '')
    matches = list(_REGISTRE.finditer(comentari))
    if not 0 <= reg_idx < len(matches):
        abort(409, 'El registre ha canviat')
    m = matches[reg_idx]
    autor, tipus, old_date, old_ini, old_fi, _ = m.groups()
    if (autor or 'General').strip().casefold() != nom.casefold():
        abort(403, 'Només pots modificar els teus fitxatges')
    if _hash(m.group(0)) != request.form.get('signatura_registre'):
        abort(409, 'Algú ha modificat aquest fitxatge. Recarrega el calendari')

    data_str = data.strftime('%d/%m/%y')
    nou = f'[{autor or nom} | {tipus} {data_str}: {inici} a {fi} ({minuts//60}h {minuts%60:02d}m)]'
    original = m.group(0)
    if original == nou:
        return redirect(url_for('fitxatges.calendari', mes=data.strftime('%Y-%m')))

    # Corregir també la clau de les observacions associades al tram.
    notes = str(t.get('Notes_Text') or '')
    nova_nota = re.sub(
        r'(\[(?:OBSERVACIÓ|INCIDÈNCIA CRONÒMETRE)\s*\|\s*'+re.escape(nom)+
        r'\s*\|\s*)'+re.escape(old_date)+r'\s+'+re.escape(old_ini)+
        r'-'+re.escape(old_fi)+r'(\s*\|\s*[^\]]+\])',
        lambda mm: (mm.group(1)+data_str+' '+inici+'-'+fi+
                    f' | {minuts//60}h {minuts%60:02d}m]'),
        notes, count=1, flags=re.IGNORECASE
    )

    df.at[idx,'Comentaris_Operari'] = comentari[:m.start()] + nou + comentari[m.end():]
    df.at[idx,'Hores_Imputades'] = calcular_total_formatted(df.at[idx,'Comentaris_Operari'])
    if nova_nota != notes:
        df.at[idx,'Notes_Text'] = nova_nota

    # Escrivim primer l'auditoria; si falla, no alterem l'historial.
    _audit(nom,t,'MODIFICAR',original,nou)
    guardar_tasques(df)
    flash('Fitxatge corregit correctament.', 'success')
    return redirect(url_for('fitxatges.calendari', mes=data.strftime('%Y-%m')))
