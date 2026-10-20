from flask import Blueprint, render_template, request, redirect, url_for, current_app, jsonify, session, flash, make_response, abort
from datetime import datetime, timedelta
import pandas as pd
import re, os, json, random, string
import urllib.parse
import secrets, hashlib, hmac, ssl
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from db import carregar_operaris, carregar_tasques, guardar_tasques, carregar_articles, carregar_taula, get_engine
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 🚀 Declaració del Blueprint
operari_bp = Blueprint('operari', __name__)

# ---------------------------------------------------------------------
# FUNCIONS AUXILIARS DE PROCESSAMENT
# ---------------------------------------------------------------------

def extreure_historial_hores(text_comentaris):
    if not text_comentaris or pd.isna(text_comentaris): 
        return []
    registres = []
    patro = r'\[(?:([^|]+)\|)?\s*(?:Temps manual|Cronòmetre|Crono)\s+([\d\/]+):\s+([\d:]+)\s+a\s+([\d:]+)\s+\(([^)]+)\)\]'
    coincidencies = list(re.finditer(patro, str(text_comentaris)))
    for idx, match in enumerate(coincidencies):
        op, data, h_inici, h_fi, durada = match.groups()
        registres.append({
            "reg_index": idx, 
            "operari": op.strip() if op else "General",
            "data": data, 
            "inici": h_inici, 
            "fi": h_fi, 
            "total": durada, 
            "raw_text": match.group(0)
        })
    return registres

def vincular_observacions_historial(registres, notes):
    """Relaciona observacions antigues i noves amb el període concret del cronòmetre."""
    patron = re.compile(
        r"\[(?:INCIDÈNCIA CRONÒMETRE|OBSERVACIÓ)\s*\|\s*([^|\]\n]+)"
        r"\s*\|\s*(\d{2}/\d{2}/\d{2})\s+"
        r"(\d{2}:\d{2})-(\d{2}:\d{2})\s*\|\s*[^\]]+\]"
        r"\s*\n(.*?)(?=\n\s*\n|\n\[(?:INCIDÈNCIA CRONÒMETRE|OBSERVACIÓ)\s*\||\Z)",
        re.S | re.I
    )
    observacions = {}
    for m in patron.finditer(str(notes or '')):
        op, dia, inici, fi, contingut = m.groups()
        clau = (op.strip().casefold(), dia, inici, fi)
        contingut = contingut.strip()
        if contingut:
            observacions.setdefault(clau, []).append(contingut)
    for reg in registres:
        clau = (str(reg['operari']).strip().casefold(), reg['data'], reg['inici'], reg['fi'])
        disponibles = observacions.get(clau, [])
        reg['observacio'] = disponibles.pop(0) if disponibles else ''
    return registres


def extreure_historial_material(text_material):
    if not text_material or pd.isna(text_material): 
        return []
    registres = []
    patro = r'\[([\d\/]+ - [\d:]+)\|\s*(WhatsApp|Email)\|\s*Estat:\s*([^\|]+)\|\s*Material:\s*([^\]]+)\]'
    coincidencies = list(re.finditer(patro, str(text_material)))
    for idx, match in enumerate(coincidencies):
        data_hora, via, estat, detall = match.groups()
        registres.append({
            "mat_index": idx,
            "data_hora": data_hora,
            "via": via,
            "estat": estat.strip(),
            "detall": detall.strip(),
            "raw_text": match.group(0)
        })
    return registres

def extreure_historial_material_no_subministrat(text_mat_no_sub):
    if not text_mat_no_sub or pd.isna(text_mat_no_sub) or str(text_mat_no_sub).strip().lower() == "nan": 
        return []
    registres = []
    linies = [l.strip() for l in str(text_mat_no_sub).split("\n") if l.strip()]
    for idx, l in enumerate(linies):
        if l.startswith("[") and "Ref:" in l:
            try:
                data_hora = l.split("|")[0].replace("[", "").strip()
                ref_part = l.split("Ref:")[1].split("| Op:")[0].strip()
                op_part = l.split("| Op:")[1].replace("]", "").strip() if "| Op:" in l else ""
                
                registres.append({
                    "mat_idx": idx,
                    "data_hora": data_hora,
                    "referencia": ref_part,
                    "operari": op_part,
                    "raw_text": l
                })
            except Exception:
                registres.append({
                    "mat_idx": idx,
                    "data_hora": "",
                    "referencia": l.replace("[", "").replace("]", ""),
                    "operari": "",
                    "raw_text": l
                })
        else:
            registres.append({
                "mat_idx": idx,
                "data_hora": "",
                "referencia": l,
                "operari": "",
                "raw_text": l
            })
    return registres

def extreure_checklist_items(text_detall):
    if not text_detall or pd.isna(text_detall): 
        return []
    linees = [l.strip() for l in str(text_detall).split("\n") if l.strip()]
    items = []
    for idx, l in enumerate(linees):
        es_fet = l.startswith("[x]") or l.startswith("[X]")
        text_net = l.replace("[x]", "").replace("[X]", "").replace("[ ]", "").strip()
        items.append({
            "item_index": idx,
            "fet": es_fet,
            "text": text_net
        })
    return items

