from flask import Blueprint, render_template, request, redirect, url_for, current_app
import pandas as pd
import os, re
import json
from werkzeug.utils import secure_filename
from db import carregar_tasques, guardar_tasques, carregar_operaris
from routes.embarcacions import carregar_embarcacions
from routes.operari import extreure_historial_hores, extreure_historial_material, calcular_total_formatted, extreure_historial_material_no_subministrat
from datetime import datetime, timedelta

tasques_bp = Blueprint('tasques', __name__)

@tasques_bp.route("/tasques", methods=["GET"])
def vista_tasques():
    df_tasques = carregar_tasques()
    df_emb = carregar_embarcacions()
    operaris = carregar_operaris()
    
    tasques_llista = []
    task_view_idx = request.args.get("view_idx", type=int)
    task_edit_idx = request.args.get("edit_idx", type=int)
    
    tasca_view = None
    tasca_edit = None
    
    if not df_tasques.empty:
        if "Data_Creacio" not in df_tasques.columns:
            df_tasques["Data_Creacio"] = ""
        if "Project_Manager" not in df_tasques.columns:
            df_tasques["Project_Manager"] = ""

        for idx, row in df_tasques.iterrows():
            item = row.to_dict()
            item["csv_index"] = idx
            item["hores_formatted"] = calcular_total_formatted(item.get("Comentaris_Operari", ""))
            item["historial_hores"] = extreure_historial_hores(item.get("Comentaris_Operari", ""))
            item["historial_material"] = extreure_historial_material(item.get("Material_Demanat", ""))
            item["historial_mat_no_subministrat"] = extreure_historial_material_no_subministrat(item.get("Material_No_Subministrat", ""))

            # ⏱️ EXTRACTOR DE CRONÒMETRES ACTIUS PER A L'ADMINISTRADOR
            crono_json = str(row.get("Inici_Crono", "")).strip()
            operaris_cronos_actius = []

            if crono_json.startswith("{"):
                try:
                    crono_dict = json.loads(crono_json)
                    operaris_cronos_actius = [op for op, inici in crono_dict.items() if inici]
                except Exception:
                    pass
            elif crono_json and crono_json.lower() != "nan":
                operaris_cronos_actius = ["General"]

            item["operaris_cronos_actius"] = operaris_cronos_actius

            emb_folder = secure_filename(item.get("Embarcació", "GENERAL"))
            folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
            fotos = []
            if os.path.exists(folder_path):
                fotos = [f"/uploads/{emb_folder}/{f}" for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            item["fotos"] = fotos
            
            tasques_llista.append(item)
            
            if task_view_idx is not None and task_view_idx == idx:
                tasca_view = item
                
            if task_edit_idx is not None and task_edit_idx == idx:
                tasca_edit = item

    embarcacions_llista = sorted(df_emb["Nom"].dropna().unique().tolist()) if not df_emb.empty and "Nom" in df_emb.columns else []

    return render_template(
        "tasques.html", 
        tasques=tasques_llista, 
        embarcacions=embarcacions_llista, 
        operaris=operaris,
        tasca_view=tasca_view,
        tasca_edit=tasca_edit
    )

@tasques_bp.route("/afegir_tasca", methods=["POST"])
def afegir_tasca():
    operaris_llista = request.form.getlist("operaris")
    operaris_str = ", ".join(operaris_llista) if operaris_llista else request.form.get("operari", "").strip()
    
    embarcacio = request.form.get("embarcacio", "").strip()
    titol = request.form.get("titol", "").strip()
    project_manager = request.form.get("project_manager", "").strip()
    detall = request.form.get("detall", "").strip()
    prioritat = request.form.get("prioritat", "Normal")
    estat_inicial = request.form.get("estat_inicial", "Pendent").strip()
    
    avui_str = datetime.now().strftime("%Y-%m-%d")
    data_inici = request.form.get("data_inici", "").strip()
    data_fi = request.form.get("data_fi", "").strip()
    
    if titol and embarcacio:
        df = carregar_tasques()
        
        if "Data_Inici" not in df.columns: df["Data_Inici"] = ""
        if "Data_Fi" not in df.columns: df["Data_Fi"] = ""
        if "Data_Creacio" not in df.columns: df["Data_Creacio"] = ""
        if "Project_Manager" not in df.columns: df["Project_Manager"] = ""
        
        nova_tasca = pd.DataFrame([{
            "Embarcació": embarcacio,
            "Titol_Tasca": titol,
            "Project_Manager": project_manager,
            "Tasques_Detall": detall,
            "Operari": operaris_str,
            "Prioritat": prioritat,
            "Estat": estat_inicial,
            "Data_Creacio": avui_str,
            "Data_Inici": data_inici,
            "Data_Fi": data_fi,
            "Inici_Crono": "",
            "Hores_Imputades": "0",
            "Comentaris_Operari": "",
            "Notes_Text": "",
            "Material_Demanat": "",
            "Material_No_Subministrat": ""
        }])
        df = pd.concat([df, nova_tasca], ignore_index=True)
        guardar_tasques(df)
        
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/editar_tasca", methods=["POST"])
def editar_tasca():
    idx = int(request.form.get("csv_index"))
    df = carregar_tasques()
    
    if 0 <= idx < len(df):
        operaris_llista = request.form.getlist("operaris")
        operaris_str = ", ".join(operaris_llista) if operaris_llista else request.form.get("operari", "").strip()
        
        df.at[idx, "Embarcació"] = request.form.get("embarcacio", "").strip()
        df.at[idx, "Titol_Tasca"] = request.form.get("titol", "").strip()
        df.at[idx, "Project_Manager"] = request.form.get("project_manager", "").strip()
        df.at[idx, "Tasques_Detall"] = request.form.get("detall", "").strip()
        df.at[idx, "Operari"] = operaris_str
        df.at[idx, "Prioritat"] = request.form.get("prioritat", "Normal")
        
        if "Data_Inici" not in df.columns: df["Data_Inici"] = ""
        if "Data_Fi" not in df.columns: df["Data_Fi"] = ""
        if "Project_Manager" not in df.columns: df["Project_Manager"] = ""
        
        df.at[idx, "Data_Inici"] = request.form.get("data_inici", "").strip()
        df.at[idx, "Data_Fi"] = request.form.get("data_fi", "").strip()
        
        guardar_tasques(df)
        
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/canviar_estat_tasca", methods=["POST"])
def canviar_estat_tasca():
    idx = int(request.form.get("csv_index"))
    nou_estat = request.form.get("nou_estat")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        df.at[idx, "Estat"] = nou_estat
        guardar_tasques(df)
        
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/aprovar_pressupost", methods=["POST"])
def aprovar_pressupost():
    idx = int(request.form.get("csv_index"))
    df = carregar_tasques()
    if 0 <= idx < len(df):
        df.at[idx, "Estat"] = "Pendent"
        guardar_tasques(df)
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/eliminar_tasca", methods=["POST"])
def eliminar_tasca():
    idx = int(request.form.get("csv_index"))
    df = carregar_tasques()
    if 0 <= idx < len(df):
        df = df.drop(idx).reset_index(drop=True)
        guardar_tasques(df)
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/arxiu", methods=["GET"])
def vista_arxiu():
    df_tasques = carregar_tasques()
    tasques_arxivades = []
    
    if not df_tasques.empty:
        for idx, row in df_tasques.iterrows():
            item = row.to_dict()
            item["csv_index"] = idx
            
            if str(item.get("Estat", "")).strip() == "Arxivada":
                item["hores_formatted"] = calcular_total_formatted(item.get("Comentaris_Operari", ""))
                tasques_arxivades.append(item)

    return render_template("arxiu.html", tasques=tasques_arxivades)

@tasques_bp.route("/arxivar_tasca", methods=["POST"])
def arxivar_tasca():
    idx = int(request.form.get("csv_index"))
    accio = request.form.get("accio", "arxivar")
    redirect_to = request.form.get("redirect_to", "tasques")
    
    df = carregar_tasques()
    if 0 <= idx < len(df):
        if accio == "arxivar":
            df.at[idx, "Estat"] = "Arxivada"
        else:
            df.at[idx, "Estat"] = "Finalitzada"
            
        guardar_tasques(df)
        
    if redirect_to == "arxiu":
        return redirect(url_for("tasques.vista_arxiu"))
    elif redirect_to == "operari":
        operari_sel = request.form.get("operari_sel", "")
        return redirect(url_for("operari.vista_operari", operari=operari_sel))
    return redirect(url_for("tasques.vista_tasques"))

@tasques_bp.route("/toggle_pressupost_enviat", methods=["POST"])
def toggle_pressupost_enviat():
    idx = int(request.form.get("csv_index"))
    df = carregar_tasques()
    
    if 0 <= idx < len(df):
        if "Pressupost_Enviat" not in df.columns:
            df["Pressupost_Enviat"] = "0"
            
        estat_actual = str(df.at[idx, "Pressupost_Enviat"]).strip()
        df.at[idx, "Pressupost_Enviat"] = "0" if estat_actual == "1" else "1"
        guardar_tasques(df)
        
    return redirect(url_for("tasques.vista_tasques"))

