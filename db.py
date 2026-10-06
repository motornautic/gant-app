import os
import pandas as pd
from sqlalchemy import create_engine

# Detectar la connexió de PostgreSQL a Railway o utilitzar fitxers CSV en local
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
        
def get_engine():
    if DATABASE_URL:
        return create_engine(DATABASE_URL)
    return None

def carregar_taula(nom_taula, fitxer_csv, columnes_default):
    engine = get_engine()
    if engine:
        try:
            df = pd.read_sql_table(nom_taula, con=engine, dtype=str).fillna("")
            for col in columnes_default:
                if col not in df.columns:
                    df[col] = ""
            return df
        except Exception:
            # Si la taula encara no existeix a PostgreSQL, carrega el CSV local
            pass
    
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
            df.to_sql(nom_taula, con=engine, if_exists="replace", index=False)
        except Exception as e:
            print(f"Error guardant a Postgres: {e}")

    # Guardar sempre una còpia en CSV per seguretat
    path = os.path.join(os.getcwd(), fitxer_csv)
    df.to_csv(path, index=False)

# --- FUNCIONS ESPECÍFIQUES DEL TEU PROJECTE ---

# ARTICLES
def carregar_articles():
    return carregar_taula("articles", "data/articles.csv", ["Ref", "Ref_Interna", "Descripcio", "Stock", "Ubicacio"])

def guardar_articles(df):
    guardar_taula(df, "articles", "data/articles.csv")

# OPERARIS
def carregar_operaris():
    df = carregar_taula("operaris", "operaris.csv", ["Nom", "Cognoms", "Telefon", "Email", "Password"])
    return df["Nom"].dropna().unique().tolist() if not df.empty and "Nom" in df.columns else []

# TASQUES
def carregar_tasques():
    return carregar_taula("tasques", "tasques.csv", ["Embarcació", "Titol_Tasca", "Operari", "Estat", "Data_Inici"])

def guardar_tasques(df):
    guardar_taula(df, "tasques", "tasques.csv")

# ADMINS
def carregar_admins():
    return carregar_taula("admins", "admins.csv", ["Usuari", "Password"])

def guardar_admins(df):
    guardar_taula(df, "admins", "admins.csv")

# CLIENTS
def carregar_clients():
    return carregar_taula("clients", "clients.csv", ["Nom", "Telefon", "Email"])

def guardar_clients(df):
    guardar_taula(df, "clients", "clients.csv")

# EMBARCACIONS
def carregar_embarcacions():
    return carregar_taula("embarcacions", "embarcacions.csv", ["Nom", "Model", "Client"])

def guardar_embarcacions(df):
    guardar_taula(df, "embarcacions", "embarcacions.csv")

