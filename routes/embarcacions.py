from flask import Blueprint, render_template, request, redirect, url_for, current_app
import pandas as pd
import os, re, json
from datetime import datetime
from werkzeug.utils import secure_filename
from routes.clients import carregar_clients

embarcacions_bp = Blueprint('embarcacions', __name__)

CSV_EMBARCACIONS = "embarcacions.csv"
JSON_MOTORS_CUSTOM = "motors_custom.json"

DIC_MOTORS_BASE = {
    "Caterpillar": ["3208", "C12", "C18", "C32", "C7", "C9"],
    "Cummins": ["QSB 5.9", "QSB 6.7", "QSC 8.3", "QSL 9", "QSM 11"],
    "MAN": ["V12-1550", "V12-1900", "V8-1000", "V8-1200", "i6-730"],
    "Mercury / Mercruiser": ["350 MAG MPI", "4.3 MPI", "5.0 MPI", "5.7L", "6.2L V8", "8.2 MAG", "F115 EFI", "F150 EFI", "F200 Verado", "F300 Verado", "F350 Verado"],
    "Suzuki": ["DF115B", "DF140B", "DF150AP", "DF200AP", "DF250AP", "DF300AP", "DF350A", "DF90A"],
    "Volvo Penta": ["D1-13", "D1-20", "D1-30", "D11-670", "D13-900", "D2-40", "D2-50", "D2-60", "D2-75", "D3-110", "D3-150", "D3-220", "D4-180", "D4-225", "D4-260", "D4-300", "D6-310", "D6-370", "D6-435", "KAD300", "KAD32", "KAD42", "KAD43", "KAD44", "TAMD41"],
    "Yanmar": ["1GM10", "2YM15", "3JH40", "3YM20", "3YM30AE", "4JH110", "4JH45", "4JH57", "4JH80", "4LHA-STP", "6CX530", "6LPA-STP", "6LY400"]
}

def carregar_diccionari_motors():
    dic = {k: sorted(v) for k, v in DIC_MOTORS_BASE.items()}
    if os.path.exists(JSON_MOTORS_CUSTOM):
        try:
            with open(JSON_MOTORS_CUSTOM, "r", encoding="utf-8") as f:
                custom_data = json.load(f)
                for marca, models in custom_data.items():
                    if marca not in dic: dic[marca] = []
                    for m in models:
                        if m not in dic[marca]: dic[marca].append(m)
        except Exception: pass
    return {k: sorted(dic[k]) for k in sorted(dic.keys())}

def guardar_nou_motor_custom(marca, model):
    dic_custom = {}
    if os.path.exists(JSON_MOTORS_CUSTOM):
        try:
            with open(JSON_MOTORS_CUSTOM, "r", encoding="utf-8") as f:
                dic_custom = json.load(f)
        except Exception: dic_custom = {}
            
    if marca not in dic_custom: dic_custom[marca] = []
    if model and model not in dic_custom[marca]:
        base_models = DIC_MOTORS_BASE.get(marca, [])
        if model not in base_models: dic_custom[marca].append(model)
            
    dic_custom_ordenat = {k: sorted(dic_custom[k]) for k in sorted(dic_custom.keys())}
    with open(JSON_MOTORS_CUSTOM, "w", encoding="utf-8") as f:
        json.dump(dic_custom_ordenat, f, ensure_ascii=False, indent=2)

def extreure_historial_hores_motor(text_historial):
    if not text_historial: return []
    registres = []
    patro = r'\[([\d\/]+):\s*([^\]]+)\]'
    coincidencies = list(re.finditer(patro, text_historial))
    for idx, match in enumerate(coincidencies):
        data, hores_str = match.groups()
        registres.append({"reg_index": idx, "data": data, "hores": hores_str, "raw_text": match.group(0)})
    return registres

def extreure_enllacs(text_enllacs):
    if not text_enllacs: return []
    registres = []
    patro = r'\[([^\|]+)\|([^\]]+)\]'
    coincidencies = list(re.finditer(patro, text_enllacs))
    for idx, match in enumerate(coincidencies):
        titol, url = match.groups()
        es_pdf = url.lower().endswith('.pdf')
        registres.append({"link_index": idx, "titol": titol.strip(), "url": url.strip(), "es_pdf": es_pdf, "raw_text": match.group(0)})
    return registres

