import os
from datetime import datetime, time
import httpx
from typing import Optional
import pytz

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import uvicorn

# --- CONFIGURAÇÃO DE TIMEZONE ---
tz_am = pytz.timezone('America/Manaus')

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
    foto_agressor_url = Column(String, nullable=True)
    data_validade = Column(String)

class HistoricoViolacao(Base):
    __tablename__ = "historico_violacoes"
    id = Column(Integer, primary_key=True, index=True)
    medida_id = Column(Integer, ForeignKey("medidas_protetivas.id"))
    timestamp = Column(DateTime, default=lambda: datetime.now(tz_am))
    distancia_detectada = Column(Float)
    lat_agressor = Column(Float)
    long_agressor = Column(Float)
    status_notificacao = Column(String)
    medida_vigente_na_hora = Column(String)

Base.metadata.create_all(bind=engine)

# --- SEGURANÇA OAUTH2 ---
app = FastAPI(title="Sentinela Mulher - Amazonas (Seguro)")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Usuário e Senha para a Demonstração
USER_ADMIN = "admin"
PASS_ADMIN = "senha123"

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == USER_ADMIN and form_data.password == PASS_ADMIN:
        return {"access_token": "chave_secreta_policial_2026", "token_type": "bearer"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

def verificar_token(token: str = Depends(oauth2_scheme)):
    if token != "chave_secreta_policial_2026":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")
    return token

# --- LÓGICA DE NEGÓCIO ---
WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url, vigente):
    status_juridico = "VIGENTE - AUTORIZA PRISÃO" if vigente else "EXPIRADA - MONITORAMENTO INFORMATIVO"
    payload = {
        "timestamp": datetime.now(tz_am).strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "ALERTA SENTINELA: VIOLAÇÃO",
        "status_juridico": status_juridico,
        "vitima": vitima,
        "distancia": f"{round(distancia, 2)}m",
        "mapa": maps_url,
        "foto": foto_url or "https://via.placeholder.com/150"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try: await client.post(WEBHOOK_URL, json=payload)
        except: pass

def verificar_vigencia(data_str: str) -> bool:
    try:
        agora = datetime.now(tz_am)
        data_exp = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        data_exp_final = tz_am.localize(datetime.combine(data_exp.date(), time(23, 59, 59)))
        return agora <= data_exp_final
    except: return True

# --- ENDPOINTS PROTEGIDOS ---

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(...), vitima: str = Body(...), telefone: str = Body(...),
    validade: str = Body(...), raio: float = Body(500.0), foto: str = Body(None),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    nova = MedidaProtetiva(processo_id=processo.strip(), nome_vitima=vitima, telefone_vitima=telefone,
                           distancia_minima=raio, foto_agressor_url=foto, data_validade=validade)
    db.add(nova); db.commit()
    return {"status": "Segurança ativada para este processo"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...), ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db), token: str = Depends(verificar_token)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso.strip()).first()
    if not medida: raise HTTPException(status_code=404, detail="Processo não cadastrado")

    vigente = verificar_vigencia(medida.data_validade)
    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    
    if dist <= medida.distancia_minima:
        maps = f"https://www.google.com/maps?q={ag_lat},{ag_long}"
        await disparar_alerta_urgente(medida.telefone_vitima, dist, medida.nome_vitima, maps, medida.foto_agressor_url, vigente)
        
        log = HistoricoViolacao(medida_id=medida.id, distancia_detectada=round(dist, 2),
                               lat_agressor=ag_lat, long_agressor=ag_long, 
                               status_notificacao="Alerta Enviado", medida_vigente_na_hora="SIM" if vigente else "NÃO")
        db.add(log); db.commit()

    return {
        "alerta": dist <= medida.distancia_minima,
        "vigencia": "ATIVA" if vigente else "EXPIRADA",
        "distancia": f"{round(dist, 2)}m",
        "vitima": medida.nome_vitima,
        "agressor_foto": medida.foto_agressor_url
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    # Nota: Este endpoint é visual para impressão. 
    # Em produção, ele também deveria validar o token via Cookie ou Query,
    # mas para sua apresentação, deixaremos acessível via link direto do ID.
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id.strip()).first()
    if not medida: return "<h1>Acesso Negado ou Processo Inexistente</h1>"
    
    vigente_hoje = verificar_vigencia(medida.data_validade)
    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    
    linhas = ""
    for v in violacoes:
        v_cor = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{v.lat_agressor}, {v.long_agressor}</td><td style='color:{v_cor};'>{v.medida_vigente_na_hora}</td></tr>"

    return f"""
    <html><body style="font-family:sans-serif; padding:30px;">
        <h2 style="color:#003366;">RELATÓRIO RESTRITO - SENTINELA MULHER</h2>
        <hr>
        <p><b>STATUS JURÍDICO:</b> {'VIGENTE' if vigente_hoje else 'EXPIRADO'}</p>
        <p><b>VÍTIMA:</b> {medida.nome_vitima} | <b>PROCESSO:</b> {medida.processo_id}</p>
        <table border="1" width="100%" style="border-collapse:collapse;">
            <tr style="background:#eee;"><th>Data</th><th>Distância</th><th>Localização</th><th>Vigente?</th></tr>
            {linhas or "<tr><td colspan='4' align='center'>Sem ocorrências</td></tr>"}
        </table>
        <br><button onclick="window.print()">Imprimir PDF Oficial</button>
    </body></html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
