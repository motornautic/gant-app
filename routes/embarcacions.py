from flask import Blueprint, render_template, request, redirect, url_for, current_app, send_file, abort, session
import pandas as pd
import os, re, json, io
from io import BytesIO
from uuid import uuid4
from urllib.parse import urlsplit
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename
from routes.clients import carregar_clients
# 🚀 IMPORTEM DE DB.PY PER GARANTIR LA CONEXIÓ AMB POSTGRESQL
from db import carregar_embarcacions, guardar_embarcacions

embarcacions_bp = Blueprint('embarcacions', __name__)

# Protecció complementària: totes les operacions de modificació són exclusives de l'administració.
@embarcacions_bp.before_request
def protegir_modificacions_embarcacions():
    if request.method == "GET" or session.get("admin_autenticat"):
        return
    # Les úniques excepcions: afegir documents o fotografies des de la fitxa.
    if (request.endpoint in ("embarcacions.afegir_document_fitxa", "embarcacions.pujar_foto_fitxa")
            and session.get("operari_autenticat")):
        return
    abort(403)

JSON_MOTORS_CUSTOM = "motors_custom.json"

DIC_MOTORS_BASE = {
    "Caterpillar": ["3208", "C12", "C18", "C32", "C7", "C9"],
    "Cummins": ["QSB 5.9", "QSB 6.7", "QSC 8.3", "QSL 9", "QSM 11"],
    "MAN": ["V12-1550", "V12-1900", "V8-1000", "V8-1200", "i6-730"],
    "Mercury / Mercruiser": ["350 MAG MPI", "4.3 MPI", "5.0 MPI", "5.7L", "6.2L V8", "8.2 MAG", "F115 EFI", "F150 EFI", "F200 Verado", "F350 Verado"],
    "Suzuki": ["DF115B", "DF140B", "DF150AP", "DF200AP", "DF250AP", "DF300AP", "DF350A", "DF90A"],
    "Volvo Penta": ["D1-13", "D1-20", "D1-30", "D11-670", "D13-900", "D2-40", "D2-50", "D2-60", "D2-75", "D3-110", "D3-150", "D3-220", "D4-180", "D4-225", "D4-260", "D4-300", "D6-310", "D6-370", "D6-435", "KAD300", "KAD32", "KAD42", "KAD43", "KAD44", "TAMD41"],
    "Yanmar": ["1GM10", "2YM15", "3JH40", "3YM20", "3YM30AE", "4JH110", "4JH45", "4JH57", "4JH80", "4LHA-STP", "6CX530", "6LPA-STP", "6LY400"]
}