def carregar_embarcacions():
    if os.path.exists(CSV_EMBARCACIONS):
        df = pd.read_csv(CSV_EMBARCACIONS, dtype=str).fillna("")
        for col in ["Nom", "Client_Propietari", "Marca_Motor", "Model_Motor", "Num_Motors", "Num_Serie_Motors", "Hores_Motor", "Data_Hores", "Historial_Hores", "Enllacs", "Model_Barco", "Matricula", "Port", "Amarre", "Claus", "Comentaris"]:
            if col not in df.columns: df[col] = ""
        return df
    return pd.DataFrame(columns=["Nom", "Client_Propietari", "Marca_Motor", "Model_Motor", "Num_Motors", "Num_Serie_Motors", "Hores_Motor", "Data_Hores", "Historial_Hores", "Enllacs", "Model_Barco", "Matricula", "Port", "Amarre", "Claus", "Comentaris"])

def guardar_embarcacions(df):
    df.to_csv(CSV_EMBARCACIONS, index=False)

@embarcacions_bp.route("/embarcacions", methods=["GET"])
def vista_embarcacions():
    df_emb = carregar_embarcacions()
    df_cli = carregar_clients()
    dic_motors = carregar_diccionari_motors()
    
    llista_clients_noms = []
    if not df_cli.empty:
        for _, r in df_cli.iterrows():
            nom_comp = f"{r['Nom']} {r['Cognoms']}".strip() if r['Tipus'] == 'Particular' else r['Nom']
            if nom_comp: llista_clients_noms.append(nom_comp)

    llista_emb = []
    edit_idx = request.args.get("edit_idx", type=int)
    emb_edit = None
    
    if not df_emb.empty:
        for idx, row in df_emb.iterrows():
            item = row.to_dict()
            item["csv_index"] = idx
            
            item["num_motors_int"] = int(item.get("Num_Motors", 1)) if str(item.get("Num_Motors", "1")).isdigit() else 1
            item["list_num_serie"] = [s.strip() for s in item.get("Num_Serie_Motors", "").split(",") if s.strip()] or [""] * item["num_motors_int"]
            item["list_hores"] = [h.strip() for h in item.get("Hores_Motor", "").split(",") if h.strip()] or [""] * item["num_motors_int"]

            item["historial_hores_llista"] = extreure_historial_hores_motor(item.get("Historial_Hores", ""))
            item["enllacs_llista"] = extreure_enllacs(item.get("Enllacs", ""))
            item["num_docs"] = len(item["enllacs_llista"])

            emb_folder = secure_filename(item.get("Nom", "GENERAL"))
            folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
            fotos = []
            if os.path.exists(folder_path):
                fotos = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            item["num_fotos"] = len(fotos)
            llista_emb.append(item)
            
            if edit_idx is not None and edit_idx == idx:
                emb_edit = item
            
    now_date = datetime.now().strftime("%Y-%m-%d")
    return render_template("embarcacions.html", embarcacions=llista_emb, clients_llista=sorted(llista_clients_noms), dic_motors=dic_motors, edit_idx=edit_idx, emb_edit=emb_edit, now_date=now_date)

# PÀGINA INDEPENDENT DE GALERIA DE FOTOS
@embarcacions_bp.route("/embarcacions/<int:idx>/fotos", methods=["GET"])
def galeria_fotos(idx):
    df = carregar_embarcacions()
    if idx < 0 or idx >= len(df):
        return redirect(url_for("embarcacions.vista_embarcacions"))
    
    embarcacio = df.iloc[idx].to_dict()
    embarcacio["csv_index"] = idx
    
    emb_folder = secure_filename(embarcacio.get("Nom", "GENERAL"))
    folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
    
    fotos = []
    if os.path.exists(folder_path):
        for f in os.listdir(folder_path):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                fotos.append({
                    "filename": f,
                    "url": f"/uploads/{emb_folder}/{f}"
                })
                
    return render_template("galeria_fotos.html", embarcacio=embarcacio, fotos=fotos, emb_folder=emb_folder)