def calcular_total_formatted(text_comentaris):
    registres = extreure_historial_hores(text_comentaris)
    if not registres: 
        return "0h 00m"
    total_segons = 0
    for r in registres:
        try:
            t_inici = datetime.strptime(r["inici"], "%H:%M")
            t_fi = datetime.strptime(r["fi"], "%H:%M")
            if t_fi < t_inici: 
                t_fi += pd.Timedelta(days=1)
            total_segons += int((t_fi - t_inici).total_seconds())
        except Exception: 
            pass
    
    hores = int(total_segons // 3600)
    minuts = int(round((total_segons % 3600) / 60))
    if minuts == 60:
        hores += 1
        minuts = 0
    return f"{hores}h {minuts:02d}m"

def carregar_df_operaris():
    # La base de dades PostgreSQL és la font de veritat a Railway.
    return carregar_taula('operaris', 'operaris.csv',
                         ['Nom', 'Cognoms', 'Telefon', 'Email', 'Password', 'Reset_Code', 'Reset_Expiry'])


def _es_password_valida(contrasenya_entrada, guardada, nom):
    actual = (guardada or '').strip()
    if actual.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(actual, contrasenya_entrada)
    # Compatibilitat amb contrasenyes antigues, fins que es canviïn.
    antiga = actual or nom
    return hmac.compare_digest(contrasenya_entrada.upper(), antiga.upper())


def _guardar_camps_operari(nom, camps):
    # Actualitza exclusivament l'operari corresponent, no tota la taula.
    engine = get_engine()
    if engine is not None:
        camps_permesos = {'Password', 'Reset_Code', 'Reset_Expiry'}
        if not camps or not set(camps).issubset(camps_permesos):
            return False
        updates = ', '.join('"' + camp + '" = :' + camp for camp in camps)
        with engine.begin() as conn:
            result = conn.execute(
                text(f'UPDATE operaris SET {updates} WHERE LOWER(TRIM("Nom")) = :nom'),
                {**camps, 'nom': nom.casefold()}
            )
            return result.rowcount == 1
    # Mode de desenvolupament sense PostgreSQL.
    df = carregar_df_operaris()
    match = df.index[df['Nom'].astype(str).str.strip().str.casefold() == nom.casefold()]
    if len(match) != 1:
        return False
    for k, v in camps.items():
        df.at[match[0], k] = v
    df.to_csv(os.path.join(os.getcwd(), 'operaris.csv'), index=False)
    return True


def _correu_recuperacio(destinatari, enllac):
    host = os.environ.get('SMTP_HOST') or current_app.config.get('MAIL_SERVER')
    port = int(os.environ.get('SMTP_PORT') or current_app.config.get('MAIL_PORT', 465))
    usuari = os.environ.get('SMTP_USERNAME') or current_app.config.get('MAIL_USERNAME')
    # No utilitzem contrasenyes incloses en el codi. Cal SMTP_PASSWORD a Railway.
    clau = os.environ.get('SMTP_PASSWORD')
    remitent = os.environ.get('SMTP_FROM') or usuari
    if not all((host, usuari, clau, remitent)):
        raise RuntimeError('Falta configurar SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM')

    msg = MIMEText(
        'Hem rebut una sol·licitud per canviar la teva contrasenya de MotorNautic.\n\n'
        f'Obre aquest enllaç (vàlid 15 minuts i d’un sol ús):\n{enllac}\n\n'
        'Si no ho has sol·licitat tu, ignora aquest missatge.', 'plain', 'utf-8'
    )
    msg['Subject'] = 'MotorNautic - Recuperació de contrasenya'
    msg['From'] = remitent
    msg['To'] = destinatari
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as smtp:
            smtp.login(usuari, clau)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(usuari, clau)
            smtp.send_message(msg)


def _validar_token_reset(token):
    if not token or len(token) > 160:
        return None
    hash_token = hashlib.sha256(token.encode('utf-8')).hexdigest()
    df = carregar_df_operaris()
    if df.empty:
        return None
    coincidencies = df[df['Reset_Code'].astype(str) == hash_token]
    if len(coincidencies) != 1:
        return None
    registre = coincidencies.iloc[0]
    try:
        expiracio = datetime.fromisoformat(str(registre['Reset_Expiry']))
        if datetime.utcnow() > expiracio:
            return None
    except (ValueError, TypeError):
        return None
    return str(registre['Nom'])


# ---------------------------------------------------------------------
# RUTES DE L'OPERARI
# ---------------------------------------------------------------------

@operari_bp.route("/operari", methods=["GET", "POST"])
def vista_operari():
    # Desa els checks sense modificar l'estat general de la tasca.
    if request.method == "POST":
        if request.form.get("accio") != "toggle_checklist":
            return jsonify({"ok": False, "error": "Acció no permesa"}), 400
        operari_actual = (session.get("operari_autenticat") or "").strip()
        es_admin_actual = bool(session.get("admin_autenticat"))
        if not (operari_actual or es_admin_actual):
            return jsonify({"ok": False, "error": "Sessió caducada"}), 401
        try:
            tasca_idx = int(request.form.get("csv_index", ""))
            item_idx = int(request.form.get("item_index", ""))
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Índex invàlid"}), 400
        valor = request.form.get("fet")
        if valor not in ("0", "1"):
            return jsonify({"ok": False, "error": "Valor invàlid"}), 400
        df = carregar_tasques()
        if not 0 <= tasca_idx < len(df):
            return jsonify({"ok": False, "error": "Tasca inexistent"}), 404
        assignats = [n.strip().casefold() for n in str(df.iloc[tasca_idx].get("Operari", "")).split(",") if n.strip()]
        if not es_admin_actual and operari_actual.casefold() not in assignats:
            return jsonify({"ok": False, "error": "Tasca no assignada"}), 403

        detall = str(df.iloc[tasca_idx].get("Tasques_Detall", "") or "")
        if detall.lower() in ("nan", "none"):
            detall = ""
        linies = detall.splitlines(keepends=True)
        posicions = [i for i, linia in enumerate(linies) if linia.strip()]
        if not 0 <= item_idx < len(posicions):
            return jsonify({"ok": False, "error": "Element inexistent"}), 404
        pos = posicions[item_idx]
        linia = linies[pos]
        salt = "\r\n" if linia.endswith("\r\n") else "\n" if linia.endswith("\n") else ""
        contingut = linia[:-len(salt)] if salt else linia
        # Manté el text i la indentació originals, modifica només la marca.
        coincidencia = re.match(r"^(\s*)(?:\[(?:[xX]| )\]\s*)?(.*)$", contingut)
        prefix, text_item = coincidencia.groups()
        if not text_item.strip():
            return jsonify({"ok": False, "error": "Element buit"}), 400
        linies[pos] = f"{prefix}{'[x]' if valor == '1' else '[ ]'} {text_item}{salt}"
        df.at[df.index[tasca_idx], "Tasques_Detall"] = "".join(linies)
        guardar_tasques(df)
        return jsonify({"ok": True, "fet": valor == "1"})
    operaris = carregar_operaris()
    es_admin = bool(session.get("admin_autenticat"))
    
    if request.args.get("triar_operari") == "1":
        return render_template("login_operari.html", operaris=operaris, operari_sel=None, error=request.args.get("error_auth"))

    operari_sel = session.get("operari_autenticat")

    # Si NO hi ha cap operari seleccionat ni guardat, demanem selecció/login d'operari
    if not operari_sel:
        if es_admin and operaris:
            operari_sel = operaris[0]
            session["operari_autenticat"] = operari_sel
        else:
            return render_template("login_operari.html", operaris=operaris, operari_sel=None, error=request.args.get("error_auth"))

    confirm_idx = request.args.get("confirm_idx", type=int)
    edit_reg_info = {"task_idx": request.args.get("edit_task_idx", type=int), "reg_idx": request.args.get("edit_reg_idx", type=int)}
    
    df_articles = carregar_articles()
    llista_articles = []
    if not df_articles.empty:
        for _, row in df_articles.iterrows():
            ref = str(row.get("Ref", "")).strip()
            ref_int = str(row.get("Ref_Interna", "")).strip()
            desc = str(row.get("Descripcio", "")).strip()
            stock = str(row.get("Stock", "0")).strip()
            ubicacio = str(row.get("Ubicacio", "")).strip()
            
            if ref:
                etiqueta = ref
                if ref_int: etiqueta += f" (INT: {ref_int})"
                if desc: etiqueta += f" - {desc}"
                
                detalls_extra = []
                if stock: detalls_extra.append(f"Stock: {stock}")
                if ubicacio: detalls_extra.append(f"Ubicació: {ubicacio}")
                
                if detalls_extra:
                    etiqueta += f" [{ ' | '.join(detalls_extra) }]"
                
                llista_articles.append({
                    "ref": ref,
                    "etiqueta": etiqueta
                })

    df_tasques = carregar_tasques()
    tasques_op = []
    
    perfil_data = {"Nom": operari_sel, "Cognoms": "", "Telefon": "", "Email": ""}
    df_op = carregar_df_operaris()
    if not df_op.empty and "Nom" in df_op.columns and operari_sel:
        row_op = df_op[df_op["Nom"].str.upper() == operari_sel.upper()]
        if not row_op.empty:
            perfil_data["Cognoms"] = str(row_op.iloc[0].get("Cognoms", "")).strip()
            perfil_data["Telefon"] = str(row_op.iloc[0].get("Telefon", "")).strip()
            perfil_data["Email"] = str(row_op.iloc[0].get("Email", "")).strip()

    if not df_tasques.empty and operari_sel:
        for idx, row in df_tasques.iterrows():
            operaris_assignats = [op.strip() for op in str(row.get("Operari", "")).split(",") if op.strip()]
            data_inici_val = str(row.get("Data_Inici", "")).strip()
            estat_val = str(row.get("Estat", "")).strip()
            
            if operari_sel in operaris_assignats and estat_val not in ["Arxivada", "Pressupost"] and data_inici_val != "":
                item = row.to_dict()
                item["csv_index"] = idx
                
                crono_dict = {}
                json_str = str(item.get("Inici_Crono", ""))
                if json_str.startswith("{"):
                    try: crono_dict = json.loads(json_str)
                    except Exception: pass
                elif json_str:
                    crono_dict = {"General": json_str}
                
                item["crono_actiu_operari"] = crono_dict.get(operari_sel, "")
                item["hores_formatted"] = calcular_total_formatted(item.get("Comentaris_Operari", ""))
                item["historial_hores"] = vincular_observacions_historial(
                    extreure_historial_hores(item.get("Comentaris_Operari", "")),
                    item.get("Notes_Text", "")
                )
                item["historial_material"] = extreure_historial_material(item.get("Material_Demanat", ""))
                item["checklist"] = extreure_checklist_items(item.get("Tasques_Detall", ""))
                item["historial_mat_no_subministrat"] = extreure_historial_material_no_subministrat(item.get("Material_No_Subministrat", ""))
                item["notes_visibles"] = str(item.get("Notes_Text", "") or "").replace("INCIDÈNCIA CRONÒMETRE", "OBSERVACIÓ")

                emb_folder = secure_filename(item.get("Embarcació", "GENERAL"))
                folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
                fotos = []
                if os.path.exists(folder_path):
                    fotos = [f"/uploads/{emb_folder}/{f}" for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                item["fotos"] = fotos
                tasques_op.append(item)

    now_date = datetime.now().strftime("%Y-%m-%d")

    # 🎯 ATENCIÓ: ARA CARREGA SEMPRE 'operari.html' PER AL PANELL MÒBIL D'OPERARIS
    response = make_response(render_template(
        "operari.html", 
        operaris=operaris, 
        operari_sel=operari_sel, 
        perfil=perfil_data, 
        tasques=tasques_op, 
        confirm_idx=confirm_idx, 
        edit_reg_info=edit_reg_info, 
        articles=llista_articles, 
        es_admin=es_admin,
        now_date=now_date
    ))
    
    if operari_sel:
        response.set_cookie("operari_saved", operari_sel, max_age=30*24*3600)
        
    return response

@operari_bp.route("/login_operari", methods=["POST"])
def login_operari():
    operari_sel = (request.form.get('operari') or '').strip()
    password_input = request.form.get('password') or ''
    df_operaris = carregar_df_operaris()
    if not df_operaris.empty:
        coincidencies = df_operaris[df_operaris['Nom'].astype(str).str.casefold() == operari_sel.casefold()]
        if len(coincidencies) == 1:
            fila = coincidencies.iloc[0]
            nom_real = str(fila['Nom'])
            if _es_password_valida(password_input, str(fila.get('Password','')), nom_real):
                session['operari_autenticat'] = nom_real
                resp = make_response(redirect(url_for('operari.vista_operari')))
                resp.set_cookie('operari_saved', nom_real, max_age=30*24*3600, samesite='Lax')
                return resp
    return redirect(url_for('operari.vista_operari', triar_operari=1, error_auth=1))


@operari_bp.route("/canviar_operari_admin", methods=["POST"])
def canviar_operari_admin():
    if not session.get("admin_autenticat"):
        return redirect(url_for("vista_login_admin"))

    nom = (request.form.get("operari") or "").strip()
    operaris_disponibles = carregar_operaris()
    seleccionat = next(
        (op for op in operaris_disponibles if str(op).strip().casefold() == nom.casefold()),
        None
    )
    if seleccionat is None:
        return redirect(url_for("operari.vista_operari"))

    session["operari_autenticat"] = seleccionat
    resposta = make_response(redirect(url_for("operari.vista_operari")))
    resposta.set_cookie("operari_saved", seleccionat, max_age=30*24*3600, samesite="Lax")
    return resposta


@operari_bp.route("/logout_operari", methods=["POST"])
def logout_operari():
    session.pop("operari_autenticat", None)
    response = make_response(redirect(url_for("operari.vista_operari", triar_operari=1)))
    response.delete_cookie("operari_saved")
    return response

@operari_bp.route("/iniciar_crono", methods=["POST"])
def iniciar_crono():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip() or request.cookies.get("operari_saved", "").strip()
    
    if operari_sel:
        session["operari_autenticat"] = operari_sel

    df = carregar_tasques()
    if 0 <= idx < len(df) and operari_sel:
        crono_dict = {}
        json_str = str(df.at[idx, "Inici_Crono"])
        if json_str.startswith("{"):
            try: crono_dict = json.loads(json_str)
            except Exception: pass
            
        crono_dict[operari_sel] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df.at[idx, "Inici_Crono"] = json.dumps(crono_dict)
        df.at[idx, "Estat"] = "En Curs"
        guardar_tasques(df)
        
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/aturar_crono", methods=["POST"])
def aturar_crono():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip() or request.cookies.get("operari_saved", "").strip()
    
    if operari_sel:
        session["operari_autenticat"] = operari_sel

    accio_aturar = request.form.get("accio_aturar", "continuar").strip()

    df = carregar_tasques()
    if 0 <= idx < len(df) and operari_sel:
        crono_dict = {}
        json_str = str(df.at[idx, "Inici_Crono"])
        if json_str.startswith("{"):
            try: crono_dict = json.loads(json_str)
            except Exception: pass
        elif json_str:
            crono_dict = {operari_sel: json_str}
            
        inici_str = crono_dict.get(operari_sel, "")
        if inici_str:
            try:
                t_inici = datetime.strptime(inici_str, "%Y-%m-%d %H:%M:%S")
                t_fi = datetime.now()
                diff_segons = max(0, int((t_fi - t_inici).total_seconds()))
                
                h_int = int(diff_segons // 3600)
                m_int = int(round((diff_segons % 3600) / 60))
                if m_int == 60:
                    h_int += 1
                    m_int = 0
                
                data_avui = t_fi.strftime("%d/%m/%y")
                hora_i = t_inici.strftime("%H:%M")
                hora_f = t_fi.strftime("%H:%M")
                
                nova_nota = f"[{operari_sel} | Crono {data_avui}: {hora_i} a {hora_f} ({h_int}h {m_int:02d}m)]"
                
                com_actual = df.at[idx, "Comentaris_Operari"]
                nou_com = f"{com_actual} | {nova_nota}" if com_actual else nova_nota
                df.at[idx, "Comentaris_Operari"] = nou_com
                df.at[idx, "Hores_Imputades"] = calcular_total_formatted(nou_com)

                # Incidències d'aquest període, sense sobreescriure les notes existents.
                observacions = (request.form.get("observacions_crono") or "").strip()[:4000]
                if observacions:
                    if "Notes_Text" not in df.columns:
                        df["Notes_Text"] = ""
                    anterior = str(df.at[idx, "Notes_Text"] or "").strip()
                    if anterior.lower() in ("nan", "none"):
                        anterior = ""
                    capcalera = (
                        f"[OBSERVACIÓ | {operari_sel} | {data_avui} "
                        f"{hora_i}-{hora_f} | {h_int}h {m_int:02d}m]"
                    )
                    entrada = f"{capcalera}\n{observacions}"
                    df.at[idx, "Notes_Text"] = f"{anterior}\n\n{entrada}" if anterior else entrada

            except Exception as e:
                print(f"Error calculant crono: {e}")
                
            crono_dict.pop(operari_sel, None)
            df.at[idx, "Inici_Crono"] = json.dumps(crono_dict) if crono_dict else ""
            # Continuar: mantenir l'estat actual de la tasca.
            # Finalitzar: marcar-la com a finalitzada.
            if accio_aturar == "finalitzar":
                df.at[idx, "Estat"] = "Finalitzada"
            guardar_tasques(df)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel, confirm_idx=idx))

@operari_bp.route("/afegir_temps_manual", methods=["POST"])
def afegir_temps_manual():
    idx = int(request.form.get("csv_index"))
    hora_inici, hora_fi = request.form.get("hora_inici"), request.form.get("hora_fi")
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    
    data_imp_raw = request.form.get("data_imputacio", "").strip()
    if data_imp_raw:
        try:
            data_formatted = datetime.strptime(data_imp_raw, "%Y-%m-%d").strftime("%d/%m/%y")
        except Exception:
            data_formatted = datetime.now().strftime("%d/%m/%y")
    else:
        data_formatted = datetime.now().strftime("%d/%m/%y")

    t_inici, t_fi = datetime.strptime(hora_inici, "%H:%M"), datetime.strptime(hora_fi, "%H:%M")
    if t_fi < t_inici: t_fi += pd.Timedelta(days=1)
    
    diff_segons = int((t_fi - t_inici).total_seconds())
    h_int = int(diff_segons // 3600)
    m_int = int(round((diff_segons % 3600) / 60))
    if m_int == 60:
        h_int += 1
        m_int = 0
    
    df = carregar_tasques()
    
    nova_nota = f"[{operari_sel} | Temps manual {data_formatted}: {hora_inici} a {hora_fi} ({h_int}h {m_int:02d}m)]"
    
    com_actual = df.at[idx, "Comentaris_Operari"]
    nou_com = f"{com_actual} | {nova_nota}" if com_actual else nova_nota
    df.at[idx, "Comentaris_Operari"] = nou_com
    df.at[idx, "Hores_Imputades"] = calcular_total_formatted(nou_com)

    # Vinculem les observacions manuals amb aquest període d'hores.
    # Mateix format que les observacions del cronòmetre: la icona de nota
    # apareix automàticament en l'historial del període corresponent.
    observacions = (request.form.get("observacions_manual") or "").strip()[:4000]
    if observacions:
        if "Notes_Text" not in df.columns:
            df["Notes_Text"] = ""
        anterior = str(df.at[idx, "Notes_Text"] or "").strip()
        if anterior.lower() in ("nan", "none"):
            anterior = ""
        capcalera = (
            f"[OBSERVACIÓ | {operari_sel} | {data_formatted} "
            f"{hora_inici}-{hora_fi} | {h_int}h {m_int:02d}m]"
        )
        entrada = f"{capcalera}\n{observacions}"
        df.at[idx, "Notes_Text"] = f"{anterior}\n\n{entrada}" if anterior else entrada

    if request.form.get("marcar_finalitzada"): 
        df.at[idx, "Estat"] = "Finalitzada"
    else:
        df.at[idx, "Estat"] = "En Curs"
        
    guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/registrar_sollicitud_material", methods=["POST"])
def registrar_sollicitud_material():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    material_text = request.form.get("material_text", "").strip()
    via = request.form.get("via", "WhatsApp")
    
    if material_text:
        df = carregar_tasques()
        if 0 <= idx < len(df):
            data_hora = datetime.now().strftime("%d/%m/%Y - %H:%M")
            nova_entrada = f"[{data_hora}|{via}|Estat:Pendent|Material:{material_text}]"
            
            mat_actual = df.at[idx, "Material_Demanat"] if "Material_Demanat" in df.columns else ""
            df.at[idx, "Material_Demanat"] = f"{mat_actual} {nova_entrada}".strip()
            df.at[idx, "Estat"] = "Esperant Recanvi"
            
            guardar_tasques(df)
            
            embarcacio = df.at[idx, "Embarcació"]
            tasca_titol = df.at[idx, "Titol_Tasca"]
            
            msg = f"📦 *SOL·LICITUD DE RECANVI*\n⛵ *Embarcació:* {embarcacio}\n📋 *Tasca:* {tasca_titol}\n👷 *Operari:* {operari_sel}\n\n📝 *Material:* {material_text}"
            
            if via == "WhatsApp":
                url_wa = f"https://wa.me/?text={urllib.parse.quote(msg)}"
                return redirect(url_wa)
            elif via == "Email":
                subject = f"Sol·licitud de Recanvi: {embarcacio} - {tasca_titol}"
                body = f"SOL·LICITUD DE RECANVI\n\nEmbarcació: {embarcacio}\nTasca: {tasca_titol}\nOperari: {operari_sel}\n\nMaterial Sol·licitat:\n{material_text}"
                url_mail = f"mailto:admin@motornautic.com?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
                return redirect(url_mail)

    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/canviar_estat_material", methods=["POST"])
def canviar_estat_material():
    idx = int(request.form.get("csv_index"))
    mat_idx = int(request.form.get("mat_index"))
    nou_estat = request.form.get("nou_estat")
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    redirect_to = request.form.get("redirect_to", "operari")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        mat_actual = df.at[idx, "Material_Demanat"]
        registres = extreure_historial_material(mat_actual)
        
        if 0 <= mat_idx < len(registres):
            reg = registres[mat_idx]
            text_antic = reg["raw_text"]
            
            if nou_estat == "Eliminar":
                nou_text_mat = mat_actual.replace(text_antic, "").strip()
                df.at[idx, "Material_Demanat"] = nou_text_mat
            else:
                text_nou = f"[{reg['data_hora']}|{reg['via']}|Estat:{nou_estat}|Material:{reg['detall']}]"
                df.at[idx, "Material_Demanat"] = mat_actual.replace(text_antic, text_nou)
                
            guardar_tasques(df)
            
    if redirect_to == "tasques":
        return redirect(url_for("tasques.vista_tasques", view_idx=idx))
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/pujar_foto", methods=["POST"])
def pujar_foto():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    file = request.files.get("foto")
    if file and file.filename != '':
        df = carregar_tasques()
        emb_folder = secure_filename(df.at[idx, "Embarcació"])
        dest_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
        os.makedirs(dest_dir, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        file.save(os.path.join(dest_dir, filename))
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/confirmar_finalitzacio", methods=["POST"])
def confirmar_finalitzacio():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    es_finalitzada = request.form.get("es_finalitzada")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        if es_finalitzada == "1":
            df.at[idx, "Estat"] = "Finalitzada"
        else:
            df.at[idx, "Estat"] = "En Curs"
            
        guardar_tasques(df)
        
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/eliminar_registre_hora", methods=["POST"])
def eliminar_registre_hora():
    idx, reg_idx = int(request.form.get("csv_index")), int(request.form.get("reg_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    df = carregar_tasques()
    
    if 0 <= idx < len(df):
        com_actual = str(df.at[idx, "Comentaris_Operari"])
        registres = extreure_historial_hores(com_actual)
        
        if 0 <= reg_idx < len(registres):
            text_a_esborrar = registres[reg_idx]["raw_text"]
            nou_comentari = com_actual.replace(text_a_esborrar, "").replace(" |  | ", " | ").strip(" | ")
            
            hores_formatades = calcular_total_formatted(nou_comentari)
            df.at[idx, "Comentaris_Operari"] = nou_comentari
            df.at[idx, "Hores_Imputades"] = hores_formatades
            
            registres_restants = extreure_historial_hores(nou_comentari)
            crono_actiu = str(df.at[idx, "Inici_Crono"]).strip()
            es_crono_buit = not crono_actiu or crono_actiu == "{}" or crono_actiu == "nan"
            
            if (hores_formatades == "0h 00m" or not registres_restants) and es_crono_buit:
                df.at[idx, "Estat"] = "Pendent"
                
            guardar_tasques(df)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/guardar_notes_operari", methods=["POST"])
def guardar_notes_operari():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    notes_text = request.form.get("notes_operari", "").strip()
    df = carregar_tasques()
    if "Notes_Text" not in df.columns: df["Notes_Text"] = ""
    df.at[idx, "Notes_Text"] = notes_text
    guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/reobrir_tasca", methods=["POST"])
def reobrir_tasca():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    df = carregar_tasques()
    df.at[idx, "Estat"] = "Pendent"
    guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/afegir_operari", methods=["POST"])
def afegir_operari():
    nom_operari = request.form.get("nom_operari", "").strip()
    redirect_to = request.form.get("redirect_to", "operari")
    
    if nom_operari:
        fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
        df_operaris = carregar_df_operaris()

        if "Nom" not in df_operaris.columns: df_operaris["Nom"] = ""
        if "Password" not in df_operaris.columns: df_operaris["Password"] = ""

        llista_noms = [str(n).strip().upper() for n in df_operaris["Nom"].tolist() if str(n).strip()]
        
        if nom_operari.upper() not in llista_noms:
            nou_df = pd.DataFrame([{"Nom": nom_operari, "Cognoms": "", "Telefon": "", "Email": "", "Password": nom_operari, "Reset_Code": "", "Reset_Expiry": ""}])
            df_operaris = pd.concat([df_operaris, nou_df], ignore_index=True)
            df_operaris.to_csv(fitxer_op, index=False)

    if redirect_to == "tasques":
        return redirect(url_for("tasques.vista_tasques"))
    return redirect(url_for("operari.vista_operari", operari=nom_operari))

@operari_bp.route("/canviar_contrasenya", methods=["POST"])
def canviar_contrasenya():
    nom = (session.get('operari_autenticat') or '').strip()
    actual = request.form.get('pwd_actual') or ''
    nova = request.form.get('pwd_nova') or ''
    if not nom or len(nova) < 8:
        return redirect(url_for('operari.vista_operari', pwd_err=1))
    df = carregar_df_operaris()
    match = df[df['Nom'].astype(str).str.casefold() == nom.casefold()]
    if len(match) != 1 or not _es_password_valida(actual, str(match.iloc[0].get('Password','')), nom):
        return redirect(url_for('operari.vista_operari', pwd_err=1))
    try:
        ok = _guardar_camps_operari(nom, {'Password': generate_password_hash(nova)})
    except Exception:
        current_app.logger.exception('Error guardant contrasenya operari')
        ok = False
    return redirect(url_for('operari.vista_operari', **({'pwd_ok': 1} if ok else {'pwd_err': 1})))


@operari_bp.route('/sollicitar_recuperacio', methods=['POST'])
def sollicitar_recuperacio():
    email = (request.form.get('email') or '').strip().casefold()
    # Missatge sempre genèric per no revelar quins correus tenen compte.
    msg = 'Si el correu està registrat, rebràs un enllaç per canviar la contrasenya.'
    if not email or len(email) > 254:
        return redirect(url_for('operari.vista_operari', triar_operari=1, reset_enviat=1))
    df = carregar_df_operaris()
    if not df.empty and 'Email' in df.columns:
        files = df[df['Email'].astype(str).str.strip().str.casefold() == email]
        if len(files) == 1:
            nom = str(files.iloc[0]['Nom']).strip()
            token = secrets.token_urlsafe(32)
            hash_token = hashlib.sha256(token.encode('utf-8')).hexdigest()
            expiracio = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
            enllac = url_for('operari.validar_codi_recuperacio', token=token, _external=True)
            try:
                if _guardar_camps_operari(nom, {'Reset_Code': hash_token, 'Reset_Expiry': expiracio}):
                    _correu_recuperacio(str(files.iloc[0]['Email']).strip(), enllac)
            except Exception:
                current_app.logger.exception('Error enviant recuperació operari')
    return redirect(url_for('operari.vista_operari', triar_operari=1, reset_enviat=1))


@operari_bp.route('/validar_codi_recuperacio', methods=['GET', 'POST'])
def validar_codi_recuperacio():
    token = (request.values.get('token') or '').strip()
    nom = _validar_token_reset(token)
    if not nom:
        return render_template('reset_operari.html', token='', error='Enllaç invàlid o caducat.'), 400
    if request.method == 'GET':
        return render_template('reset_operari.html', token=token, error=None)

    nova = request.form.get('nova_password') or ''
    confirmacio = request.form.get('confirmar_password') or ''
    if len(nova) < 8 or nova != confirmacio:
        return render_template('reset_operari.html', token=token, error='La contrasenya ha de tenir almenys 8 caràcters i coincidir.'), 400
    try:
        engine = get_engine()
        if engine is not None:
            # Consum atòmic del token: evita que es faci servir una segona vegada.
            with engine.begin() as conn:
                result = conn.execute(text('UPDATE operaris SET "Password" = :pwd, "Reset_Code" = :empty, "Reset_Expiry" = :empty WHERE LOWER(TRIM("Nom")) = :nom AND "Reset_Code" = :token'),
                    {'pwd': generate_password_hash(nova), 'nom': nom.casefold(), 'token': hashlib.sha256(token.encode()).hexdigest(), 'empty': ''})
                ok = result.rowcount == 1
        else:
            ok = _guardar_camps_operari(nom, {'Password': generate_password_hash(nova), 'Reset_Code': '', 'Reset_Expiry': ''})
    except Exception:
        current_app.logger.exception('Error restablint contrasenya')
        ok = False
    if not ok:
        return render_template('reset_operari.html', token='', error='No s’ha pogut actualitzar la contrasenya. Torna a sol·licitar l’enllaç.'), 400
    session.pop('operari_autenticat', None)
    response = make_response(redirect(url_for('operari.vista_operari', triar_operari=1, reset_ok=1)))
    response.delete_cookie('operari_saved')
    return response


@operari_bp.route("/recuperar_contrasenya", methods=["POST"])
def recuperar_contrasenya():
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    via = request.form.get("via", "WhatsApp")
    
    msg = f"🔑 *SOL·LICITUD DE RECUPERACIÓ DE CONTRASENYA*\n👷 *Operari:* {operari_sel}\n\nHola Admin, he oblidat la meva contrasenya per accedir al panell de treball."
    
    if via == "WhatsApp":
        url_wa = f"https://wa.me/?text={urllib.parse.quote(msg)}"
        return redirect(url_wa)
    else:
        subject = f"Recuperació de contrasenya: {operari_sel}"
        url_mail = f"mailto:admin@motornautic.com?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(msg)}"
        return redirect(url_mail)

@operari_bp.route("/registrar_material_no_subministrat", methods=["POST"])
def registrar_material_no_subministrat():
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip() or request.cookies.get("operari_saved", "").strip()
    
    try:
        idx_raw = request.form.get("csv_index")
        referencia_input = request.form.get("referencia", "").strip()
        quantitat = request.form.get("quantitat", "1").strip()
        
        if idx_raw is not None and referencia_input:
            idx = int(idx_raw)
            df = carregar_tasques()
            df_articles = carregar_articles()
            
            descripcio_trobada = ""
            stock_trobat = ""
            ubicacio_trobada = ""
            
            ref_neta = referencia_input.split(" - ")[0].split(" (")[0].split(" [")[0].strip()
            
            if not df_articles.empty and "Ref" in df_articles.columns:
                match = df_articles[df_articles["Ref"].astype(str).str.strip().str.upper() == ref_neta.upper()]
                if not match.empty:
                    descripcio_trobada = str(match.iloc[0].get("Descripcio", "")).strip()
                    stock_trobat = str(match.iloc[0].get("Stock", "0")).strip()
                    ubicacio_trobada = str(match.iloc[0].get("Ubicacio", "")).strip()
            
            prefix_quantitat = f"[{quantitat} ut.] " if quantitat else ""

            if descripcio_trobada:
                ref_formatted = f"{prefix_quantitat}{ref_neta} ({descripcio_trobada})"
            else:
                ref_formatted = f"{prefix_quantitat}{referencia_input}"

            detalls_extra = []
            if stock_trobat:
                detalls_extra.append(f"Stock: {stock_trobat}")
            if ubicacio_trobada:
                detalls_extra.append(f"Ubicació: {ubicacio_trobada}")

            if detalls_extra:
                ref_formatted += f" [{ ' | '.join(detalls_extra) }]"

            if 0 <= idx < len(df):
                if "Material_No_Subministrat" not in df.columns:
                    df["Material_No_Subministrat"] = ""
                    
                data_hora = datetime.now().strftime("%d/%m/%Y - %H:%M")
                nova_entrada = f"[{data_hora} | Ref: {ref_formatted} | Op: {operari_sel}]"
                
                actual = str(df.at[idx, "Material_No_Subministrat"]).strip()
                if actual and actual.lower() != "nan":
                    df.at[idx, "Material_No_Subministrat"] = f"{actual}\n{nova_entrada}"
                else:
                    df.at[idx, "Material_No_Subministrat"] = nova_entrada
                    
                guardar_tasques(df)
    except Exception as e:
        print(f"❌ Error en guardar material no subministrat: {e}")
            
    if operari_sel:
        return redirect(url_for("operari.vista_operari", operari=operari_sel))
    else:
        return redirect(request.referrer or url_for("operari.vista_operari"))

@operari_bp.route("/eliminar_material_no_subministrat", methods=["POST"])
def eliminar_material_no_subministrat():
    idx = int(request.form.get("csv_index"))
    mat_idx = int(request.form.get("mat_idx"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip()
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        text_actual = str(df.at[idx, "Material_No_Subministrat"]).strip()
        registres = extreure_historial_material_no_subministrat(text_actual)
        
        if 0 <= mat_idx < len(registres):
            reg_a_eliminar = registres[mat_idx]["raw_text"]
            linies = [l.strip() for l in text_actual.split("\n") if l.strip()]
            linies_filtrades = [l for l in linies if l != reg_a_eliminar]
            
            df.at[idx, "Material_No_Subministrat"] = "\n".join(linies_filtrades)
            guardar_tasques(df)
            
    if operari_sel:
        return redirect(url_for("operari.vista_operari", operari=operari_sel))
    else:
        return redirect(request.referrer or url_for("operari.vista_operari"))































































































































































