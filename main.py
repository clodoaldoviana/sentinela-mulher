import os
import datetime
from typing import Optional

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from geopy.distance import geodesic
import uvicorn

# --- CONFIGURAÇÃO DO BANCO DE DADOS (PILAR 3) ---
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

# --- INICIALIZAÇÃO DO APP ---
app = FastAPI(
    title="Projeto Sentinela Mulher",
    description="Sistema de Monitoramento e Proteção (Lei Maria da Penha) com Registro Pericial.",
    version="1.3.0"
)

# --- SEGURANÇA (OAUTH2) ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Em produção, utilize hashing e banco de dados para senhas
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial", "token_type": "bearer"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais Inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token Inválido")
    return token

# --- FUNÇÕES DE APOIO (PILAR 1) ---
def disparar_alerta_urgente(telefone, distancia):
    """Simulação de disparo via WhatsApp/SMS"""
    # Integração real com Twilio/Evolution API entraria aqui
    return f"Sucesso: Alerta enviado para {telefone}"

# --- ENDPOINTS ADMINISTRATIVOS ---
@app.post("/cadastrar-medida", tags=["Administrativo"], status_code=status.HTTP_201_CREATED)
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
    return {"mensagem": f"Medida para {vitima} cadastrada."}

# --- ENDPOINTS OPERACIONAIS ---
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
        raise HTTPException(status_code=404, detail="Processo não encontrado.")

    distancia = geodesic((agressor_lat, agressor_long), (vitima_lat, vitima_long)).meters
    
    status_alerta = "SEGURO"
    notif_status = "N/A"
    maps_url = None

    if distancia <= medida.distancia_minima:
        status_alerta = "🚨 INVASÃO DE PERÍMETRO 🚨"
        maps_url = f"https://www.google.com/maps?q={agressor_lat},{agressor_long}"
        notif_status = disparar_alerta_urgente(medida.telefone_vitima, distancia)
        
        # Log de Invasão
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(distancia, 2),
            lat_agressor=agressor_lat, long_agressor=agressor_long,
            status_notificacao=notif_status
        )
        db.add(log)
        db.commit()

    return {
        "projeto": "Sentinela Mulher",
        "vitima": medida.nome_vitima,
        "distancia": f"{round(distancia, 2)}m",
        "status": status_alerta,
        "alerta_vitima": notif_status,
        "mapa_agressor": maps_url
    }

@app.get("/relatorio", tags=["Inteligência"])
async def gerar_relatorio(token: str = Depends(verificar_token), db: Session = Depends(get_db)):
    logs = db.query(HistoricoViolacao).all()
    return {"total_ocorrencias": len(logs), "dados": logs}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