# PÀGINA INDEPENDENT DE GESTIÓ DE DOCUMENTS I ENLLAÇOS
@embarcacions_bp.route("/embarcacions/<int:idx>/documents", methods=["GET"])
def gestio_documents(idx):
    df = carregar_embarcacions()
    if idx < 0 or idx >= len(df):
        return redirect(url_for("embarcacions.vista_embarcacions"))
    
    embarcacio = df.iloc[idx].to_dict()
    embarcacio["csv_index"] = idx
    documents = extreure_enllacs(embarcacio.get("Enllacs", ""))
    
    return render_template("gestio_documents.html", embarcacio=embarcacio, documents=documents)

@embarcacions_bp.route("/pujar_foto_embarcacio", methods=["POST"])
def pujar_foto_embarcacio():
    idx = int(request.form.get("csv_index"))
    file = request.files.get("foto")
    if file and file.filename != '':
        df = carregar_embarcacions()
        emb_folder = secure_filename(df.at[idx, "Nom"])
        dest_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
        os.makedirs(dest_dir, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        file.save(os.path.join(dest_dir, filename))
    return redirect(url_for("embarcacions.galeria_fotos", idx=idx))

@embarcacions_bp.route("/eliminar_foto_embarcacio", methods=["POST"])
def eliminar_foto_embarcacio():
    idx = int(request.form.get("csv_index"))
    filename = request.form.get("filename")
    df = carregar_embarcacions()
    
    if idx >= 0 and idx < len(df) and filename:
        emb_folder = secure_filename(df.at[idx, "Nom"])
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            
    return redirect(url_for("embarcacions.galeria_fotos", idx=idx))

@embarcacions_bp.route("/afegir_enllac_embarcacio", methods=["POST"])
def afegir_enllac_embarcacio():
    idx = int(request.form.get("csv_index"))
    tipus_doc = request.form.get("tipus_doc")
    titol = request.form.get("titol", "").strip()
    
    url_final = ""
    df = carregar_embarcacions()
    emb_nom = df.at[idx, "Nom"]
    
    if tipus_doc == "pdf":
        file = request.files.get("pdf_file")
        if file and file.filename != '':
            emb_folder = secure_filename(emb_nom)
            dest_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
            os.makedirs(dest_dir, exist_ok=True)
            filename = f"DOC_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
            file.save(os.path.join(dest_dir, filename))
            url_final = f"/uploads/{emb_folder}/{filename}"
            if not titol: titol = secure_filename(file.filename)
    else:
        url_final = request.form.get("url", "").strip()

    if titol and url_final:
        nou_link = f"[{titol}|{url_final}]"
        actuals = df.at[idx, "Enllacs"]
        df.at[idx, "Enllacs"] = f"{actuals} | {nou_link}" if actuals else nou_link
        guardar_embarcacions(df)
        
    return redirect(url_for("embarcacions.gestio_documents", idx=idx))

@embarcacions_bp.route("/eliminar_document_embarcacio", methods=["POST"])
def eliminar_document_embarcacio():
    idx = int(request.form.get("csv_index"))
    link_idx = int(request.form.get("link_index"))
    
    df = carregar_embarcacions()
    if 0 <= idx < len(df):
        enllacs = extreure_enllacs(df.at[idx, "Enllacs"])
        if 0 <= link_idx < len(enllacs):
            doc_esborrar = enllacs.pop(link_idx)
            
            # Si és un PDF local, esborrar el fitxer físic del disc
            if doc_esborrar["es_pdf"]:
                emb_folder = secure_filename(df.at[idx, "Nom"])
                rel_path = doc_esborrar["url"].replace(f"/uploads/{emb_folder}/", "")
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder, rel_path)
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except Exception: pass
            
            # Tornar a construir la cadena d'enllaços per guardar
            nous_enllacs_str = " | ".join([f"[{d['titol']}|{d['url']}]" for d in enllacs])
            df.at[idx, "Enllacs"] = nous_enllacs_str
            guardar_embarcacions(df)
            
    return redirect(url_for("embarcacions.gestio_documents", idx=idx))

