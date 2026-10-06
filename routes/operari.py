from flask import Blueprint, render_template, request, redirect, url_for, current_app, jsonify, session, flash, make_response
from datetime import datetime, timedelta
import pandas as pd
import re, os, json, random, string
import urllib.parse
from werkzeug.utils import secure_filename
from db import carregar_operaris, carregar_tasques, guardar_tasques, carregar_articles
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 🚀 Declaració del Blueprint
operari_bp = Blueprint('operari', __name__)

# ---------------------------------------------------------------------
# FUNCIONS AUXILIARS DE PROCESSAMENT (IMPORTADES PER TASQUES.PY)
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
    if not text_mat_no_sub or pd.isna(text_mat_no_sub):
        return []
    registres = []
    patro = r'\[([\d\/]+ - [\d:]+)\s*\|\s*Ref:\s*([^\|]+)\s*\|\s*Op:\s*([^\]]+)\]'
    coincidencies = list(re.finditer(patro, str(text_mat_no_sub)))
    for idx, match in enumerate(coincidencies):
        data_hora, ref, op = match.groups()
        registres.append({
            "mat_idx": idx,
            "data_hora": data_hora.strip(),
            "referencia": ref.strip(),
            "operari": op.strip(),
            "raw_text": match.group(0)
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
    fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
    columnes = ["Nom", "Cognoms", "Telefon", "Email", "Password", "Reset_Code", "Reset_Expiry"]
    if os.path.exists(fitxer_op):
        try:
            df = pd.read_csv(fitxer_op, dtype=str).fillna('')
            for col in columnes:
                if col not in df.columns:
                    df[col] = ""
            return df
        except Exception:
            return pd.DataFrame(columns=columnes)
    return pd.DataFrame(columns=columnes)

# ---------------------------------------------------------------------
# RUTES DE L'OPERARI
# ---------------------------------------------------------------------

@operari_bp.route("/operari", methods=["GET"])
def vista_operari():
    operaris = carregar_operaris()
    
    # Check si l'usuari actual és un administrador autenticat
    es_admin = bool(session.get("admin_autenticat"))
    
    operari_autenticat = request.cookies.get("operari_saved") or session.get("operari_autenticat")
    operari_req = request.args.get("operari")
    
    # Si és administrador, pot veure qualsevol operari directament sense demanar login
    if es_admin:
        operari_sel = operari_req or (operaris[0] if operaris else None)
    else:
        if operari_req and operari_autenticat and operari_req.upper() != operari_autenticat.upper():
            operari_autenticat = None
            
        operari_sel = operari_req or operari_autenticat
        
        if not operari_autenticat or not operari_sel:
            return render_template("login_operari.html", operaris=operaris, operari_sel=operari_sel, error=request.args.get("error_auth"))

    confirm_idx = request.args.get("confirm_idx", type=int)
    edit_reg_info = {"task_idx": request.args.get("edit_task_idx", type=int), "reg_idx": request.args.get("edit_reg_idx", type=int)}
    
        # 📦 Carregar la base de dades d'articles per a l'autocompletat (amb Stock i Ubicació)
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
                
                # Afegir Stock i Ubicació visibles per a l'operari
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
                item["historial_hores"] = extreure_historial_hores(item.get("Comentaris_Operari", ""))
                item["historial_material"] = extreure_historial_material(item.get("Material_Demanat", ""))
                item["checklist"] = extreure_checklist_items(item.get("Tasques_Detall", ""))
                item["historial_mat_no_subministrat"] = extreure_historial_material_no_subministrat(item.get("Material_No_Subministrat", ""))

                emb_folder = secure_filename(item.get("Embarcació", "GENERAL"))
                folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
                fotos = []
                if os.path.exists(folder_path):
                    fotos = [f"/uploads/{emb_folder}/{f}" for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                item["fotos"] = fotos
                tasques_op.append(item)

    return render_template("operari.html", operaris=operaris, operari_sel=operari_sel, perfil=perfil_data, tasques=tasques_op, confirm_idx=confirm_idx, edit_reg_info=edit_reg_info, articles=llista_articles, es_admin=es_admin)


@operari_bp.route("/login_operari", methods=["POST"])
def login_operari():
    operari_sel = request.form.get("operari", "").strip()
    password_input = request.form.get("password", "").strip()
    remember = request.form.get("remember")
    
    df_operaris = carregar_df_operaris()
    
    if not df_operaris.empty and "Nom" in df_operaris.columns:
        row = df_operaris[df_operaris["Nom"].str.upper() == str(operari_sel).upper()]
        if not row.empty:
            pwd_guardada = str(row.iloc[0].get("Password", "")).strip()
            pwd_esperada = pwd_guardada if pwd_guardada else operari_sel
            
            if password_input.upper() == pwd_esperada.upper():
                session["operari_autenticat"] = operari_sel
                response = make_response(redirect(url_for("operari.vista_operari", operari=operari_sel)))
                
                if remember == "1":
                    response.set_cookie("operari_saved", operari_sel, max_age=30*24*3600)
                else:
                    response.delete_cookie("operari_saved")
                    
                return response
    
    return redirect(url_for("operari.vista_operari", operari=operari_sel, error_auth=1))

@operari_bp.route("/logout_operari", methods=["POST"])
def logout_operari():
    session.pop("operari_autenticat", None)
    response = make_response(redirect(url_for("operari.vista_operari")))
    response.delete_cookie("operari_saved")
    return response

@operari_bp.route("/sollicitar_recuperacio", methods=["POST"])
def sollicitar_recuperacio():
    email_input = request.form.get("email", "").strip().lower()
    fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
    df_operaris = carregar_df_operaris()
    
    if not df_operaris.empty and "Email" in df_operaris.columns:
        idx_list = df_operaris.index[df_operaris["Email"].str.lower() == email_input].tolist()
        if idx_list:
            idx = idx_list[0]
            operari_nom = df_operaris.at[idx, "Nom"]
            
            codi = ''.join(random.choices(string.digits, k=6))
            expiracio = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
            
            df_operaris.at[idx, "Reset_Code"] = codi
            df_operaris.at[idx, "Reset_Expiry"] = expiracio
            df_operaris.to_csv(fitxer_op, index=False)
            
            mail_user = current_app.config.get('MAIL_USERNAME')
            mail_pass = current_app.config.get('MAIL_PASSWORD')
            mail_server = current_app.config.get('MAIL_SERVER')
            mail_port = current_app.config.get('MAIL_PORT', 465)
            use_ssl = current_app.config.get('MAIL_USE_SSL', True)
            
            if mail_user and mail_pass and mail_server:
                try:
                    msg = MIMEMultipart()
                    msg['From'] = f"MotorNautic Gestió <{mail_user}>"
                    msg['To'] = email_input
                    msg['Subject'] = f"🔑 Codi de recuperació de contrasenya: {codi}"
                    
                    cos_email = f"""
                    Hola {operari_nom},
                    
                    Heu sol·licitat restablir la vostra contrasenya per accedir al Panell d'Operari.
                    
                    El teu codi de verificació de 6 dígits és: {codi}
                    
                    ⏱️ Aquest codi caducarà en 15 minuts.
                    
                    Si no heu demanat aquest canvi, podeu ignorar aquest correu.
                    """
                    msg.attach(MIMEText(cos_email, 'plain'))
                    
                    if use_ssl or mail_port == 465:
                        server = smtplib.SMTP_SSL(mail_server, mail_port, timeout=10)
                    else:
                        server = smtplib.SMTP(mail_server, mail_port, timeout=10)
                        server.starttls()
                        
                    server.login(mail_user, mail_pass)
                    server.sendmail(mail_user, email_input, msg.as_string())
                    server.quit()
                    
                    print(f"✅ EMAIL ENVIAT CORRECTAMENT A {email_input}")
                except Exception as e:
                    print(f"❌ Error enviant Email SMTP: {e}")
            else:
                print(f"⚠️ SMTP no configurat a app.py. Codi generat per a {email_input}: {codi}")

            return render_template("reset_password.html", email=email_input, msg_info="S'ha enviat un codi de 6 dígits al teu correu. Tens 15 minuts per utilitzar-lo.")
            
    return render_template("login_operari.html", operaris=carregar_operaris(), error_auth=1)

@operari_bp.route("/validar_codi_recuperacio", methods=["POST"])
def validar_codi_recuperacio():
    email_input = request.form.get("email", "").strip().lower()
    codi_input = request.form.get("codi", "").strip()
    pwd_nova = request.form.get("password_nova", "").strip()
    
    fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
    df_operaris = carregar_df_operaris()
    
    if not df_operaris.empty and "Email" in df_operaris.columns:
        idx_list = df_operaris.index[df_operaris["Email"].str.lower() == email_input].tolist()
        if idx_list:
            idx = idx_list[0]
            codi_guardat = str(df_operaris.at[idx, "Reset_Code"]).strip()
            expiracio_str = str(df_operaris.at[idx, "Reset_Expiry"]).strip()
            
            if codi_guardat and codi_input == codi_guardat:
                try:
                    expiracio_dt = datetime.strptime(expiracio_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() <= expiracio_dt:
                        df_operaris.at[idx, "Password"] = pwd_nova
                        df_operaris.at[idx, "Reset_Code"] = ""
                        df_operaris.at[idx, "Reset_Expiry"] = ""
                        df_operaris.to_csv(fitxer_op, index=False)
                        
                        operari_nom = df_operaris.at[idx, "Nom"]
                        session["operari_autenticat"] = operari_nom
                        
                        response = make_response(redirect(url_for("operari.vista_operari", operari=operari_nom)))
                        response.set_cookie("operari_saved", operari_nom, max_age=30*24*3600)
                        return response
                    else:
                        error_msg = "El codi ha caducat (durada màxima de 15 minuts). Sol·licita un de nou."
                except Exception:
                    error_msg = "Error validant la data de caducitat del codi."
            else:
                error_msg = "El codi de verificació introduït no és correcte."
                
            return render_template("reset_password.html", email=email_input, error=error_msg)

    return redirect(url_for("operari.vista_operari"))

@operari_bp.route("/guardar_perfil_operari", methods=["POST"])
def guardar_perfil_operari():
    operari_sel = request.form.get("operari_sel", "").strip()
    cognoms = request.form.get("cognoms", "").strip()
    telefon = request.form.get("telefon", "").strip()
    email = request.form.get("email", "").strip().lower()
    
    fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
    df_operaris = carregar_df_operaris()
    
    if not df_operaris.empty and "Nom" in df_operaris.columns:
        idx_list = df_operaris.index[df_operaris["Nom"].str.upper() == operari_sel.upper()].tolist()
        if idx_list:
            idx = idx_list[0]
            df_operaris.at[idx, "Cognoms"] = cognoms
            df_operaris.at[idx, "Telefon"] = telefon
            df_operaris.at[idx, "Email"] = email
            df_operaris.to_csv(fitxer_op, index=False)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/toggle_checklist_item", methods=["POST"])
def toggle_checklist_item():
    data = request.get_json()
    idx = int(data.get("csv_index"))
    item_idx = int(data.get("item_index"))
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        detall_raw = str(df.at[idx, "Tasques_Detall"]).strip()
        linees = [l.strip() for l in detall_raw.split("\n") if l.strip()]
        
        if 0 <= item_idx < len(linees):
            linea = linees[item_idx]
            es_fet = linea.startswith("[x]") or linea.startswith("[X]")
            text_pur = linea.replace("[x]", "").replace("[X]", "").replace("[ ]", "").strip()
            
            if es_fet:
                linees[item_idx] = f"[ ] {text_pur}"
            else:
                linees[item_idx] = f"[x] {text_pur}"
                
            df.at[idx, "Tasques_Detall"] = "\n".join(linees)
            totes_fetes = all(l.startswith("[x]") or l.startswith("[X]") for l in linees)
                
            guardar_tasques(df)
            return jsonify({"status": "success", "totes_fetes": totes_fetes})
            
    return jsonify({"status": "error"}), 400

@operari_bp.route("/iniciar_crono", methods=["POST"])
def iniciar_crono():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel")
    df = carregar_tasques()
    
    if 0 <= idx < len(df):
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
    operari_sel = request.form.get("operari_sel")
    df = carregar_tasques()
    
    if 0 <= idx < len(df):
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
                
            except Exception as e:
                print(f"Error calculant crono: {e}")
                
            crono_dict.pop(operari_sel, None)
            df.at[idx, "Inici_Crono"] = json.dumps(crono_dict) if crono_dict else ""
            df.at[idx, "Estat"] = "En Curs"
            guardar_tasques(df)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel, confirm_idx=idx))

@operari_bp.route("/registrar_sollicitud_material", methods=["POST"])
def registrar_sollicitud_material():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel")
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
    operari_sel = request.form.get("operari_sel", "")
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
    operari_sel = request.form.get("operari_sel")
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
    operari_sel = request.form.get("operari_sel")
    es_finalitzada = request.form.get("es_finalitzada")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        if es_finalitzada == "1":
            df.at[idx, "Estat"] = "Finalitzada"
        else:
            df.at[idx, "Estat"] = "En Curs"
            
        guardar_tasques(df)
        
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/afegir_temps_manual", methods=["POST"])
def afegir_temps_manual():
    idx = int(request.form.get("csv_index"))
    hora_inici, hora_fi = request.form.get("hora_inici"), request.form.get("hora_fi")
    operari_sel = request.form.get("operari_sel")
    
    t_inici, t_fi = datetime.strptime(hora_inici, "%H:%M"), datetime.strptime(hora_fi, "%H:%M")
    if t_fi < t_inici: t_fi += pd.Timedelta(days=1)
    
    diff_segons = int((t_fi - t_inici).total_seconds())
    h_int = int(diff_segons // 3600)
    m_int = int(round((diff_segons % 3600) / 60))
    if m_int == 60:
        h_int += 1
        m_int = 0
    
    df = carregar_tasques()
    data_avui = datetime.now().strftime("%d/%m/%y")
    
    nova_nota = f"[{operari_sel} | Temps manual {data_avui}: {hora_inici} a {hora_fi} ({h_int}h {m_int:02d}m)]"
    
    com_actual = df.at[idx, "Comentaris_Operari"]
    nou_com = f"{com_actual} | {nova_nota}" if com_actual else nova_nota
    df.at[idx, "Comentaris_Operari"] = nou_com
    df.at[idx, "Hores_Imputades"] = calcular_total_formatted(nou_com)
    
    if request.form.get("marcar_finalitzada"): 
        df.at[idx, "Estat"] = "Finalitzada"
    else:
        df.at[idx, "Estat"] = "En Curs"
        
    guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/eliminar_registre_hora", methods=["POST"])
def eliminar_registre_hora():
    idx, reg_idx = int(request.form.get("csv_index")), int(request.form.get("reg_index"))
    operari_sel = request.form.get("operari_sel")
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

@operari_bp.route("/guardar_edicio_hora", methods=["POST"])
def guardar_edicio_hora():
    idx, reg_idx = int(request.form.get("csv_index")), int(request.form.get("reg_index"))
    hora_inici, hora_fi = request.form.get("hora_inici"), request.form.get("hora_fi")
    operari_sel = request.form.get("operari_sel")
    df = carregar_tasques()
    com_actual = df.at[idx, "Comentaris_Operari"]
    registres = extreure_historial_hores(com_actual)
    if 0 <= reg_idx < len(registres):
        reg_antic = registres[reg_idx]
        t_inici, t_fi = datetime.strptime(hora_inici, "%H:%M"), datetime.strptime(hora_fi, "%H:%M")
        if t_fi < t_inici: t_fi += pd.Timedelta(days=1)
        diff_segons = int((t_fi - t_inici).total_seconds())
        h_int = int(diff_segons // 3600)
        m_int = int(round((diff_segons % 3600) / 60))
        if m_int == 60:
            h_int += 1
            m_int = 0
            
        nou_text_reg = f"[{reg_antic['operari']} | Temps manual {reg_antic['data']}: {hora_inici} a {hora_fi} ({h_int}h {m_int:02d}m)]"
        df.at[idx, "Comentaris_Operari"] = com_actual.replace(reg_antic["raw_text"], nou_text_reg)
        df.at[idx, "Hores_Imputades"] = calcular_total_formatted(df.at[idx, "Comentaris_Operari"])
        guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/guardar_notes_operari", methods=["POST"])
def guardar_notes_operari():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel")
    notes_text = request.form.get("notes_operari", "").strip()
    df = carregar_tasques()
    if "Notes_Text" not in df.columns: df["Notes_Text"] = ""
    df.at[idx, "Notes_Text"] = notes_text
    guardar_tasques(df)
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/reobrir_tasca", methods=["POST"])
def reobrir_tasca():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel")
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
    operari_sel = request.form.get("operari_sel", "").strip()
    pwd_actual = request.form.get("pwd_actual", "").strip()
    pwd_nova = request.form.get("pwd_nova", "").strip()
    
    if not operari_sel or not pwd_nova:
        return redirect(url_for("operari.vista_operari", operari=operari_sel, pwd_err=1))

    try:
        fitxer_op = os.path.join(os.getcwd(), 'operaris.csv')
        df_operaris = carregar_df_operaris()
        
        if not df_operaris.empty and "Nom" in df_operaris.columns:
            if "Password" not in df_operaris.columns:
                df_operaris["Password"] = ""

            for idx, row in df_operaris.iterrows():
                nom_csv = str(row.get("Nom", "")).strip()
                
                if nom_csv.upper() == operari_sel.upper():
                    pwd_guardada = str(row.get("Password", "")).strip()
                    pwd_esperada = pwd_guardada if pwd_guardada else nom_csv
                    
                    if pwd_actual.upper() == pwd_esperada.upper():
                        df_operaris.at[idx, "Password"] = pwd_nova
                        df_operaris.to_csv(fitxer_op, index=False)
                        return redirect(url_for("operari.vista_operari", operari=operari_sel, pwd_ok=1))
                    else:
                        return redirect(url_for("operari.vista_operari", operari=operari_sel, pwd_err=1))

    except Exception as e:
        print(f"⚠️ Error en canviar la contrasenya: {e}")

    return redirect(url_for("operari.vista_operari", operari=operari_sel, pwd_err=1))

@operari_bp.route("/recuperar_contrasenya", methods=["POST"])
def recuperar_contrasenya():
    operari_sel = request.form.get("operari_sel")
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
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel")
    referencia_input = request.form.get("referencia", "").strip()
    
    if referencia_input:
        df = carregar_tasques()
        df_articles = carregar_articles()
        
        descripcio_trobada = ""
        stock_trobat = ""
        ubicacio_trobada = ""
        
        # Netejar la referència si s'ha seleccionat del datalist
        ref_neta = referencia_input.split(" - ")[0].split(" (")[0].split(" [")[0].strip()
        
        if not df_articles.empty:
            match = df_articles[df_articles["Ref"].str.strip().str.upper() == ref_neta.upper()]
            if not match.empty:
                descripcio_trobada = str(match.iloc[0].get("Descripcio", "")).strip()
                stock_trobat = str(match.iloc[0].get("Stock", "0")).strip()
                ubicacio_trobada = str(match.iloc[0].get("Ubicacio", "")).strip()
        
        # Construcció del format del text a desar
        elements_text = []
        if descripcio_trobada:
            elements_text.append(f"{ref_neta} ({descripcio_trobada})")
        else:
            elements_text.append(referencia_input)

        detalls_extra = []
        if stock_trobat:
            detalls_extra.append(f"Stock: {stock_trobat}")
        if ubicacio_trobada:
            detalls_extra.append(f"Ubicació: {ubicacio_trobada}")

        ref_formatted = elements_text[0]
        if detalls_extra:
            ref_formatted += f" [{ ' | '.join(detalls_extra) }]"

        if 0 <= idx < len(df):
            if "Material_No_Subministrat" not in df.columns:
                df["Material_No_Subministrat"] = ""
                
            data_hora = datetime.now().strftime("%d/%m/%Y - %H:%M")
            nova_entrada = f"[{data_hora} | Ref: {ref_formatted} | Op: {operari_sel}]"
            
            actual = str(df.at[idx, "Material_No_Subministrat"]).strip()
            if actual and actual != "nan":
                df.at[idx, "Material_No_Subministrat"] = f"{actual}\n{nova_entrada}"
            else:
                df.at[idx, "Material_No_Subministrat"] = nova_entrada
                
            guardar_tasques(df)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel))

@operari_bp.route("/eliminar_material_no_subministrat", methods=["POST"])
def eliminar_material_no_subministrat():
    idx = int(request.form.get("csv_index"))
    mat_idx = int(request.form.get("mat_idx"))
    operari_sel = request.form.get("operari_sel")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        text_actual = str(df.at[idx, "Material_No_Subministrat"]).strip()
        registres = extreure_historial_material_no_subministrat(text_actual)
        
        if 0 <= mat_idx < len(registres):
            reg_a_eliminar = registres[mat_idx]["raw_text"]
            # Eliminar la línia corresponent
            linies = [l.strip() for l in text_actual.split("\n") if l.strip()]
            linies_filtrades = [l for l in linies if l != reg_a_eliminar]
            
            df.at[idx, "Material_No_Subministrat"] = "\n".join(linies_filtrades)
            guardar_tasques(df)
            
    return redirect(url_for("operari.vista_operari", operari=operari_sel))


