import os
import datetime
import httpx
from typing import Optional
from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
import uvicorn

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./sentinela_mulher.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELOS DO BANCO ---
class MedidaProtetiva(Base):
    __tablename__ = "medidas_protetivas"
    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(String, unique=True, index=True)
    nome_vitima = Column(String)
    telefone_vitima = Column(String)
    distancia_minima = Column(Float, default=500.0)
    foto_agressor_url = Column(String, nullable=True) # Campo para a foto

class HistoricoViolacao(Base):
    __tablename__ = "historico_violacoes"
    id = Column(Integer, primary_key=True, index=True)
    medida_id = Column(Integer, ForeignKey("medidas_protetivas.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    distancia_detectada = Column(Float)
    lat_agressor = Column(Float)
    long_agressor = Column(Float)
    status_notificacao = Column(String)

# Cria as tabelas se não existirem
Base.metadata.create_all(bind=engine)

# --- CONFIGURAÇÃO DE ALERTA REAL ---
# SUBSTITUA ABAIXO PELO SEU LINK DO WEBHOOK.SITE
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url):
    payload = {
        "timestamp": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO DETECTADA",
        "vitima": vitima,
        "contato_vitima": telefone,
        "distancia_detectada": f"{round(distancia, 2)} metros",
        "link_rastreamento_maps": maps_url,
        "foto_do_agressor": foto_url or "Sem foto cadastrada",
        "mensagem_emergencia": f"⚠️ ALERTA: O agressor está a {round(distancia, 2)}m da vítima {vitima}."
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Envia para o Webhook.site
            await client.post(WEBHOOK_URL, json=payload)
            return "Sucesso: Dados táticos enviados para Central."
        except Exception as e:
            return f"Erro no envio: {str(e)}"

# --- INICIALIZAÇÃO DO APP ---
app = FastAPI(title="Sentinela Mulher - Projeto Clodoaldo S. Viana")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- SEGURANÇA ---
@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial", "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Credenciais Inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial":
        raise HTTPException(status_code=401, detail="Token Inválido")
    return token

# --- ENDPOINTS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(..., example="001-AM-2026"),
    vitima: str = Body(..., example="Maria da Silva"),
    telefone: str = Body(..., example="5592999999999"),
    raio_minimo: float = Body(500.0),
    foto_url: str = Body(None, example="https://link-da-foto.com/agressor.jpg"),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    if db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo).first():
        raise HTTPException(status_code=400, detail="Processo já cadastrado.")
    
    nova_medida = MedidaProtetiva(
        processo_id=processo, nome_vitima=vitima, 
        telefone_vitima=telefone, distancia_minima=raio_minimo,
        foto_agressor_url=foto_url
    )
    db.add(nova_medida)
    db.commit()
    return {"status": "Sucesso", "mensagem": f"Proteção ativada para {vitima}"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(..., description="ID do Processo"),
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
    maps_url = f"https://www.google.com/maps?q={agressor_lat},{agressor_long}"
    
    status_msg = "SEGURO"
    notif_status = "Nenhuma violação"

    if distancia <= medida.distancia_minima:
        status_msg = "🚨 INVASÃO DE PERÍMETRO 🚨"
        notif_status = await disparar_alerta_urgente(
            medida.telefone_vitima, distancia, medida.nome_vitima, maps_url, medida.foto_agressor_url
        )
        
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(distancia, 2),
            lat_agressor=agressor_lat, long_agressor=agressor_long,
            status_notificacao=notif_status
        )
        db.add(log)
        db.commit()

    return {
        "vitima": medida.nome_vitima,
        "status": status_msg,
        "distancia_atual": f"{round(distancia, 2)}m",
        "alerta_webhook": notif_status,
        "mapa_agressor": maps_url
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
