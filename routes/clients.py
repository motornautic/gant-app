from flask import Blueprint, render_template, request, redirect, url_for, send_file
import pandas as pd
import io
# 🚀 IMPORTEM DE DB.PY PER GARANTIR PERSISTÈNCIA A POSTGRESQL
from db import carregar_clients, guardar_clients

clients_bp = Blueprint('clients', __name__)

def generar_nou_id(df):
    if df.empty or "ID" not in df.columns:
        return "CLI-001"
    ids_existents = df["ID"].str.replace("CLI-", "", regex=False)
    ids_numerics = pd.to_numeric(ids_existents, errors="coerce").dropna()
    if ids_numerics.empty:
        return "CLI-001"
    següent_num = int(ids_numerics.max()) + 1
    return f"CLI-{següent_num:03d}"

@clients_bp.route("/clients", methods=["GET"])
def vista_clients():
    from routes.embarcacions import carregar_embarcacions
    
    df_clients = carregar_clients()
    df_emb = carregar_embarcacions()
    
    dic_embarcacions_dades = {}
    if not df_emb.empty:
        for _, r in df_emb.iterrows():
            nom_emb = str(r.get("Nom", "")).strip()
            if nom_emb:
                dic_embarcacions_dades[nom_emb] = {
                    "port": str(r.get("Port", "")).strip(),
                    "amarre": str(r.get("Amarre", "")).strip(),
                    "claus": str(r.get("Claus", "")).strip()
                }
                
    llista_clients = []
    edit_idx = request.args.get("edit_idx", type=int)
    error_nif = request.args.get("error_nif", type=bool, default=False)
    client_edit = None
    
    if not df_clients.empty:
        for idx, row in df_clients.iterrows():
            item = row.to_dict()
            item["csv_index"] = idx
            llista_clients.append(item)
            if edit_idx is not None and edit_idx == idx:
                client_edit = item
            
    return render_template(
        "clients.html", 
        clients=llista_clients, 
        embarcacions=sorted(list(dic_embarcacions_dades.keys())), 
        dic_embarcacions=dic_embarcacions_dades,
        edit_idx=edit_idx, 
        client_edit=client_edit,
        error_nif=error_nif
    )

@clients_bp.route("/afegir_client", methods=["POST"])
def afegir_client():
    tipus = request.form.get("tipus", "Particular")
    nom = request.form.get("nom", "").strip()
    cognoms = request.form.get("cognoms", "").strip()
    persona_contacte = request.form.get("persona_contacte", "").strip()
    nif = request.form.get("nif", "").strip()
    telefon = request.form.get("telefon", "").strip()
    email = request.form.get("email", "").strip()
    carrer = request.form.get("carrer", "").strip()
    cp = request.form.get("cp", "").strip()
    poblacio = request.form.get("poblacio", "").strip()
    embarcacio = request.form.get("embarcacio", "").strip()
    port = request.form.get("port", "").strip()
    amarre = request.form.get("amarre", "").strip()
    claus = request.form.get("claus", "").strip()
    comentaris = request.form.get("comentaris", "").strip()
    
    if nom:
        df = carregar_clients()
        
        # 🔒 VALIDACIÓ DE NIF DUPLICAT
        if nif and "NIF" in df.columns:
            nif_existents = df["NIF"].dropna().astype(str).str.strip().str.upper()
            if nif.upper() in nif_existents.values:
                return redirect(url_for("clients.vista_clients", error_nif=True))

        nou_id = generar_nou_id(df)
        nou_client = pd.DataFrame([{
            "ID": nou_id,
            "Tipus": tipus,
            "Nom": nom,
            "Cognoms": cognoms,
            "Persona_Contacte": persona_contacte,
            "NIF": nif,
            "Telèfon": telefon,
            "Email": email,
            "Carrer": carrer,
            "Adreça": carrer,
            "CP": cp,
            "Poblacio": poblacio,
            "Embarcació": embarcacio,
            "Port": port,
            "Amarre": amarre,
            "Claus": claus,
            "Comentaris": comentaris
        }])
        df = pd.concat([df, nou_client], ignore_index=True)
        guardar_clients(df)
        
    return redirect(url_for("clients.vista_clients"))