@embarcacions_bp.route("/afegir_embarcacio", methods=["POST"])
def afegir_embarcacio():
    nom = request.form.get("nom", "").strip()
    client = request.form.get("client_propietari", "").strip()
    
    marca_motor = request.form.get("marca_motor", "").strip()
    if marca_motor == "ALTRES": marca_motor = request.form.get("marca_motor_custom", "").strip()
        
    model_motor = request.form.get("model_motor", "").strip()
    if model_motor == "ALTRES": model_motor = request.form.get("model_motor_custom", "").strip()
        
    if marca_motor and model_motor: guardar_nou_motor_custom(marca_motor, model_motor)

    num_motors = request.form.get("num_motors", "1").strip()
    num_motors_int = int(num_motors) if num_motors.isdigit() else 1

    series_list = [request.form.get(f"num_serie_{i}", "").strip() for i in range(num_motors_int)]
    hores_list = [request.form.get(f"hores_motor_{i}", "").strip() for i in range(num_motors_int)]
    
    num_serie_str = ", ".join(series_list)
    hores_str = ", ".join(hores_list)

    data_hores = request.form.get("data_hores", "").strip()
    model_barco = request.form.get("model_barco", "").strip()
    matricula = request.form.get("matricula", "").strip()
    port = request.form.get("port", "").strip()
    amarre = request.form.get("amarre", "").strip()
    claus = request.form.get("claus", "").strip()
    comentaris = request.form.get("comentaris", "").strip()
    
    enllac_inicial = ""
    tipus_doc = request.form.get("tipus_doc")
    titol_doc = request.form.get("titol_doc", "").strip()
    
    if tipus_doc == "pdf":
        file = request.files.get("pdf_file")
        if file and file.filename != '':
            emb_folder = secure_filename(nom)
            dest_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
            os.makedirs(dest_dir, exist_ok=True)
            filename = f"DOC_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
            file.save(os.path.join(dest_dir, filename))
            url_final = f"/uploads/{emb_folder}/{filename}"
            if not titol_doc: titol_doc = secure_filename(file.filename)
            enllac_inicial = f"[{titol_doc}|{url_final}]"
    elif tipus_doc == "url":
        url_input = request.form.get("url_doc", "").strip()
        if titol_doc and url_input: enllac_inicial = f"[{titol_doc}|{url_input}]"

    historial_str = ""
    if any(hores_list):
        data_format = datetime.strptime(data_hores, "%Y-%m-%d").strftime("%d/%m/%Y") if data_hores else datetime.now().strftime("%d/%m/%Y")
        historial_str = f"[{data_format}: {hores_str} h]"

    if nom:
        df = carregar_embarcacions()
        nova = pd.DataFrame([{
            "Nom": nom, "Client_Propietari": client, "Marca_Motor": marca_motor, "Model_Motor": model_motor,
            "Num_Motors": num_motors, "Num_Serie_Motors": num_serie_str, "Hores_Motor": hores_str, "Data_Hores": data_hores, 
            "Historial_Hores": historial_str, "Enllacs": enllac_inicial, "Model_Barco": model_barco, "Matricula": matricula, 
            "Port": port, "Amarre": amarre, "Claus": claus, "Comentaris": comentaris
        }])
        df = pd.concat([df, nova], ignore_index=True)
        guardar_embarcacions(df)
        
    return redirect(url_for("embarcacions.vista_embarcacions"))

