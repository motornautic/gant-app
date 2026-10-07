import os
import pandas as pd
from sqlalchemy import create_engine

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

def get_engine():
    if DATABASE_URL:
        return create_engine(DATABASE_URL, pool_pre_ping=True)
    return None

def carregar_taula(nom_taula, fitxer_csv, columnes_default):
    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                # read_sql_table no accepta dtype=str, ho fem desprès amb .astype(str)
                df = pd.read_sql_table(nom_taula, con=conn).fillna("").astype(str)
                for col in columnes_default:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            print(f"⚠️ No s'ha pogut llegir la taula '{nom_taula}' de Postgres (carregant CSV): {e}")
    
    # Mode Local / Fallback CSV
    path = os.path.join(os.getcwd(), fitxer_csv)
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            for col in columnes_default:
                if col not in df.columns:
                    df[col] = ""
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=columnes_default)

def guardar_taula(df, nom_taula, fitxer_csv):
    engine = get_engine()
    if engine:
        try:
            with engine.begin() as conn:
                df.to_sql(nom_taula, con=conn, if_exists="replace", index=False)
            print(f"✅ Taula '{nom_taula}' guardada correctament a PostgreSQL.")
        except Exception as e:
            print(f"❌ Error guardant la taula '{nom_taula}' a Postgres: {e}")

    try:
        path = os.path.join(os.getcwd(), fitxer_csv)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)
    except Exception as e:
        print(f"Error guardant CSV local: {e}")

# --- FUNCIONS ESPECÍFIQUES ---

def carregar_articles():
    return carregar_taula("articles", "data/articles.csv", ["Ref", "Ref_Interna", "Descripcio", "Stock", "Ubicacio"])

def guardar_articles(df):
    guardar_taula(df, "articles", "data/articles.csv")

def carregar_operaris():
    df = carregar_taula("operaris", "operaris.csv", ["Nom", "Cognoms", "Telefon", "Email", "Password", "Reset_Code", "Reset_Expiry"])
    return df["Nom"].dropna().unique().tolist() if not df.empty and "Nom" in df.columns else []

def carregar_tasques():
    columnes_tasques = [
        "Embarcació", "Titol_Tasca", "Operari", "Estat", "Data_Inici", 
        "Prioritat", "Tasques_Detall", "Comentaris_Operari", "Hores_Imputades", 
        "Inici_Crono", "Material_Demanat", "Material_No_Subministrat", "Notes_Text"
    ]
    return carregar_taula("tasques", "tasques.csv", columnes_tasques)

def guardar_tasques(df):
    guardar_taula(df, "tasques", "tasques.csv")

def carregar_admins():
    return carregar_taula("admins", "admins.csv", ["Usuari", "Password"])

def guardar_admins(df):
    guardar_taula(df, "admins", "admins.csv")

def carregar_clients():
    return carregar_taula("clients", "clients.csv", ["Nom", "Telefon", "Email"])

def guardar_clients(df):
    guardar_taula(df, "clients", "clients.csv")

def carregar_embarcacions():
    return carregar_taula("embarcacions", "embarcacions.csv", ["Nom", "Model", "Client"])

def guardar_embarcacions(df):
    guardar_taula(df, "embarcacions", "embarcacions.csv")