@clients_bp.route("/editar_client", methods=["POST"])
def editar_client():
    idx = int(request.form.get("csv_index"))
    df = carregar_clients()
    nif = request.form.get("nif", "").strip()
    
    if 0 <= idx < len(df):
        # 🔒 VALIDACIÓ DE NIF DUPLICAT (Excloent la fila actual)
        if nif and "NIF" in df.columns:
            df_altres = df.drop(idx)
            nif_existents = df_altres["NIF"].dropna().astype(str).str.strip().str.upper()
            if nif.upper() in nif_existents.values:
                return redirect(url_for("clients.vista_clients", edit_idx=idx, error_nif=True))

        carrer = request.form.get("carrer", "").strip()
        df.at[idx, "Tipus"] = request.form.get("tipus", "Particular")
        df.at[idx, "Nom"] = request.form.get("nom", "").strip()
        df.at[idx, "Cognoms"] = request.form.get("cognoms", "").strip()
        df.at[idx, "Persona_Contacte"] = request.form.get("persona_contacte", "").strip()
        df.at[idx, "NIF"] = nif
        df.at[idx, "Telèfon"] = request.form.get("telefon", "").strip()
        df.at[idx, "Email"] = request.form.get("email", "").strip()
        df.at[idx, "Carrer"] = carrer
        df.at[idx, "Adreça"] = carrer
        df.at[idx, "CP"] = request.form.get("cp", "").strip()
        df.at[idx, "Poblacio"] = request.form.get("poblacio", "").strip()
        df.at[idx, "Embarcació"] = request.form.get("embarcacio", "").strip()
        df.at[idx, "Port"] = request.form.get("port", "").strip()
        df.at[idx, "Amarre"] = request.form.get("amarre", "").strip()
        df.at[idx, "Claus"] = request.form.get("claus", "").strip()
        df.at[idx, "Comentaris"] = request.form.get("comentaris", "").strip()
        
        guardar_clients(df)
        
    return redirect(url_for("clients.vista_clients"))

@clients_bp.route("/eliminar_client", methods=["POST"])
def eliminar_client():
    idx = int(request.form.get("csv_index"))
    df = carregar_clients()
    if 0 <= idx < len(df):
        df = df.drop(idx).reset_index(drop=True)
        guardar_clients(df)
    return redirect(url_for("clients.vista_clients"))

@clients_bp.route("/exportar_clients_excel", methods=["GET"])
def exportar_clients_excel():
    df = carregar_clients()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Clients')
    output.seek(0)
    return send_file(output, download_name="Clients_MotorNautic.xlsx", as_attachment=True)

