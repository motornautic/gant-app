from flask import Blueprint, render_template, request, jsonify
import pandas as pd
from datetime import datetime, timedelta
from db import carregar_tasques, guardar_tasques, carregar_operaris

gantt_bp = Blueprint('gantt', __name__)

PALETA_COLORS_FIXES = {
    "AMIN": "#3b82f6",       # Blau
    "ARMANDO": "#10b981",    # Verd esmeralda
    "BRETT": "#f59e0b",      # Taronja càlid
    "DALMAU": "#8b5cf6",     # Lila
    "DANI": "#15803d",       # Verd fosc
    "ERIC": "#06b6d4",       # Cjan / Blau cel
    "LEO": "#f97316",        # Taronja fort
    "MARC": "#64748b",       # Gris
    "ORIOL": "#2563eb",      # Blau intens
    "RAUL": "#059669",       # Verd
    "SOLA": "#e11d48",       # Vermell carmesí
    "TONI": "#a855f7"        # Púrpura
}

COLORS_RESERVA = [
    "#0284c7", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#ea580c", "#475569"
]

@gantt_bp.route("/gantt", methods=["GET"])
def vista_gantt():
    df = carregar_tasques()
    operaris = carregar_operaris()
    
    # Assignar color a cada operari
    mapa_colors = {}
    for idx, op in enumerate(operaris):
        op_key = op.strip().upper()
        if op_key in PALETA_COLORS_FIXES:
            mapa_colors[op] = PALETA_COLORS_FIXES[op_key]
        else:
            mapa_colors[op] = COLORS_RESERVA[idx % len(COLORS_RESERVA)]
            
    # Color negre per a "Sense assignar"
    mapa_colors["Sense assignar"] = "#000000"

    tasques_gantt = []
    avui_dt = datetime.now()
    avui_str = avui_dt.strftime("%Y-%m-%d")
    dema_str = (avui_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    limit_7_dies_enrere = (avui_dt - timedelta(days=7)).date()

    if not df.empty:
        temp_list = []
        
        for idx, row in df.iterrows():
            estat = str(row.get("Estat", "Pendent")).strip()
            arxivada = str(row.get("Arxivada", "")).strip().lower()

            # 🚫 OMETRE TASQUES ARXIVADES
            if estat.lower() == "arxivada" or arxivada in ["true", "1", "si", "sí"]:
                continue

            data_inici = str(row.get("Data_Inici", "")).strip() or avui_str
            data_fi = str(row.get("Data_Fi", "")).strip() or dema_str
            
            try: 
                dt_inici = datetime.strptime(data_inici, "%Y-%m-%d").date()
            except: 
                dt_inici = avui_dt.date()
                data_inici = avui_str
            
            try: 
                dt_fi = datetime.strptime(data_fi, "%Y-%m-%d").date()
            except: 
                dt_fi = avui_dt.date()
                data_fi = dema_str

            if dt_fi < limit_7_dies_enrere:
                continue

            progres = 0
            if estat == "En Curs": progres = 50
            elif estat == "Esperant Recanvi": progres = 25
            elif estat == "Finalitzada": progres = 100

            operari_raw = str(row.get("Operari", "Sense assignar")).strip()
            primer_operari = operari_raw.split(",")[0].strip() if operari_raw else "Sense assignar"
            color_tasca = mapa_colors.get(primer_operari, "#000000")

            op_class_name = "".join(e for e in primer_operari if e.isalnum()).lower()

            temp_list.append({
                "id": str(idx),
                "name": f"⛵ {row.get('Embarcació', '')} - {row.get('Titol_Tasca', '')} ({operari_raw})",
                "embarcacio": str(row.get('Embarcació', '')),
                "titol_tasca": str(row.get('Titol_Tasca', '')),
                "start": data_inici,
                "end": data_fi,
                "progress": progres,
                "dependencies": "",
                "custom_class": f"op-class-{op_class_name} task-op-{idx}",
                "color": color_tasca,
                "operari": operari_raw,
                "primer_operari": primer_operari,
                "estat": estat
            })

        temp_list.sort(key=lambda x: (x["primer_operari"].upper(), x["start"]))
        tasques_gantt = temp_list

    return render_template("gantt.html", tasques_json=tasques_gantt, operaris=operaris, mapa_colors=mapa_colors)

@gantt_bp.route("/actualitzar_dates_gantt", methods=["POST"])
def actualitzar_dates_gantt():
    data = request.get_json()
    try:
        idx = int(data.get("id"))
        start_str = data.get("start")
        end_str = data.get("end")
        nou_operari = data.get("operari")

        df = carregar_tasques()
        
        if "Data_Inici" not in df.columns: df["Data_Inici"] = ""
        if "Data_Fi" not in df.columns: df["Data_Fi"] = ""
        if "Operari" not in df.columns: df["Operari"] = ""

        if 0 <= idx < len(df):
            df.at[idx, "Data_Inici"] = start_str
            df.at[idx, "Data_Fi"] = end_str
            
            if nou_operari is not None:
                df.at[idx, "Operari"] = nou_operari
            
            guardar_tasques(df)
            return jsonify({"status": "success", "message": "Fitxa actualitzada correctament"})
        
        return jsonify({"status": "error", "message": "Índex de tasca no trobat"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
