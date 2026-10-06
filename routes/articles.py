from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash
import pandas as pd
import io
import os
from db import carregar_articles, guardar_articles

articles_bp = Blueprint('articles', __name__)

@articles_bp.route("/articles", methods=["GET"])
def vista_articles():
    df = carregar_articles()
    
    # Cerca per text (filtre)
    cerca = request.args.get("cerca", "").strip().lower()
    
    articles = []
    if not df.empty:
        for idx, row in df.iterrows():
            ref = str(row.get("Ref", "")).strip()
            ref_int = str(row.get("Ref_Interna", "")).strip()
            desc = str(row.get("Descripcio", "")).strip()
            
            if cerca:
                if cerca not in ref.lower() and cerca not in ref_int.lower() and cerca not in desc.lower():
                    continue
            
            articles.append({
                "csv_index": idx,
                "ref": ref,
                "ref_interna": ref_int,
                "descripcio": desc
            })
            
    return render_template("articles.html", articles=articles, cerca=cerca)

@articles_bp.route("/afegir_article", methods=["POST"])
def afegir_article():
    ref = request.form.get("ref", "").strip()
    ref_int = request.form.get("ref_interna", "").strip()
    desc = request.form.get("descripcio", "").strip()

    df = carregar_articles()
    nou_article = pd.DataFrame([{
        "Ref": ref,
        "Ref_Interna": ref_int,
        "Descripcio": desc
    }])
    
    df = pd.concat([df, nou_article], ignore_index=True)
    guardar_articles(df)
    
    return redirect(url_for("articles.vista_articles"))

@articles_bp.route("/eliminar_article", methods=["POST"])
def eliminar_article():
    idx = int(request.form.get("csv_index"))
    df = carregar_articles()
    if 0 <= idx < len(df):
        df = df.drop(index=idx).reset_index(drop=True)
        guardar_articles(df)
    return redirect(url_for("articles.vista_articles"))

# 📥 IMPORTAR ARTICLES DES D'EXCEL / CSV
@articles_bp.route("/importar_articles", methods=["POST"])
def importar_articles():
    if 'fitxer_excel' not in request.files:
        return redirect(url_for("articles.vista_articles"))
    
    file = request.files['fitxer_excel']
    if file.filename == '':
        return redirect(url_for("articles.vista_articles"))

    try:
        # Llegir segons si és .xlsx, .xls o .csv
        if file.filename.endswith('.csv'):
            df_nou = pd.read_csv(file, dtype=str).fillna("")
        else:
            df_nou = pd.read_excel(file, dtype=str).fillna("")

        # Normalitzar columnes (accepta majúscules/minúscules o accents comuns)
        columnes_map = {}
        for col in df_nou.columns:
            c_clean = col.strip().lower()
            if "interna" in c_clean or "int" in c_clean:
                columnes_map[col] = "Ref_Interna"
            elif "desc" in c_clean or "nom" in c_clean:
                columnes_map[col] = "Descripcio"
            elif "ref" in c_clean or "codi" in c_clean or "article" in c_clean:
                columnes_map[col] = "Ref"

        df_nou = df_nou.rename(columns=columnes_map)

        # Assegurar columnes requerides
        for c in ["Ref", "Ref_Interna", "Descripcio"]:
            if c not in df_nou.columns:
                df_nou[c] = ""

        df_nou = df_nou[["Ref", "Ref_Interna", "Descripcio"]]

        # Carregar existents i fusionar
        df_existent = carregar_articles()
        df_final = pd.concat([df_existent, df_nou], ignore_index=True).drop_duplicates(subset=["Ref"], keep="last")
        
        guardar_articles(df_final)

    except Exception as e:
        print(f"Error en importar Excel: {e}")

    return redirect(url_for("articles.vista_articles"))

# 📤 EXPORTAR ARTICLES A EXCEL (.XLSX)
@articles_bp.route("/exportar_articles", methods=["GET"])
def exportar_articles():
    df = carregar_articles()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Articles')
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="cataleg_articles.xlsx"
    )