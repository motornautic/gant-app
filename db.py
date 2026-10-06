import pandas as pd
import os

CSV_TASQUES = "tasques_individuals.csv"
CSV_OPERARIS = "operaris.csv"

def carregar_operaris():
    if os.path.exists(CSV_OPERARIS):
        df = pd.read_csv(CSV_OPERARIS, dtype=str)
        ops = sorted(df["Nom"].dropna().tolist())
        if ops: return ops
    
    defecte = ["MARC", "BRETT", "ERIC", "AMIN", "SOLA", "LEO", "ORIOL"]
    pd.DataFrame({"Nom": defecte}).to_csv(CSV_OPERARIS, index=False)
    return defecte

def carregar_tasques():
    if os.path.exists(CSV_TASQUES):
        df = pd.read_csv(CSV_TASQUES, dtype=str).fillna("")
        for col in ["Embarcació", "Operari", "Titol_Tasca", "Tasques_Detall", "Prioritat", "Hores_Imputades", "Estat", "Inici_Crono", "Comentaris_Operari", "Notes_Text", "Material_Demanat"]:
            if col not in df.columns:
                df[col] = ""
        return df
    
    dades_exemple = [
        {"Embarcació": "PINCOY CBC", "Operari": "AMIN", "Titol_Tasca": "REFREDEDORS", "Tasques_Detall": "NETEJA REFREDEDORS", "Prioritat": "Normal", "Hores_Imputades": "0.0", "Estat": "Pendent", "Inici_Crono": "", "Comentaris_Operari": ""},
        {"Embarcació": "SHAMAN", "Operari": "AMIN", "Titol_Tasca": "PASACASCOS", "Tasques_Detall": "REVISIO PASACASCOS", "Prioritat": "Urgent", "Hores_Imputades": "0.0", "Estat": "Pendent", "Inici_Crono": "", "Comentaris_Operari": ""}
    ]
    df_ex = pd.DataFrame(dades_exemple)
    df_ex.to_csv(CSV_TASQUES, index=False)
    return df_ex

def guardar_tasques(df):
    df.to_csv(CSV_TASQUES, index=False)

ARTICLES_CSV = "data/articles.csv"

def carregar_articles():
    if not os.path.exists(ARTICLES_CSV):
        # 📁 Crear la carpeta 'data' si no existeix abans de guardar
        os.makedirs(os.path.dirname(ARTICLES_CSV), exist_ok=True)
        df = pd.DataFrame(columns=["Ref", "Ref_Interna", "Descripcio"])
        df.to_csv(ARTICLES_CSV, index=False)
        return df
    return pd.read_csv(ARTICLES_CSV, dtype=str).fillna("")

def guardar_articles(df):
    os.makedirs(os.path.dirname(ARTICLES_CSV), exist_ok=True)
    df.to_csv(ARTICLES_CSV, index=False)

CSV_ADMINS = "admins.csv"

def carregar_admins():
    if os.path.exists(CSV_ADMINS):
        df = pd.read_csv(CSV_ADMINS, dtype=str).fillna("")
        if not df.empty:
            return df
    
    # Administrador creat per defecte la primera vegada
    default_admin = [{
        "Usuari": "admin",
        "Nom": "Administrador",
        "Email": "admin@motornautic.com",
        "Password": "admin"  # Podran canviar-la posteriorment
    }]
    df_def = pd.DataFrame(default_admin)
    df_def.to_csv(CSV_ADMINS, index=False)
    return df_def

def guardar_admins(df):
    df.to_csv(CSV_ADMINS, index=False)




