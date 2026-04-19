# --- BANCO DE DADOS ATUALIZADO ---
class MedidaProtetiva(Base):
    __tablename__ = "medidas_protetivas"
    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(String, unique=True, index=True)
    nome_vitima = Column(String)
    telefone_vitima = Column(String)
    distancia_minima = Column(Float, default=500.0)
    # Novo campo para a foto do agressor (URL de uma foto hospedada)
    foto_agressor_url = Column(String, nullable=True) 

# --- FUNÇÃO DE ALERTA REAL ATUALIZADA ---
async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url):
    """Envia o Alerta com Link do Mapa e Foto do Agressor"""
    payload = {
        "timestamp": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO DETECTADA",
        "vitima": vitima,
        "contato_vitima": telefone,
        "distancia_detectada": f"{round(distancia, 2)} metros",
        "link_rastreamento": maps_url,  # Link para abrir no Google Maps
        "foto_agressor": foto_url or "https://via.placeholder.com/150?text=Sem+Foto+Cadastrada",
        "mensagem_emergencia": f"⚠️ ALERTA: O agressor está violando o limite de {round(distancia, 2)}m da vítima {vitima}."
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(WEBHOOK_URL, json=payload)
            return "Sucesso: Dados táticos enviados para Central."
        except Exception as e:
            return f"Erro no envio: {str(e)}"

# --- ENDPOINT MONITORAR ATUALIZADO ---
@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...),
    agressor_lat: float = Query(...),
    agressor_long: float = Query(...),
    vitima_lat: float = Query(...),
    vitima_long: float = Query(...),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso).first()
    if not medida:
        raise HTTPException(status_code=404, detail="Medida não encontrada.")

    distancia = geodesic((agressor_lat, agressor_long), (vitima_lat, vitima_long)).meters
    
    status_msg = "SEGURO"
    notif_status = "N/A"
    maps_url = f"https://www.google.com/maps?q={agressor_lat},{agressor_long}"

    if distancia <= medida.distancia_minima:
        status_msg = "🚨 INVASÃO DE PERÍMETRO 🚨"
        
        # Agora passamos também o link do mapa e a foto cadastrada
        notif_status = await disparar_alerta_urgente(
            medida.telefone_vitima, 
            distancia, 
            medida.nome_vitima, 
            maps_url, 
            medida.foto_agressor_url
        )
        
        # Log pericial
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(distancia, 2),
            lat_agressor=agressor_lat, long_agressor=agressor_long,
            status_notificacao=notif_status
        )
        db.add(log)
        db.commit()

    return {
        "status": status_msg,
        "dados_enviados_webhook": notif_status,
        "link_maps": maps_url
    }
