import os
import datetime
import httpx
from typing import Optional

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
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
    foto_agressor_url = Column(String, nullable=True)
    data_validade = Column(String, default="Indeterminada")

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
# IMPORTANTE: Substitua pela sua URL do Webhook.site
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url):
    payload = {
        "timestamp": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO",
        "vitima": vitima,
        "contato": telefone,
        "distancia": f"{round(distancia, 2)}m",
        "mapa": maps_url,
        "foto_agressor": foto_url or "Sem foto",
        "prioridade": "CRÍTICA"
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(WEBHOOK_URL, json=payload)
            return "Sucesso: Central Notificada"
        except:
            return "Erro: Falha no Gateway"

# --- INICIALIZAÇÃO E SEGURANÇA ---
app = FastAPI(title="Sentinela Mulher - Amazonas")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial", "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Credenciais Inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial":
        raise HTTPException(status_code=401, detail="Token Inválido")
    return token

# --- ENDPOINTS OPERACIONAIS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(..., example="00123-AM-2026"),
    vitima: str = Body(..., example="Maria da Silva"),
    telefone: str = Body(..., example="5592999999999"),
    validade: str = Body(..., example="12/12/2026"),
    raio_minimo: float = Body(500.0),
    foto_url: str = Body(None),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    nova_medida = MedidaProtetiva(
        processo_id=processo, nome_vitima=vitima, telefone_vitima=telefone,
        distancia_minima=raio_minimo, foto_agressor_url=foto_url, data_validade=validade
    )
    db.add(nova_medida)
    db.commit()
    return {"status": "Proteção Ativada"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...),
    agressor_lat: float = Query(...), agressor_long: float = Query(...),
    vitima_lat: float = Query(...), vitima_long: float = Query(...),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso).first()
    if not medida: raise HTTPException(status_code=404, detail="Não encontrado")

    distancia = geodesic((agressor_lat, agressor_long), (vitima_lat, vitima_long)).meters
    maps_url = f"https://www.google.com/maps?q={agressor_lat},{agressor_long}"
    
    status_msg = "SEGURO"
    notif = "N/A"

    if distancia <= medida.distancia_minima:
        status_msg = "🚨 INVASÃO DETECTADA 🚨"
        notif = await disparar_alerta_urgente(medida.telefone_vitima, distancia, medida.nome_vitima, maps_url, medida.foto_agressor_url)
        
        log = HistoricoViolacao(
            medida_id=medida.id, distancia_detectada=round(distancia, 2),
            lat_agressor=agressor_lat, long_agressor=agressor_long, status_notificacao=notif
        )
        db.add(log)
        db.commit()

    return {"status": status_msg, "distancia": f"{round(distancia, 2)}m", "notificacao": notif}

# --- ENDPOINT DE RELATÓRIO VISUAL (IMPRESSÃO) ---
@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id).first()
    if not medida: return "<h1>Processo não localizado</h1>"
    
    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    linhas = ""
    geo = Nominatim(user_agent="sentinela_am")

    for v in violacoes:
        try:
            loc = geo.reverse(f"{v.lat_agressor}, {v.long_agressor}", timeout=3)
            end = loc.address if loc else "Endereço aproximado"
        except: end = "Ver coordenadas no mapa"
        
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{end}</td><td>OK</td></tr>"

    return f"""
    <html>
    <head><style>
        body {{ font-family: sans-serif; padding: 30px; }}
        .header {{ border-bottom: 3px solid #003366; padding-bottom: 10px; text-align: center; }}
        .box {{ background: #f4f4f4; padding: 15px; margin: 20px 0; border-radius: 8px; display: flex; align-items: center; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #ccc; padding: 10px; text-align: left; }}
        th {{ background: #003366; color: white; }}
        .foto {{ width: 100px; height: 100px; border-radius: 5px; margin-right: 20px; object-fit: cover; border: 2px solid #003366; }}
    </style></head>
    <body>
        <div class="header"><h1>Relatório Pericial de Monitoramento</h1><p>Projeto Sentinela Mulher - Amazonas</p></div>
        <div class="box">
            <img src="{medida.foto_agressor_url or ''}" class="foto" alt="Foto">
            <div>
                <p><b>PROCESSO:</b> {medida.processo_id} | <b>VÍTIMA:</b> {medida.nome_vitima}</p>
                <p><b>VALIDADE:</b> {medida.data_validade} | <b>VIOLAÇÕES:</b> {len(violacoes)}</p>
            </div>
        </div>
        <table>
            <thead><tr><th>Data/Hora</th><th>Distância</th><th>Localização</th><th>Status</th></tr></thead>
            <tbody>{linhas or "<tr><td colspan='4'>Sem registros</td></tr>"}</tbody>
        </table>
        <br><button onclick="window.print()">Imprimir PDF</button>
    </body></html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