@clients_bp.route("/importar_clients_excel", methods=["POST"])
def importar_clients_excel():
    file = request.files.get("fitxer_excel")
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        # 1. Llegim l'Excel
        df_nou = pd.read_excel(file, dtype=str).fillna("")
        
        # Treiem columnes buides o de sistema
        df_nou = df_nou.loc[:, ~df_nou.columns.str.contains('^Unnamed', na=False)]
        
        # 2. Mapa de traducció de columnes
        mapa_columnes = {
            "id": "ID", "codi": "ID", "id_client": "ID", "id client": "ID",
            "població": "Poblacio", "poblacio": "Poblacio", "poblacio/ciutat": "Poblacio", "ciutat": "Poblacio",
            "codi postal": "CP", "codi_postal": "CP", "cp": "CP", "zip": "CP",
            "email": "Email", "e-mail": "Email", "correu": "Email", "correu electronic": "Email", "correu electrònic": "Email", "correu electrònic.1": "Email",
            "carrer": "Carrer", "adreça": "Carrer", "adreca": "Carrer",
            "telèfon": "Telèfon", "telefon": "Telèfon", "nif": "NIF", "cif": "NIF", "dni": "NIF", "nif/cif": "NIF",
            "embarcació": "Embarcació", "embarcacio": "Embarcació", "barco": "Embarcació",
            "nom": "Nom", "cognoms": "Cognoms", "port": "Port", "amarre": "Amarre", "claus": "Claus", "comentaris": "Comentaris"
        }
        
        noves_col = {}
        for col in df_nou.columns:
            col_clean = str(col).strip().lower()
            if col_clean in mapa_columnes:
                noves_col[col] = mapa_columnes[col_clean]
        
        df_nou = df_nou.rename(columns=noves_col)
        
        # ⚠️ CLAU PER EVITAR L'ERROR "Name: 0, dtype: str":
        # Fusionem columnes que hagin pogut quedar amb el mateix nom (p.ex. si hi havia 'Embarcació' i 'Embarcacio')
        df_nou = df_nou.T.groupby(level=0).first().T
        
        # Carreguem el DataFrame actual de clients
        df_actual = carregar_clients()
        if df_actual.empty:
            df_actual = pd.DataFrame(columns=["ID", "Tipus", "Nom", "Cognoms", "Persona_Contacte", "NIF", "Telèfon", "Email", "Carrer", "Adreça", "CP", "Poblacio", "Embarcació", "Port", "Amarre", "Claus", "Comentaris"])
        
        # 3. Recorrem les files de l'Excel importat
        for _, fila_importada in df_nou.iterrows():
            # Funció auxiliar per extreure un string net d'una cel·la
            def netejar_valor(val):
                if isinstance(val, pd.Series):
                    val = val.dropna().iloc[0] if not val.dropna().empty else ""
                val_str = str(val).strip()
                if val_str.lower() in ["nan", "none", "<na>"]:
                    return ""
                return val_str

            id_imp = netejar_valor(fila_importada.get("ID", ""))
            nif_imp = netejar_valor(fila_importada.get("NIF", "")).upper()
            
            # Cercar si el client ja existeix (primer per ID, desprès per NIF)
            coincidencia_idx = None
            
            if id_imp and "ID" in df_actual.columns:
                matches = df_actual[df_actual["ID"].astype(str).str.strip() == id_imp]
                if not matches.empty:
                    coincidencia_idx = matches.index[0]
            
            if coincidencia_idx is None and nif_imp and "NIF" in df_actual.columns:
                matches = df_actual[df_actual["NIF"].astype(str).str.strip().str.upper() == nif_imp]
                if not matches.empty:
                    coincidencia_idx = matches.index[0]
            
            # CAS 1: El client JA EXISTEIX -> Només actualitzem/omplim les dades que venien a l'Excel
            if coincidencia_idx is not None:
                for col in fila_importada.index:
                    valor_nou = netejar_valor(fila_importada[col])
                    if valor_nou and col in df_actual.columns:
                        df_actual.at[coincidencia_idx, col] = valor_nou
                        if col == "Carrer":
                            df_actual.at[coincidencia_idx, "Adreça"] = valor_nou

            # CAS 2: El client NO EXISTEIX -> L'afegim com a nou registrat
            else:
                nom_imp = netejar_valor(fila_importada.get("Nom", ""))
                if nom_imp or nif_imp:
                    nou_row = {}
                    for col in fila_importada.index:
                        nou_row[col] = netejar_valor(fila_importada[col])
                    
                    if not nou_row.get("ID"):
                        nou_row["ID"] = generar_nou_id(df_actual)
                    if nou_row.get("Carrer") and not nou_row.get("Adreça"):
                        nou_row["Adreça"] = nou_row["Carrer"]
                    
                    df_actual = pd.concat([df_actual, pd.DataFrame([nou_row])], ignore_index=True)

        # Netegem duplicitats de columnes final a df_actual si escau
        df_actual = df_actual.loc[:, ~df_actual.columns.duplicated()]
        guardar_clients(df_actual)
        
    return redirect(url_for("clients.vista_clients"))

