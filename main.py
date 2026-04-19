import os
import datetime
import httpx  # Biblioteca para disparos reais de rede
from typing import Optional

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from geopy.distance import geodesic
import uvicorn

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./sentinela_mulher.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MedidaProtetiva(Base):
    __tablename__ = "medidas_protetivas"
    id = Column(Integer, primary_key=True, index=True)
    processo_id = Column(String, unique=True, index=True)
    nome_vitima = Column(String)
    telefone_vitima = Column(String)
    distancia_minima = Column(Float, default=500.0)

class HistoricoViolacao(Base):
    __tablename__ = "historico_violacoes"
    id = Column(Integer, primary_key=True, index=True)
    medida_id = Column(Integer, ForeignKey("medidas_protetivas.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    distancia_detectada = Column(Float)
    lat_agressor = Column(Float)
    long_agressor = Column(Float)
    status_notificacao = Column(String)

Base.metadata.create_all(bind=engine)

# --- CONFIGURAÇÃO DE ALERTA REAL ---
# IMPORTANTE: Substitua o link abaixo pelo seu link gerado no Webhook.site
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima):
    """Envia um alerta real para uma central externa via Webhook"""
    payload = {
        "timestamp": datetime.datetime.now().isoformat(),
        "alerta": "INVASÃO DE PERÍMETRO",
        "vitima": vitima,
        "contato_vitima": telefone,
        "distancia_metros": round(distancia, 2),
        "mensagem": f"🚨 ALERTA CRÍTICO: O agressor está a {round(distancia, 2)}m da vítima {vitima}."
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(WEBHOOK_URL, json=payload)
            if response.status_code == 200 or response.status_code == 201:
                return f"Sucesso: Notificação enviada para Central e Vítima ({telefone})"
            return f"Erro no servidor de envio: {response.status_code}"
        except Exception as e:
            return f"Falha na comunicação: {str(e)}"

# --- INICIALIZAÇÃO DO APP ---
app = FastAPI(title="Sentinela Mulher - Operacional")
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
    processo: str = Body(..., example="0012345-67.2026.8.04.0001"),
    vitima: str = Body(..., example="Maria da Silva"),
    telefone: str = Body(..., example="5592999999999"),
    raio_minimo: float = Body(500.0),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    if db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo).first():
        raise HTTPException(status_code=400, detail="Processo já cadastrado.")
    
    nova_medida = MedidaProtetiva(
        processo_id=processo, nome_vitima=vitima, 
        telefone_vitima=telefone, distancia_minima=raio_minimo
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
    # 1. Busca dados no banco
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso).first()
    if not medida:
        raise HTTPException(status_code=404, detail="Medida não encontrada no sistema.")

    # 2. Cálculo de distância
    distancia = geodesic((agressor_lat, agressor_long), (vitima_lat, vitima_long)).meters
    
    status_msg = "MONITORAMENTO ATIVO - SEGURO"
    notif_status = "Nenhuma ação necessária"
    maps_url = None

    # 3. Lógica de Alerta Real
    if distancia <= medida.distancia_minima:
        status_msg = "🚨 ALERTA: VIOLAÇÃO DE PERÍMETRO 🚨"
        maps_url = f"https://www.google.com/maps?q={agressor_lat},{agressor_long}"
        
        # DISPARO REAL
        notif_status = await disparar_alerta_urgente(medida.telefone_vitima, distancia, medida.nome_vitima)
        
        # Log no Banco
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(distancia, 2),
            lat_agressor=agressor_lat, long_agressor=agressor_long,
            status_notificacao=notif_status
        )
        db.add(log)
        db.commit()

    return {
        "vitima": medida.nome_vitima,
        "distancia_atual": f"{round(distancia, 2)}m",
        "status": status_msg,
        "notificacao_real": notif_status,
        "localizacao_agressor": maps_url
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