def estampar_data_fotografia(dades_fitxer, extensio, text_data):
    """Afegeix la data/hora a la cantonada inferior dreta de la fotografia."""
    with Image.open(BytesIO(dades_fitxer)) as img:
        img = ImageOps.exif_transpose(img)
        format_original = (img.format or '').upper()

        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA')
        elif img.mode == 'RGB':
            img = img.convert('RGBA')

        draw = ImageDraw.Draw(img)

        ample, alt = img.size
        font_size = max(30, int(min(ample, alt) * 0.065))
        try:
            font = ImageFont.truetype('DejaVuSans-Bold.ttf', font_size)
        except Exception:
            font = ImageFont.load_default()

        # Evitem que la data surti tallada en fotos verticals o estretes.
        bbox = draw.textbbox((0, 0), text_data, font=font)
        while bbox[2] - bbox[0] > ample * 0.83 and font_size > 16:
            font_size -= 2
            try:
                font = ImageFont.truetype('DejaVuSans-Bold.ttf', font_size)
            except Exception:
                break
            bbox = draw.textbbox((0, 0), text_data, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        padding_x = max(12, int(font_size * 0.55))
        padding_y = max(8, int(font_size * 0.35))
        marge = max(12, int(font_size * 0.6))

        x1 = ample - text_w - (padding_x * 2) - marge
        y1 = alt - text_h - (padding_y * 2) - marge
        x2 = ample - marge
        y2 = alt - marge

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle([x1, y1, x2, y2], radius=max(8, int(font_size * 0.35)), fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img, overlay)

        draw = ImageDraw.Draw(img)
        draw.text((x1 + padding_x, y1 + padding_y), text_data, fill=(255, 255, 255, 255), font=font)

        out = BytesIO()
        ext = (extensio or '').lower()
        if ext in ('.jpg', '.jpeg') or format_original in ('JPEG', 'JPG'):
            img = img.convert('RGB')
            img.save(out, format='JPEG', quality=92, optimize=True)
        elif ext == '.png' or format_original == 'PNG':
            img.save(out, format='PNG', optimize=True)
        else:
            img.save(out, format='WEBP', quality=92, method=6)

        return out.getvalue()

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

@embarcacions_bp.route("/embarcacions", methods=["GET"])
def vista_embarcacions():
    df_emb = carregar_embarcacions()
    df_cli = carregar_clients()
    dic_motors = carregar_diccionari_motors()
    
    sort_by = request.args.get("sort_by", "nom_asc")
    
    llista_clients_noms = []
    if not df_cli.empty:
        for _, r in df_cli.iterrows():
            nom_comp = f"{r['Nom']} {r['Cognoms']}".strip() if r.get('Tipus') == 'Particular' else r.get('Nom', '')
            if nom_comp: llista_clients_noms.append(nom_comp)

    llista_emb = []
    edit_idx = request.args.get("edit_idx", type=int) if session.get("admin_autenticat") else None
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

            emb_folder = secure_filename(str(item.get("Nom", "GENERAL")))
            folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
            fotos = []
            if os.path.exists(folder_path):
                fotos = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            item["num_fotos"] = len(fotos)
            llista_emb.append(item)
            
            if edit_idx is not None and edit_idx == idx:
                emb_edit = item
                
    # Ordenació al backend per defecte
    if sort_by == "nom_asc":
        llista_emb.sort(key=lambda x: str(x.get("Nom", "")).lower())
    elif sort_by == "nom_desc":
        llista_emb.sort(key=lambda x: str(x.get("Nom", "")).lower(), reverse=True)
    elif sort_by == "propietari_asc":
        llista_emb.sort(key=lambda x: str(x.get("Client_Propietari", "")).lower())
    elif sort_by == "propietari_desc":
        llista_emb.sort(key=lambda x: str(x.get("Client_Propietari", "")).lower(), reverse=True)
            
    now_date = datetime.now().strftime("%Y-%m-%d")
    return render_template("embarcacions.html", embarcacions=llista_emb, clients_llista=sorted(llista_clients_noms), dic_motors=dic_motors, edit_idx=edit_idx, emb_edit=emb_edit, now_date=now_date, current_sort=sort_by)

# FITXA INDIVIDUAL D'EMBARCACIÓ (NOMÉS CONSULTA)
@embarcacions_bp.route("/embarcacions/fitxa", methods=["GET"])
def fitxa_embarcacio():
    # Una segona comprovació, independent del middleware.
    if not (session.get("admin_autenticat") or session.get("operari_autenticat")):
        abort(403)

    nom = (request.args.get("nom") or "").strip()
    if not nom:
        abort(404)

    df = carregar_embarcacions()
    if df.empty or "Nom" not in df.columns:
        abort(404)

    coincidencies = df[df["Nom"].astype(str).str.strip().str.casefold() == nom.casefold()]
    if coincidencies.empty:
        abort(404)

    idx = int(coincidencies.index[0])
    embarcacio = coincidencies.iloc[0].to_dict()
    embarcacio["csv_index"] = idx
    embarcacio["historial_hores_llista"] = extreure_historial_hores_motor(embarcacio.get("Historial_Hores", ""))
    embarcacio["enllacs_llista"] = extreure_enllacs(embarcacio.get("Enllacs", ""))

    carpeta = secure_filename(str(embarcacio.get("Nom", "GENERAL")))
    dir_fotos = os.path.join(current_app.config["UPLOAD_FOLDER"], carpeta)
    embarcacio["fotos"] = (
        [f"/uploads/{carpeta}/{f}" for f in sorted(os.listdir(dir_fotos))
         if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        if os.path.isdir(dir_fotos) else []
    )
    return render_template("fitxa_embarcacio.html", e=embarcacio)


# Afegir documents/enllaços a la fitxa (operari o administrador autenticat).
@embarcacions_bp.route("/embarcacions/fitxa/afegir-document", methods=["POST"])
def afegir_document_fitxa():
    if not (session.get("operari_autenticat") or session.get("admin_autenticat")):
        abort(403)

    nom = (request.form.get("nom_embarcacio") or "").strip()
    tipus = request.form.get("tipus_doc", "").strip()
    titol = (request.form.get("titol") or "").strip()
    if not nom or tipus not in ("pdf", "url"):
        abort(400)

    df = carregar_embarcacions()
    if df.empty or "Nom" not in df.columns:
        abort(404)
    trobat = df.index[df["Nom"].astype(str).str.strip().str.casefold() == nom.casefold()]
    if len(trobat) == 0:
        abort(404)
    idx = trobat[0]
    nom_real = str(df.at[idx, "Nom"])
    url_final = ""

    if tipus == "pdf":
        fitxer = request.files.get("pdf_file")
        if not fitxer or not fitxer.filename or not fitxer.filename.lower().endswith(".pdf"):
            abort(400, "Selecciona un arxiu PDF.")
        # Màxim 15 MiB i verificació bàsica de la capçalera PDF.
        dades = fitxer.stream.read(15 * 1024 * 1024 + 1)
        if len(dades) > 15 * 1024 * 1024 or not dades.startswith(b"%PDF-"):
            abort(400, "El PDF no és vàlid o supera els 15 MB.")
        nom_fitxer = secure_filename(fitxer.filename)
        if not nom_fitxer:
            abort(400)
        carpeta = secure_filename(nom_real)
        desti = os.path.join(current_app.config["UPLOAD_FOLDER"], carpeta)
        os.makedirs(desti, exist_ok=True)
        guardat = f"DOC_{uuid4().hex}_{nom_fitxer}"
        with open(os.path.join(desti, guardat), "wb") as f:
            f.write(dades)
        url_final = f"/uploads/{carpeta}/{guardat}"
        if not titol:
            titol = fitxer.filename.rsplit(".", 1)[0]
    else:
        url_final = (request.form.get("url") or "").strip()
        u = urlsplit(url_final)
        if u.scheme not in ("http", "https") or not u.netloc:
            abort(400, "L'enllaç ha de començar per https:// o http://")

    # El format de la columna Enllacs és [títol|URL].
    titol = re.sub(r"[\[\]\|]", "", titol).strip()[:180]
    if not titol or any(c in url_final for c in "[]|"):
        abort(400, "Títol o enllaç no vàlid.")

    entrada = f"[{titol}|{url_final}]"
    actual = str(df.at[idx, "Enllacs"]).strip() if "Enllacs" in df.columns else ""
    if actual.lower() in ("nan", "none"):
        actual = ""
    df.at[idx, "Enllacs"] = f"{actual} | {entrada}" if actual else entrada
    guardar_embarcacions(df)
    return redirect(url_for("embarcacions.fitxa_embarcacio", nom=nom_real, doc_ok=1) + "#documents-embarcacio")


# Pujar una fotografia des de la fitxa individual (operari o administrador).
@embarcacions_bp.route("/embarcacions/fitxa/foto", methods=["POST"])
def pujar_foto_fitxa():
    if not (session.get("admin_autenticat") or session.get("operari_autenticat")):
        abort(403)

    nom = (request.form.get("nom") or "").strip()
    df = carregar_embarcacions()
    if not nom or df.empty or "Nom" not in df.columns:
        abort(404)
    coincidencies = df[df["Nom"].astype(str).str.strip().str.casefold() == nom.casefold()]
    if coincidencies.empty:
        abort(404)
    nom_real = str(coincidencies.iloc[0]["Nom"]).strip()
    fitxer = request.files.get("foto")
    if not fitxer or not fitxer.filename:
        abort(400, "Selecciona una fotografia.")

    mida_max = 12 * 1024 * 1024
    dades = fitxer.read(mida_max + 1)
    if not dades or len(dades) > mida_max:
        abort(413, "La fotografia ha de tenir menys de 12 MB.")
    extensio = os.path.splitext(secure_filename(fitxer.filename))[1].lower()
    signatures = {
        ".jpg": dades.startswith(bytes.fromhex("FFD8FF")),
        ".jpeg": dades.startswith(bytes.fromhex("FFD8FF")),
        ".png": dades.startswith(bytes.fromhex("89504E470D0A1A0A")),
        ".webp": dades.startswith(b"RIFF") and dades[8:12] == b"WEBP",
    }
    if not signatures.get(extensio, False):
        abort(400, "Només s'admeten JPG, PNG o WEBP.")

    carpeta = secure_filename(nom_real)
    if not carpeta:
        abort(400)
    desti = os.path.join(current_app.config["UPLOAD_FOLDER"], carpeta)
    os.makedirs(desti, exist_ok=True)

    moment_foto = datetime.now()
    text_data = moment_foto.strftime("%d/%m/%Y %H:%M")
    try:
        dades_finals = estampar_data_fotografia(dades, extensio, text_data)
    except Exception as e:
        print(f"⚠️ No s'ha pogut estampar la data a la fotografia: {e}")
        abort(400, "No s'ha pogut processar la fotografia.")

    nom_fitxer = f"{moment_foto:%Y%m%d_%H%M%S}_{uuid4().hex[:10]}{extensio}"
    with open(os.path.join(desti, nom_fitxer), "wb") as f:
        f.write(dades_finals)
    return redirect(url_for("embarcacions.fitxa_embarcacio", nom=nom_real, foto_ok=1) + "#fotografies-embarcacio")


# 📊 EXPORTAR EMBARCACIONS A EXCEL
@embarcacions_bp.route("/exportar_embarcacions_excel", methods=["GET"])
def exportar_embarcacions_excel():
    df = carregar_embarcacions()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Embarcacions')
    output.seek(0)
    return send_file(output, download_name="Embarcacions_MotorNautic.xlsx", as_attachment=True)

# 📥 IMPORTAR EMBARCACIONS DES DE FITXER EXCEL
@embarcacions_bp.route("/importar_embarcacions_excel", methods=["POST"])
def importar_embarcacions_excel():
    file = request.files.get("fitxer_excel")
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        df_nou = pd.read_excel(file, dtype=str).fillna("")
        df_nou = df_nou.loc[:, ~df_nou.columns.str.contains('^Unnamed', na=False)]
        
        mapa_columnes = {
            "nom": "Nom", "embarcació": "Nom", "embarcacio": "Nom", "barco": "Nom",
            "client": "Client_Propietari", "client_propietari": "Client_Propietari", "propietari": "Client_Propietari",
            "marca_motor": "Marca_Motor", "marca": "Marca_Motor",
            "model_motor": "Model_Motor", "model": "Model_Motor",
            "num_motors": "Num_Motors", "motors": "Num_Motors",
            "num_serie_motors": "Num_Serie_Motors", "num_serie": "Num_Serie_Motors", "serie": "Num_Serie_Motors",
            "hores_motor": "Hores_Motor", "hores": "Hores_Motor",
            "model_barco": "Model_Barco", "model_embarcacio": "Model_Barco",
            "matricula": "Matricula", "port": "Port", "amarre": "Amarre", "claus": "Claus", "comentaris": "Comentaris"
        }
        
        noves_col = {}
        for col in df_nou.columns:
            col_clean = str(col).strip().lower()
            if col_clean in mapa_columnes:
                noves_col[col] = mapa_columnes[col_clean]
        
        df_nou = df_nou.rename(columns=noves_col)
        df_nou = df_nou.T.groupby(level=0).first().T
        
        df_actual = carregar_embarcacions()
        df_actual = df_actual.loc[:, ~df_actual.columns.duplicated()]
        
        df_fusionat = pd.concat([df_actual, df_nou], ignore_index=True).fillna("")
        df_fusionat = df_fusionat.loc[:, ~df_fusionat.columns.duplicated()]
        
        guardar_embarcacions(df_fusionat)
        
    return redirect(url_for("embarcacions.vista_embarcacions"))

# PÀGINA INDEPENDENT DE GALERIA DE FOTOS
@embarcacions_bp.route("/embarcacions/<int:idx>/fotos", methods=["GET"])
def galeria_fotos(idx):
    df = carregar_embarcacions()
    if idx < 0 or idx >= len(df):
        return redirect(url_for("embarcacions.vista_embarcacions"))
    
    embarcacio = df.iloc[idx].to_dict()
    embarcacio["csv_index"] = idx
    
    emb_folder = secure_filename(str(embarcacio.get("Nom", "GENERAL")))
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
        emb_folder = secure_filename(str(df.at[idx, "Nom"]))
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
        emb_folder = secure_filename(str(df.at[idx, "Nom"]))
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
    emb_nom = str(df.at[idx, "Nom"])
    
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
            
            if doc_esborrar["es_pdf"]:
                emb_folder = secure_filename(str(df.at[idx, "Nom"]))
                rel_path = doc_esborrar["url"].replace(f"/uploads/{emb_folder}/", "")
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder, rel_path)
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except Exception: pass
            
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


































