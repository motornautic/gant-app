@operari_bp.route("/operari", methods=["GET"])
def vista_operari():
    operaris = carregar_operaris()
    
    # 1. Prioritzem l'operari indicat per la URL, per la sessió o per la cookie
    operari_req = request.args.get("operari")
    operari_autenticat = session.get("operari_autenticat") or request.cookies.get("operari_saved")
    
    operari_sel = operari_req or operari_autenticat

    # 2. Si tenim un operari identificat, el gravem clarament a la sessió de Flask
    if operari_sel:
        session["operari_autenticat"] = operari_sel

    # 3. El mode administració NOMÉS s'activa si s'ha entrat com a admin I NO hi ha cap operari actiu treballant
    es_admin = bool(session.get("admin_autenticat")) and not bool(session.get("operari_autenticat"))

    # Si no hi ha cap operari assignat, mostrem el formulari d'accés
    if not operari_sel:
        return render_template("login_operari.html", operaris=operaris, operari_sel=None, error=request.args.get("error_auth"))

    confirm_idx = request.args.get("confirm_idx", type=int)
    edit_reg_info = {"task_idx": request.args.get("edit_task_idx", type=int), "reg_idx": request.args.get("edit_reg_idx", type=int)}
    
    df_articles = carregar_articles()
    llista_articles = []
    if not df_articles.empty:
        for _, row in df_articles.iterrows():
            ref = str(row.get("Ref", "")).strip()
            ref_int = str(row.get("Ref_Interna", "")).strip()
            desc = str(row.get("Descripcio", "")).strip()
            stock = str(row.get("Stock", "0")).strip()
            ubicacio = str(row.get("Ubicacio", "")).strip()
            
            if ref:
                etiqueta = ref
                if ref_int: etiqueta += f" (INT: {ref_int})"
                if desc: etiqueta += f" - {desc}"
                
                detalls_extra = []
                if stock: detalls_extra.append(f"Stock: {stock}")
                if ubicacio: detalls_extra.append(f"Ubicació: {ubicacio}")
                
                if detalls_extra:
                    etiqueta += f" [{ ' | '.join(detalls_extra) }]"
                
                llista_articles.append({
                    "ref": ref,
                    "etiqueta": etiqueta
                })

    df_tasques = carregar_tasques()
    tasques_op = []
    
    perfil_data = {"Nom": operari_sel, "Cognoms": "", "Telefon": "", "Email": ""}
    df_op = carregar_df_operaris()
    if not df_op.empty and "Nom" in df_op.columns and operari_sel:
        row_op = df_op[df_op["Nom"].str.upper() == operari_sel.upper()]
        if not row_op.empty:
            perfil_data["Cognoms"] = str(row_op.iloc[0].get("Cognoms", "")).strip()
            perfil_data["Telefon"] = str(row_op.iloc[0].get("Telefon", "")).strip()
            perfil_data["Email"] = str(row_op.iloc[0].get("Email", "")).strip()

    if not df_tasques.empty and operari_sel:
        for idx, row in df_tasques.iterrows():
            operaris_assignats = [op.strip() for op in str(row.get("Operari", "")).split(",") if op.strip()]
            data_inici_val = str(row.get("Data_Inici", "")).strip()
            estat_val = str(row.get("Estat", "")).strip()
            
            if operari_sel in operaris_assignats and estat_val not in ["Arxivada", "Pressupost"] and data_inici_val != "":
                item = row.to_dict()
                item["csv_index"] = idx
                
                crono_dict = {}
                json_str = str(item.get("Inici_Crono", ""))
                if json_str.startswith("{"):
                    try: crono_dict = json.loads(json_str)
                    except Exception: pass
                elif json_str:
                    crono_dict = {"General": json_str}
                
                item["crono_actiu_operari"] = crono_dict.get(operari_sel, "")
                item["hores_formatted"] = calcular_total_formatted(item.get("Comentaris_Operari", ""))
                item["historial_hores"] = extreure_historial_hores(item.get("Comentaris_Operari", ""))
                item["historial_material"] = extreure_historial_material(item.get("Material_Demanat", ""))
                item["checklist"] = extreure_checklist_items(item.get("Tasques_Detall", ""))
                item["historial_mat_no_subministrat"] = extreure_historial_material_no_subministrat(item.get("Material_No_Subministrat", ""))

                emb_folder = secure_filename(item.get("Embarcació", "GENERAL"))
                folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], emb_folder)
                fotos = []
                if os.path.exists(folder_path):
                    fotos = [f"/uploads/{emb_folder}/{f}" for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                item["fotos"] = fotos
                tasques_op.append(item)

    now_date = datetime.now().strftime("%Y-%m-%d")

    response = make_response(render_template(
        "operari.html", 
        operaris=operaris, 
        operari_sel=operari_sel, 
        perfil=perfil_data, 
        tasques=tasques_op, 
        confirm_idx=confirm_idx, 
        edit_reg_info=edit_reg_info, 
        articles=llista_articles, 
        es_admin=es_admin,
        now_date=now_date
    ))
    
    if operari_sel:
        response.set_cookie("operari_saved", operari_sel, max_age=30*24*3600)
        
    return response

@operari_bp.route("/iniciar_crono", methods=["POST"])
def iniciar_crono():
    idx = int(request.form.get("csv_index"))
    operari_sel = request.form.get("operari_sel", "").strip() or session.get("operari_autenticat", "").strip() or request.cookies.get("operari_saved", "").strip()
    
    df = carregar_tasques()
    
    if 0 <= idx < len(df) and operari_sel:
        # Assegurem la sessió de l'operari
        session["operari_autenticat"] = operari_sel
        
        crono_dict = {}
        json_str = str(df.at[idx, "Inici_Crono"])
        if json_str.startswith("{"):
            try: crono_dict = json.loads(json_str)
            except Exception: pass
            
        crono_dict[operari_sel] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df.at[idx, "Inici_Crono"] = json.dumps(crono_dict)
        df.at[idx, "Estat"] = "En Curs"
        guardar_tasques(df)
        
    return redirect(url_for("operari.vista_operari", operari=operari_sel))


