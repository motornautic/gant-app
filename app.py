from flask import Flask, redirect, url_for, send_from_directory, render_template, request, jsonify, session
from routes.operari import operari_bp
from routes.clients import clients_bp  
from routes.embarcacions import embarcacions_bp 
from routes.tasques import tasques_bp
from routes.gantt import gantt_bp
from routes.articles import articles_bp
from datetime import datetime, timedelta
from db import carregar_admins, guardar_admins
import os
import pandas as pd

app = Flask(__name__)
app.secret_key = "clau_secret_motornautic"

# 📧 CONFIGURACIÓ DE CORREU PER A L'ENVIAMENT REAL (admin@motornautic.com)
app.config['MAIL_SERVER'] = 'mail.motornautic.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USERNAME'] = 'admin@motornautic.com'
app.config['MAIL_PASSWORD'] = 'M0t0r@2026admin'  # ⚠️ Posa la teva contrasenya real de correu

# Carpeta persistent de fotografies
UPLOAD_FOLDER = os.environ.get(
    "UPLOAD_FOLDER",
    os.path.join(os.getcwd(), "uploads")
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Enregistrar els mòduls de rutes
app.register_blueprint(operari_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(embarcacions_bp)
app.register_blueprint(tasques_bp)    
app.register_blueprint(gantt_bp)
app.register_blueprint(articles_bp)

# 🛡️ CONTROL D'ACCÉS
# Accés al login i al panell de l'operari; la comprovació de credencials
# per a la sessió d'operari es fa a routes/operari.py.
RUTES_PUBLIQUES = [
    "vista_login_admin",
    "login_admin",
    "logout_admin",
    "operari.vista_operari",
    "operari.login_operari",
    "operari.logout_operari",
    "operari.sollicitar_recuperacio",
    "operari.validar_codi_recuperacio",
    "operari.recuperar_contrasenya",
    "static",
    "serve_upload",
]

# Accions que necessiten una sessió d'operari o d'administrador.
# No incloure-hi operari.afegir_operari: és una acció administrativa.
RUTES_OPERARI = {
    "operari.iniciar_crono",
    "operari.aturar_crono",
    "operari.afegir_temps_manual",
    "operari.registrar_sollicitud_material",
    "operari.canviar_estat_material",
    "operari.pujar_foto",
    "operari.confirmar_finalitzacio",
    "operari.eliminar_registre_hora",
    "operari.guardar_notes_operari",
    "operari.reobrir_tasca",
    "operari.canviar_contrasenya",
    "operari.registrar_material_no_subministrat",
    "operari.eliminar_material_no_subministrat",
}

@app.before_request
def requerir_login_admin():
    endpoint = request.endpoint
    if not endpoint:
        return

    if endpoint in RUTES_PUBLIQUES:
        return

    if session.get("admin_autenticat"):
        return

    # Lectura de la fitxa individual per a operaris autenticats.
    if (endpoint == "embarcacions.fitxa_embarcacio"
            and request.method == "GET"
            and session.get("operari_autenticat")):
        return

    # Els operaris poden afegir documents a la fitxa, però no editar embarcacions.
    if (endpoint == "embarcacions.afegir_document_fitxa"
            and request.method == "POST"
            and session.get("operari_autenticat")):
        return

    # Lectura de la llista d'embarcacions per a operaris.
    # Només s'autoritza el GET exacte de /embarcacions; qualsevol
    # altra URL o mètode segueix requerint administració.
    if (request.path.rstrip('/') == '/embarcacions'
            and request.method == 'GET'
            and session.get('operari_autenticat')):
        return

    if endpoint in RUTES_OPERARI:
        if session.get("operari_autenticat"):
            return
        return redirect(url_for("operari.vista_operari"))

    return redirect(url_for("vista_login_admin"))

# 🔐 RUTES D'AUTENTICACIÓ D'ADMINISTRACIÓ
@app.route("/login_admin", methods=["GET"])
def vista_login_admin():
    return render_template("login_admin.html", error=request.args.get("error"))

@app.route("/login_admin", methods=["POST"])
def login_admin():
    usuari_input = request.form.get("usuari", "").strip()
    pwd_input = request.form.get("password", "").strip()
    
    df_admins = carregar_admins()
    
    if not df_admins.empty:
        match = df_admins[
            (df_admins["Usuari"].str.lower() == usuari_input.lower()) & 
            (df_admins["Password"] == pwd_input)
        ]
        
        if not match.empty:
            session["admin_autenticat"] = match.iloc[0]["Usuari"]
            session["admin_nom"] = match.iloc[0]["Nom"]
            return redirect(url_for("tasques.vista_tasques"))
            
    return redirect(url_for("vista_login_admin", error=1))

@app.route("/logout_admin")
def logout_admin():
    session.pop("admin_autenticat", None)
    session.pop("admin_nom", None)
    return redirect(url_for("vista_login_admin"))

# Funció helper per carregar CSVs de manera segura
def carregar_csv_local(fitxer):
    if os.path.exists(fitxer):
        try:
            return pd.read_csv(fitxer, dtype=str).fillna('')
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/")
def index():
    return redirect(url_for("operari.vista_operari"))

# Filtre de data per a les plantilles Jinja (DD/MM/AAAA)
@app.template_filter('format_data')
def format_data(value):
    if not value or not isinstance(value, str):
        return value
    parts = value.strip().split('-')
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return value

@app.route('/scheduler')
def scheduler():
    week_start_param = request.args.get('week_start')
    avui = datetime.today()

    if week_start_param:
        try:
            start_date = datetime.strptime(week_start_param, '%Y-%m-%d')
        except ValueError:
            start_date = avui - timedelta(days=avui.weekday())
    else:
        start_date = avui - timedelta(days=avui.weekday())

    dies_setmana = []
    nom_dies = ['Dilluns', 'Dimarts', 'Dimecres', 'Dijous', 'Divendres', 'Dissabte', 'Diumenge']
    for i in range(7):
        dia_dt = start_date + timedelta(days=i)
        dies_setmana.append({
            'data_str': dia_dt.strftime('%Y-%m-%d'),
            'data_fmt': dia_dt.strftime('%d/%m/%Y'),
            'nom_dia': nom_dies[i],
            'dia_num': dia_dt.strftime('%d'),
            'es_avui': dia_dt.date() == avui.date()
        })

    prev_week = (start_date - timedelta(days=7)).strftime('%Y-%m-%d')
    next_week = (start_date + timedelta(days=7)).strftime('%Y-%m-%d')

    df_operaris = carregar_csv_local('operaris.csv')
    operaris = df_operaris['Nom'].tolist() if not df_operaris.empty and 'Nom' in df_operaris.columns else []
    
    colors_llista = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#64748b']
    mapa_colors = {op: colors_llista[i % len(colors_llista)] for i, op in enumerate(operaris)}

    df_tasques = carregar_csv_local('tasques.csv')
    tasques_llista = []

    def parse_data_flexible(data_raw):
        if not data_raw or str(data_raw).strip().lower() in ['nan', 'none', '']:
            return None
        st = str(data_raw).strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y'):
            try:
                return datetime.strptime(st, fmt).date()
            except ValueError:
                pass
        return None

    if not df_tasques.empty:
        for idx, row in df_tasques.iterrows():
            d_inici = parse_data_flexible(row.get('Data_Inici', row.get('data_inici', '')))
            d_fi = parse_data_flexible(row.get('Data_Fi', row.get('data_fi', '')))

            if not d_inici:
                continue
            if not d_fi or d_fi < d_inici:
                d_fi = d_inici

            dies_actius = []
            curr = d_inici
            while curr <= d_fi:
                dies_actius.append(curr.strftime('%Y-%m-%d'))
                curr += timedelta(days=1)

            barco = str(row.get('Embarcació', row.get('Embarcacio', 'Sense Barco'))).strip()
            operari_str = str(row.get('Operari', '')).strip()

            tasques_llista.append({
                'csv_index': idx,
                'titol': row.get('Titol_Tasca', 'Sense títol'),
                'embarcacio': barco,
                'operari': operari_str,
                'dies_actius': dies_actius,
                'estat': row.get('Estat', 'Pendent'),
                'prioritat': row.get('Prioritat', 'Normal')
            })

    return render_template(
        'scheduler.html',
        dies_setmana=dies_setmana,
        operaris=operaris,
        mapa_colors=mapa_colors,
        tasques=tasques_llista,
        prev_week=prev_week,
        next_week=next_week,
        start_date_str=start_date.strftime('%Y-%m-%d')
    )

# 🔐 RUTA PER A LA VISTA DE GESTIÓ D'ADMINISTRADORS
@app.route("/admins", methods=["GET"])
def vista_admins():
    df_admins = carregar_admins()
    admins_list = df_admins.to_dict(orient="records") if not df_admins.empty else []
    return render_template("admins.html", admins=admins_list)

@app.route("/afegir_admin", methods=["POST"])
def afegir_admin():
    usuari = request.form.get("usuari", "").strip()
    nom = request.form.get("nom", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if usuari and password:
        df = carregar_admins()
        # Verificar que l'usuari no existeixi ja
        if not df.empty and usuari.lower() in df["Usuari"].str.lower().values:
            return redirect(url_for("vista_admins", error="L'usuari ja existeix"))

        nou_admin = pd.DataFrame([{
            "Usuari": usuari,
            "Nom": nom if nom else usuari,
            "Email": email,
            "Password": password
        }])
        df = pd.concat([df, nou_admin], ignore_index=True)
        guardar_admins(df)

    return redirect(url_for("vista_admins"))

@app.route("/eliminar_admin", methods=["POST"])
def eliminar_admin():
    usuari = request.form.get("usuari", "").strip()
    df = carregar_admins()
    
    # Evitar esborrar el darrer administrador que queda
    if len(df) <= 1:
        return redirect(url_for("vista_admins", error="No pots eliminar l'únic administrador del sistema"))

    if not df.empty:
        df = df[df["Usuari"].str.lower() != usuari.lower()].reset_index(drop=True)
        guardar_admins(df)

    return redirect(url_for("vista_admins"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)


