@embarcacions_bp.route("/actualitzar_hores", methods=["POST"])
def actualitzar_hores():
    idx = int(request.form.get("csv_index"))
    df = carregar_embarcacions()
    num_m = int(df.at[idx, "Num_Motors"]) if str(df.at[idx, "Num_Motors"]).isdigit() else 1
    
    noves_hores_list = [request.form.get(f"noves_hores_{i}", "").strip() for i in range(num_m)]
    nova_data = request.form.get("nova_data", "").strip()
    
    if any(noves_hores_list):
        hores_str = ", ".join(noves_hores_list)
        data_format = datetime.strptime(nova_data, "%Y-%m-%d").strftime("%d/%m/%Y") if nova_data else datetime.now().strftime("%d/%m/%Y")
        nou_reg = f"[{data_format}: {hores_str} h]"
        hist_act = df.at[idx, "Historial_Hores"]
        df.at[idx, "Historial_Hores"] = f"{hist_act} | {nou_reg}" if hist_act else nou_reg
        df.at[idx, "Hores_Motor"] = hores_str
        df.at[idx, "Data_Hores"] = nova_data
        guardar_embarcacions(df)
        
    return redirect(url_for("embarcacions.vista_embarcacions"))

@embarcacions_bp.route("/editar_embarcacio", methods=["POST"])
def editar_embarcacio():
    idx = int(request.form.get("csv_index"))
    df = carregar_embarcacions()
    
    if 0 <= idx < len(df):
        marca_motor = request.form.get("marca_motor", "").strip()
        if marca_motor == "ALTRES": 
            marca_motor = request.form.get("marca_motor_custom", "").strip()
            
        model_motor = request.form.get("model_motor", "").strip()
        if model_motor == "ALTRES": 
            model_motor = request.form.get("model_motor_custom", "").strip()
        
        if marca_motor and model_motor: 
            guardar_nou_motor_custom(marca_motor, model_motor)

        num_motors = request.form.get("num_motors", "1").strip()
        num_motors_int = int(num_motors) if num_motors.isdigit() else 1

        series_list = [request.form.get(f"num_serie_{i}", "").strip() for i in range(num_motors_int)]
        hores_list = [request.form.get(f"hores_motor_{i}", "").strip() for i in range(num_motors_int)]
        
        num_serie_str = ", ".join(series_list)
        hores_str = ", ".join(hores_list)
        
        nova_data = request.form.get("data_hores", "").strip()

        df.at[idx, "Nom"] = request.form.get("nom", "").strip()
        df.at[idx, "Client_Propietari"] = request.form.get("client_propietari", "").strip()
        df.at[idx, "Marca_Motor"] = marca_motor
        df.at[idx, "Model_Motor"] = model_motor
        df.at[idx, "Num_Motors"] = num_motors
        df.at[idx, "Num_Serie_Motors"] = num_serie_str
        
        # Si les hores han canviat, actualitzar camp i afegir registre a l'historial
        if hores_str and hores_str != df.at[idx, "Hores_Motor"]:
            data_format = datetime.strptime(nova_data, "%Y-%m-%d").strftime("%d/%m/%Y") if nova_data else datetime.now().strftime("%d/%m/%Y")
            nou_reg = f"[{data_format}: {hores_str} h]"
            hist_act = df.at[idx, "Historial_Hores"]
            df.at[idx, "Historial_Hores"] = f"{hist_act} | {nou_reg}" if hist_act else nou_reg
            df.at[idx, "Hores_Motor"] = hores_str
            df.at[idx, "Data_Hores"] = nova_data

        df.at[idx, "Model_Barco"] = request.form.get("model_barco", "").strip()
        df.at[idx, "Matricula"] = request.form.get("matricula", "").strip()
        df.at[idx, "Port"] = request.form.get("port", "").strip()
        df.at[idx, "Amarre"] = request.form.get("amarre", "").strip()
        df.at[idx, "Claus"] = request.form.get("claus", "").strip()
        df.at[idx, "Comentaris"] = request.form.get("comentaris", "").strip()
        
        guardar_embarcacions(df)
        
    return redirect(url_for("embarcacions.vista_embarcacions"))

@embarcacions_bp.route("/eliminar_embarcacio", methods=["POST"])
def eliminar_embarcacio():
    idx = int(request.form.get("csv_index"))
    df = carregar_embarcacions()
    if 0 <= idx < len(df):
        df = df.drop(idx).reset_index(drop=True)
        guardar_embarcacions(df)
    return redirect(url_for("embarcacions.vista_embarcacions"))
