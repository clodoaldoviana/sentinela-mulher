import os
from datetime import datetime, time
import httpx
from typing import Optional
import pytz # Importante para o horário do Amazonas

from fastapi import FastAPI, Query, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import uvicorn

# --- CONFIGURAÇÃO DE TIMEZONE (MANAUS) ---
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
    data_validade = Column(String) # Formato DD/MM/AAAA

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

WEBHOOK_URL = "https://webhook.site/01357d1f-0b8a-4527-884f-41579b128943"

async def disparar_alerta_urgente(telefone, distancia, vitima, maps_url, foto_url, vigente):
    status_juridico = "VIGENTE - AUTORIZA PRISÃO" if vigente else "EXPIRADA - INFORMATIVO"
    payload = {
        "timestamp": datetime.now(tz_am).strftime("%d/%m/%Y %H:%M:%S"),
        "evento": "VIOLAÇÃO DE PERÍMETRO",
        "status_juridico": status_juridico,
        "vitima": vitima,
        "contato": telefone,
        "distancia": f"{round(distancia, 2)}m",
        "mapa": maps_url,
        "foto": foto_url
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(WEBHOOK_URL, json=payload)
            return f"Alerta Enviado ({status_juridico})"
        except: return "Falha na Central"

app = FastAPI(title="Sentinela Mulher - Amazonas")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- LÓGICA DE VALIDAÇÃO DE DATA (MELHORADA) ---
def verificar_vigencia(data_str: str) -> bool:
    try:
        # Pega a data atual de Manaus
        agora = datetime.now(tz_am)
        # Converte a data de validade (DD/MM/AAAA) para objeto datetime
        data_exp = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        # Define a expiração para o final do dia (23:59:59)
        data_exp = tz_am.localize(datetime.combine(data_exp.date(), time(23, 59, 59)))
        
        return agora <= data_exp
    except:
        return True # Por segurança, se a data estiver errada, mantém vigente

# --- ENDPOINTS ---

@app.post("/token", tags=["Segurança"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username == "admin" and form_data.password == "senha123":
        return {"access_token": "chave_secreta_policial", "token_type": "bearer"}
    raise HTTPException(status_code=401)

@app.post("/cadastrar-medida", tags=["Administrativo"])
async def cadastrar_medida(
    processo: str = Body(...), vitima: str = Body(...), telefone: str = Body(...),
    validade: str = Body(..., description="DD/MM/AAAA"),
    raio: float = Body(500.0), foto: str = Body(None),
    db: Session = Depends(get_db)
):
    nova = MedidaProtetiva(processo_id=processo, nome_vitima=vitima, telefone_vitima=telefone,
                           distancia_minima=raio, foto_agressor_url=foto, data_validade=validade)
    db.add(nova); db.commit()
    return {"status": "Cadastro Realizado"}

@app.post("/monitorar", tags=["Operacional"])
async def monitorar_proximidade(
    id_caso: str = Query(...), ag_lat: float = Query(...), ag_long: float = Query(...),
    vi_lat: float = Query(...), vi_long: float = Query(...),
    db: Session = Depends(get_db)
):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == id_caso).first()
    if not medida: raise HTTPException(status_code=404)

    # Chamada da nova lógica de vigência
    vigente = verificar_vigencia(medida.data_validade)

    dist = geodesic((ag_lat, ag_long), (vi_lat, vi_long)).meters
    notif = "N/A"
    
    if dist <= medida.distancia_minima:
        maps = f"https://www.google.com/maps?q={ag_lat},{ag_long}"
        notif = await disparar_alerta_urgente(medida.telefone_vitima, dist, medida.nome_vitima, maps, medida.foto_agressor_url, vigente)
        
        log = HistoricoViolacao(medida_id=medida.id, distancia_detectada=round(dist, 2),
                               lat_agressor=ag_lat, long_agressor=ag_long, 
                               status_notificacao=notif, medida_vigente_na_hora="SIM" if vigente else "NÃO")
        db.add(log); db.commit()

    return {
        "status": "🚨 ALERTA" if dist <= medida.distancia_minima else "OK", 
        "vigencia": "ATIVA" if vigente else "EXPIRADA",
        "distancia": f"{round(dist, 2)}m"
    }

@app.get("/relatorio-impressao/{processo_id}", response_class=HTMLResponse, tags=["Relatórios"])
async def gerar_relatorio_visual(processo_id: str, db: Session = Depends(get_db)):
    medida = db.query(MedidaProtetiva).filter(MedidaProtetiva.processo_id == processo_id).first()
    if not medida: return "<h1>Processo não localizado</h1>"
    
    vigente_hoje = verificar_vigencia(medida.data_validade)
    status_txt = "VIGENTE" if vigente_hoje else "EXPIRADA"
    cor = "#28a745" if vigente_hoje else "#dc3545"

    violacoes = db.query(HistoricoViolacao).filter(HistoricoViolacao.medida_id == medida.id).all()
    linhas = ""
    geo = Nominatim(user_agent="sentinela_am")

    for v in violacoes:
        try:
            l = geo.reverse(f"{v.lat_agressor}, {v.long_agressor}", timeout=3)
            end = l.address if l else "Localização via GPS"
        except: end = "Coordenadas registradas"
        
        v_cor = "green" if v.medida_vigente_na_hora == "SIM" else "red"
        linhas += f"<tr><td>{v.timestamp.strftime('%d/%m/%Y %H:%M')}</td><td>{v.distancia_detectada}m</td><td>{end}</td><td style='color:{v_cor}; font-weight:bold;'>{v.medida_vigente_na_hora}</td></tr>"

    return f"""
    <html>
    <head><style>
        body {{ font-family: sans-serif; padding: 40px; }}
        .header {{ border-bottom: 4px solid #003366; text-align: center; }}
        .badge {{ background: {cor}; color: white; padding: 10px; border-radius: 5px; font-weight: bold; display: inline-block; }}
        .box {{ background: #f8f9fa; padding: 20px; border-radius: 10px; display: flex; align-items: center; border: 1px solid #ddd; margin-top:10px; }}
        .foto {{ width: 120px; border: 3px solid #003366; border-radius: 5px; margin-right: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background: #003366; color: white; }}
    </style></head>
    <body>
        <div class="header">
            <h2>RELATÓRIO PERICIAL DE MONITORAMENTO</h2>
            <div class="badge">STATUS JURÍDICO ATUAL: {status_txt}</div>
        </div>
        <div class="box">
            <img src="{medida.foto_agressor_url or 'https://via.placeholder.com/150'}" class="foto">
            <div>
                <p><b>PROCESSO:</b> {medida.processo_id} | <b>VÍTIMA:</b> {medida.nome_vitima}</p>
                <p><b>VALIDADE:</b> {medida.data_validade} | <b>AÇÃO:</b> { "PRISÃO" if vigente_hoje else "RENOVAR" }</p>
            </div>
        </div>
        <table>
            <thead><tr><th>Data/Hora (Manaus)</th><th>Distância</th><th>Localização</th><th>Vigente na Hora?</th></tr></thead>
            <tbody>{linhas or "<tr><td colspan='4' style='text-align:center;'>Sem registros</td></tr>"}</tbody>
        </table>
        <br><button onclick="window.print()">Salvar PDF</button>
    </body></html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
